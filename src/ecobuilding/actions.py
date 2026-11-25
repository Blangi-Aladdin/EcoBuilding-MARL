"""Experimental Heating/Cooling/Ventilation action translation."""
from numbers import Integral

import numpy as np

from .cooling import CoolingCommand

HEATING = ("Schedule:Constant", "Schedule Value", "OFFICE HEATING POWER FRACTION")
VENTILATION = ("Zone Ventilation", "Air Exchange Flow Rate", "BALANCED OUTDOOR AIR")
VENTILATION_M3H = (0, 40, 120)


class ActuationError(RuntimeError):
    """A write can fail after other actuator values have already changed."""


class CheckedExchange:
    """Track completed writes, including those delegated to CoolingCommand."""

    def __init__(self, exchange):
        self.exchange = exchange
        self.completed = []
        self.names = {}

    def __getattr__(self, name):
        return getattr(self.exchange, name)

    def get_actuator_handle(self, state, *key):
        handle = self.exchange.get_actuator_handle(state, *key)
        if handle >= 0:
            self.names[handle] = key[-1]
        return handle

    def _write(self, method, state, handle, *value):
        operation = (method, self.names[handle], *value)
        try:
            getattr(self.exchange, method)(state, handle, *value)
            if self.exchange.api_error_flag(state):
                raise RuntimeError("EnergyPlus API error flag")
        except Exception as exc:
            raise ActuationError(
                f"Attempted operation {operation}; confirmed prior writes: {self.completed}; "
                "the attempted write's final state is unknown"
            ) from exc
        self.completed.append(operation)

    def set_actuator_value(self, state, handle, value):
        self._write("set_actuator_value", state, handle, value)

    def reset_actuator(self, state, handle):
        self._write("reset_actuator", state, handle)


class HVACController:
    """Bind actuator handles to one state and keep the last successful command."""

    def __init__(self, exchange, *, cooling_setpoint_c, max_heating_setpoint_c=21):
        self._exchange = CheckedExchange(exchange)
        self._cooling = CoolingCommand(
            self._exchange, setpoint_c=cooling_setpoint_c,
            max_heating_setpoint_c=max_heating_setpoint_c,
        )
        self.detach()

    @staticmethod
    def validate_action(action):
        if isinstance(action, np.ndarray):
            if action.shape != (3,):
                raise ValueError("HVAC action shape must be (3,)")
        elif not isinstance(action, (list, tuple)) or len(action) != 3:
            raise ValueError("HVAC action must contain three components")
        if any(isinstance(x, (bool, np.bool_)) or not isinstance(x, Integral) or x not in (0, 1, 2)
               for x in action):
            raise ValueError("Each HVAC action must be an integer 0, 1 or 2")
        return tuple(int(x) for x in action)

    def request_variables(self, state):
        self._exchange.request_variable(state, *CoolingCommand.LOAD)

    def initialize(self, state):
        if self._state is not None:
            raise RuntimeError("Detach before initializing another state")
        if not self._exchange.api_data_fully_ready(state):
            raise RuntimeError("EnergyPlus API data is not ready")
        try:
            handles = [self._exchange.get_actuator_handle(state, *key) for key in (HEATING, VENTILATION)]
            missing = [key for key, handle in zip((HEATING, VENTILATION), handles) if handle < 0]
            if missing:
                raise RuntimeError(f"HVAC actuators unavailable: {missing}")
            self._cooling.initialize(state)
        except Exception:
            self.detach()
            raise
        self._state, self._handles = state, handles

    def _begin_writes(self):
        if self._state is None or self._failed:
            raise RuntimeError("HVAC controller requires a valid, initialized simulation state")
        self._exchange.completed.clear()
        if self._exchange.api_error_flag(self._state):
            self._failed = True
            raise ActuationError("EnergyPlus API error flag set before any HVAC write")

    def apply(self, action):
        normalized = self.validate_action(action)
        heating, cooling, ventilation = normalized
        self._begin_writes()
        heat_handle, vent_handle = self._handles
        try:
            self._exchange.set_actuator_value(self._state, heat_handle, heating / 2)
            self._cooling.apply(cooling)
            self._exchange.set_actuator_value(
                self._state, vent_handle, VENTILATION_M3H[ventilation] / 3600,
            )
        except ActuationError:
            self._failed = True
            raise
        self._last_action = normalized
        return normalized

    def synchronize_cooling(self):
        """Update the speed override for the current predictor pass."""
        self._begin_writes()
        try:
            return self._cooling.synchronize_speed()
        except Exception:
            self._failed = True
            raise

    @property
    def cooling_speed_override(self):
        return self._cooling.speed_override

    def get_last_action(self):
        return self._last_action

    def get_last_writes(self):
        """Snapshot of writes confirmed during the most recent apply or release."""
        return tuple(self._exchange.completed)

    def all_off(self):
        return self.apply((0, 0, 0))

    def release(self):
        """Call after zone reporting, ahead of the next schedule update."""
        self._begin_writes()
        try:
            self._cooling.release()
            for handle in self._handles:
                self._exchange.reset_actuator(self._state, handle)
        except ActuationError:
            self._failed = True
            raise

    def detach(self):
        self._cooling.detach()
        self._exchange.names.clear()
        self._exchange.completed.clear()
        self._state = self._handles = self._last_action = None
        self._failed = False
