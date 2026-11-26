"""Seasonal rule-based HVAC controller for the EcoBuilding MDP."""

from dataclasses import dataclass
import json
from math import isfinite
from pathlib import Path

import numpy as np


STATE_NAMES = (
    "indoor_temperature", "indoor_relative_humidity", "indoor_co2",
    "outdoor_temperature", "outdoor_relative_humidity",
    "direct_solar_radiation", "diffuse_solar_radiation", "wind_speed",
    "occupant_count", "hour_sin", "hour_cos", "weekday_sin", "weekday_cos",
    "day_of_year_sin", "day_of_year_cos", "previous_heating_action",
    "previous_cooling_action", "previous_ventilation_action",
    "delta_indoor_temperature", "previous_energy_kwh",
)


TEMPERATURE_BOUNDS = {
    "winter": (20.0, 23.0),
    "spring": (20.0, 26.0),
    "summer": (23.0, 26.0),
    "autumn": (20.0, 26.0),
}

SEASONS = (
    "winter", "winter", "spring", "spring", "spring", "summer",
    "summer", "summer", "autumn", "autumn", "autumn", "winter",
)


def _finite_number(value, name, *, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


@dataclass(frozen=True)
class RBCConfig:
    heating_hysteresis_c: float = 0.5
    high_heating_offset_c: float = 1.5
    cooling_hysteresis_c: float = 0.5
    high_cooling_offset_c: float = 1.5
    occupied_low_co2_ppm: float = 800.0
    occupied_low_co2_exit_ppm: float = 700.0
    occupied_high_co2_ppm: float = 1000.0
    occupied_high_co2_exit_ppm: float = 900.0

    def __post_init__(self):
        for name in (
            "heating_hysteresis_c", "high_heating_offset_c",
            "cooling_hysteresis_c", "high_cooling_offset_c",
            "occupied_low_co2_ppm", "occupied_low_co2_exit_ppm",
            "occupied_high_co2_ppm", "occupied_high_co2_exit_ppm",
        ):
            minimum = 0.0
            value = _finite_number(getattr(self, name), name, minimum=minimum)
            object.__setattr__(self, name, value)
        if self.occupied_low_co2_exit_ppm > self.occupied_low_co2_ppm:
            raise ValueError("occupied_low_co2_exit_ppm must not exceed occupied_low_co2_ppm")
        if self.occupied_high_co2_exit_ppm > self.occupied_high_co2_ppm:
            raise ValueError("occupied_high_co2_exit_ppm must not exceed occupied_high_co2_ppm")

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("RBC configuration must be a JSON object")
        allowed = set(cls.__dataclass_fields__)
        if data.keys() - allowed:
            raise ValueError(f"Unsupported RBC configuration keys: {sorted(data.keys() - allowed)}")
        return cls(**data)

    def to_dict(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


class SeasonalRBC:
    """Hysteretic thermostat with occupancy-aware CO2 ventilation."""

    def __init__(self, config=None):
        self.config = RBCConfig() if config is None else config
        if not isinstance(self.config, RBCConfig):
            raise TypeError("config must be an RBCConfig")
        self.reset()

    def reset(self):
        self._heating = 0
        self._cooling = 0
        self._ventilation = 0
        return (0, 0, 0)

    @staticmethod
    def _observation_values(observation):
        if isinstance(observation, dict):
            values = []
            for name in STATE_NAMES:
                if name not in observation:
                    raise ValueError(f"Missing MDP observation: {name}")
                values.append(observation[name])
        else:
            array = np.asarray(observation)
            if array.shape != (20,) or array.dtype != np.float32:
                raise ValueError("RBC requires a float32 MDP observation of shape (20,)")
            values = array.tolist()
        temperature, occupants, co2 = values[0], values[8], values[2]
        if not all(isinstance(value, (int, float, np.number)) and isfinite(float(value))
                   for value in (temperature, occupants, co2)):
            raise ValueError("RBC physical observations must be finite numbers")
        if occupants not in (0.0, 1.0, 2.0):
            raise ValueError("RBC occupant count must be 0, 1 or 2")
        return float(temperature), int(occupants), float(co2)

    @staticmethod
    def _month(info):
        if info is not None:
            physical = info.get("physical")
            if isinstance(physical, dict):
                time = physical.get("time")
                if isinstance(time, dict) and isinstance(time.get("month"), int):
                    if 1 <= time["month"] <= 12:
                        return time["month"]
        raise ValueError("RBC needs the current month in info['physical']['time']")

    def act(self, observation, info=None):
        temperature, occupants, co2 = self._observation_values(observation)
        month = self._month(info)

        if occupants:
            low, high = TEMPERATURE_BOUNDS[SEASONS[month - 1]]
            heating, cooling = self._thermostat(temperature, low, high)
            ventilation = self._ventilation_rule(co2)
        else:
            heating, cooling = self._thermostat(temperature, 15.0, 28.0)
            ventilation = 0

        action = (heating, cooling, ventilation)
        self._heating, self._cooling, self._ventilation = action
        return action

    def _thermostat(self, temperature, low, high):
        heating = self._heating
        cooling = self._cooling
        cfg = self.config

        heat_high = low - cfg.high_heating_offset_c
        heat_medium = low - cfg.heating_hysteresis_c
        if temperature <= heat_high:
            heating = 2
        elif temperature <= heat_medium:
            heating = 1
        elif temperature >= low + cfg.heating_hysteresis_c:
            heating = 0

        cool_medium = high + cfg.cooling_hysteresis_c
        cool_high = high + cfg.high_cooling_offset_c
        if temperature >= cool_high:
            cooling = 2
        elif temperature >= cool_medium:
            cooling = 1
        elif temperature <= high - cfg.cooling_hysteresis_c:
            cooling = 0

        return heating, cooling

    def _ventilation_rule(self, co2):
        cfg = self.config
        ventilation = self._ventilation

        if ventilation == 2:
            if co2 <= cfg.occupied_high_co2_exit_ppm:
                ventilation = 1
        elif ventilation == 1:
            if co2 >= cfg.occupied_high_co2_ppm:
                ventilation = 2
            elif co2 <= cfg.occupied_low_co2_exit_ppm:
                ventilation = 0
        else:
            if co2 >= cfg.occupied_high_co2_ppm:
                ventilation = 2
            elif co2 >= cfg.occupied_low_co2_ppm:
                ventilation = 1

        if ventilation == 1 and co2 <= cfg.occupied_low_co2_exit_ppm:
            ventilation = 0
        return ventilation
