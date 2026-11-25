"""Causal, unnormalized state for the EcoBuilding MDP."""

from datetime import date
from math import cos, isfinite, sin, tau

import numpy as np
from gymnasium.spaces import Box

from ecobuilding.observations import joules_to_kwh

from .transport import EpisodeError


MEASUREMENTS = (
    ("indoor_temperature", ("diagnostics", "substep_means", "indoor_c")),
    ("indoor_relative_humidity", ("diagnostics", "substep_means", "indoor_rh_pct")),
    ("indoor_co2", ("diagnostics", "substep_means", "co2_ppm")),
    ("outdoor_temperature", ("outdoor", "outdoor_c")),
    ("outdoor_relative_humidity", ("outdoor", "outdoor_rh_pct")),
    ("direct_solar_radiation", ("outdoor", "direct_solar_w_m2")),
    ("diffuse_solar_radiation", ("outdoor", "diffuse_solar_w_m2")),
    ("wind_speed", ("outdoor", "wind_m_s")),
    ("occupant_count", ("occupancy", "people")),
)

STATE_NAMES = tuple(name for name, _ in MEASUREMENTS) + (
    "hour_sin", "hour_cos", "weekday_sin", "weekday_cos", "day_of_year_sin", "day_of_year_cos",
    "previous_heating_action", "previous_cooling_action", "previous_ventilation_action",
    "delta_indoor_temperature", "previous_energy_kwh",
)


def observation_space():
    inf = np.inf
    return Box(
        low=np.array([-inf, 0, 0, -inf, 0, 0, 0, 0, 0, *([-1] * 6), 0, 0, 0, -inf, 0], dtype=np.float32),
        high=np.array([inf, inf, inf, inf, inf, inf, inf, inf, 2, *([1] * 6), 2, 2, 2, inf, inf], dtype=np.float32),
        dtype=np.float32,
    )


def read_number(mapping, path):
    value = mapping
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise EpisodeError(f"Missing observation field {path}")
        value = value[key]
    if not isinstance(value, (int, float, np.number)) or not isfinite(value):
        raise EpisodeError(f"Unavailable or nonnumeric observation field {path}")
    return value


def interval_temperature(physical):
    return read_number(physical, MEASUREMENTS[0][1])


def _cycle(index, period):
    angle = tau * index / period
    return sin(angle), cos(angle)


def state_values(result, previous_temperature):
    physical = result.physical
    values = [read_number(physical, path) for _, path in MEASUREMENTS]
    end = result.end
    hour = (end.hour * 3600 + end.minute * 60 + end.second + end.microsecond / 1_000_000) / 3600
    weekday_api = read_number(physical, ("time", "weekday_api"))
    if weekday_api not in range(1, 8):
        raise EpisodeError(f"Invalid EnergyPlus weekday: {weekday_api}")
    # EnergyPlus reports the simulated weekday of the interval being closed (Sunday = 1).
    day_roll = (end.date() - result.start.date()).days
    weekday = (weekday_api - 2 + day_roll) % 7
    try:
        day_index = (date(2001, end.month, end.day) - date(2001, 1, 1)).days
    except ValueError as exc:
        raise EpisodeError(f"Date outside the supported 365-day calendar: {end.date()}") from exc
    values.extend((*_cycle(hour, 24), *_cycle(weekday, 7), *_cycle(day_index, 365)))

    if result.kind == "initial":
        return [*values, 0, 0, 0, 0, 0]
    if previous_temperature is None or result.applied is None:
        raise EpisodeError("Missing history for a completed controlled interval")
    total_j = read_number(physical, ("energy", "total_j"))
    return [*values, *result.applied, values[0] - previous_temperature, joules_to_kwh(total_j)]
