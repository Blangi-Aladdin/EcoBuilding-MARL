"""Exogenous occupancy inputs for an EnergyPlus simulation."""
from numbers import Integral


class OccupancyManager:
    ACTUATOR = ("Schedule:Compact", "Schedule Value", "OFFICE OCCUPANCY")
    OBSERVATION = ("Zone People Occupant Count", "OFFICE")

    def __init__(self, exchange):
        self.exchange = exchange
        self.detach()

    def initialize(self, state):
        if self._state is not None:
            raise RuntimeError("Detach before initializing a new state")
        if not self.exchange.api_data_fully_ready(state):
            raise RuntimeError("EnergyPlus API data is not ready")
        actuator = self.exchange.get_actuator_handle(state, *self.ACTUATOR)
        observation = self.exchange.get_variable_handle(state, *self.OBSERVATION)
        if min(actuator, observation) < 0:
            raise RuntimeError(f"Invalid occupancy handles: {actuator}, {observation}")
        self._state = state
        self._handles = actuator, observation
        return self._handles

    def detach(self):
        self._state = self._handles = None

    def _check_bound(self):
        if self._state is None:
            raise RuntimeError("Initialize OccupancyManager for the current state")

    @staticmethod
    def fraction(people):
        if isinstance(people, bool) or not isinstance(people, Integral) or not 0 <= people <= 2:
            raise ValueError("Occupancy must be an integer 0, 1 or 2")
        return people / 2

    def apply(self, people):
        fraction = self.fraction(people)
        self._check_bound()
        self.exchange.set_actuator_value(self._state, self._handles[0], fraction)
        return fraction

    def apply_profile(self, profile, step):
        if isinstance(step, bool) or not isinstance(step, Integral) or not 0 <= step < len(profile):
            raise ValueError("The zone-step index is outside the occupancy profile")
        return self.apply(profile[step])

    def observe(self):
        self._check_bound()
        return self.exchange.get_variable_value(self._state, self._handles[1])

    def release(self):
        """Release after zone reporting, before the next schedule update."""
        self._check_bound()
        self.exchange.reset_actuator(self._state, self._handles[0])
