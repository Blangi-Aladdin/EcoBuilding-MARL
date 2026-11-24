"""Experimental DX speed translation synchronized to the HVAC predictor."""
from numbers import Integral

from ._cooling_base import CoolingCommand as BaselineCoolingCommand


class CoolingCommand(BaselineCoolingCommand):
    LOAD = ("Zone Predicted Sensible Load to Setpoint Heat Transfer Rate", "OFFICE")

    def initialize(self, state):
        super().initialize(state)
        self._load_handle = self._exchange.get_variable_handle(state, *self.LOAD)
        if self._load_handle < 0:
            self.detach()
            raise RuntimeError(f"DX predictor variable unavailable: {self.LOAD}")

    def detach(self):
        super().detach()
        self._requested = self._speed = 0
        self._load_handle = None

    def apply(self, action):
        if isinstance(action, bool) or not isinstance(action, Integral) or action not in (0,1,2):
            raise ValueError("Cooling action must be an integer 0, 1 or 2")
        state, (availability, _, setpoint) = self._binding()
        if action:
            self._exchange.set_actuator_value(state, setpoint, self._setpoint_c)
            self._exchange.set_actuator_value(state, availability, 1)
        else:
            super().apply(action)
            self._speed = 0
        self._requested = int(action)

    @property
    def speed_override(self):
        return self._speed

    def synchronize_speed(self):
        """Use this predictor pass, after load prediction and before unitary simulation."""
        state, (_, speed, _) = self._binding()
        load = self._exchange.get_variable_value(state, self._load_handle)
        if self._exchange.api_error_flag(state):
            raise RuntimeError("EnergyPlus API failed to read the zone predictor")
        target = self._requested if load < 0 else 0
        if target != self._speed:
            if target:
                self._exchange.set_actuator_value(state, speed, target)
            else:
                self._exchange.reset_actuator(state, speed)
            self._speed = target
        return load

    def release(self):
        super().release()
        self._requested = self._speed = 0
