"""Translate a discrete Cooling action for one initialized EnergyPlus run."""
from math import isfinite
from numbers import Integral, Real


class CoolingCommand:
    ACTUATORS = (
        ("Schedule:Compact", "Schedule Value", "DX SCHEDULED AVAILABILITY"),
        ("Coil Speed Control", "Unitary System DX Coil Speed Value", "OFFICE DX UNIT"),
        ("Schedule:Compact", "Schedule Value", "SUMMER COOLING SETPOINT"),
    )

    def __init__(self, exchange, *, setpoint_c, max_heating_setpoint_c):
        for value in (setpoint_c, max_heating_setpoint_c):
            if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
                raise ValueError("Setpoints must be finite real temperatures in °C")
        if setpoint_c <= max_heating_setpoint_c:
            raise ValueError("Cooling setpoint must exceed the maximum heating setpoint")
        self._exchange = exchange
        self._setpoint_c = float(setpoint_c)
        self.detach()

    def initialize(self, state):
        """Resolve handles once per new state, after api_data_fully_ready."""
        if self._handles is not None:
            raise RuntimeError("Detach before binding to a new EnergyPlus state")
        if not self._exchange.api_data_fully_ready(state):
            raise RuntimeError("EnergyPlus API data is not ready")
        handles = [self._exchange.get_actuator_handle(state, *key) for key in self.ACTUATORS]
        missing = [key for key, handle in zip(self.ACTUATORS, handles) if handle < 0]
        if missing:
            raise RuntimeError(f"Cooling actuators unavailable: {missing}")
        self._state = state
        self._handles = handles

    def detach(self):
        """Forget the state and handles after the simulation ends."""
        self._state = self._handles = None

    def _binding(self):
        if self._handles is None:
            raise RuntimeError("Initialize Cooling for the current EnergyPlus state")
        return self._state, self._handles

    def apply(self, action):
        """Apply at the start of a zone step, before heat balance initialization."""
        if isinstance(action, bool) or not isinstance(action, Integral) or action not in (0, 1, 2):
            raise ValueError("Cooling action must be an integer 0, 1 or 2")
        state, (availability, speed, setpoint) = self._binding()
        if action == 0:
            self._exchange.set_actuator_value(state, availability, 0)
            self._exchange.reset_actuator(state, speed)
            return
        self._exchange.set_actuator_value(state, setpoint, self._setpoint_c)
        self._exchange.set_actuator_value(state, availability, 1)
        self._exchange.set_actuator_value(state, speed, int(action))

    def release(self):
        """Release all overrides after reporting the previous zone step."""
        state, handles = self._binding()
        for handle in handles:
            self._exchange.reset_actuator(state, handle)
