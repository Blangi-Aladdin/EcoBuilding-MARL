"""Comfort constraints and reward for one completed control interval."""

from dataclasses import dataclass
from math import isfinite
from numbers import Real

from ecobuilding.observations import joules_to_kwh

from .state import MEASUREMENTS, read_number


SEASONS = (
    "winter", "winter", "spring", "spring", "spring", "summer",
    "summer", "summer", "autumn", "autumn", "autumn", "winter",
)


@dataclass(frozen=True)
class RewardConfig:
    winter_temperature_c: tuple[float, float] = (20.0, 23.0)
    spring_temperature_c: tuple[float, float] = (20.0, 26.0)
    summer_temperature_c: tuple[float, float] = (23.0, 26.0)
    autumn_temperature_c: tuple[float, float] = (20.0, 26.0)
    unoccupied_temperature_c: tuple[float, float] = (15.0, 28.0)
    occupied_humidity_pct: tuple[float, float] = (40.0, 60.0)
    occupied_co2_limit_ppm: float = 1000.0

    energy_scale_kwh: float = 1.0
    temperature_scale_c: float = 5.0
    co2_scale_ppm: float = 1000.0
    humidity_scale_pct: float = 20.0
    action_scale: float = 6.0
    occupied_temperature_weight: float = 3.0
    unoccupied_temperature_weight: float = 0.5
    co2_weight: float = 2.0
    humidity_weight: float = 0.1
    action_weight: float = 0.05

    def __post_init__(self):
        for name, value in vars(self).items():
            if name.endswith(("_temperature_c", "_humidity_pct")):
                if (not isinstance(value, (tuple, list)) or len(value) != 2
                        or not all(_finite_real(endpoint) for endpoint in value) or value[0] > value[1]):
                    raise ValueError(f"{name} must be an ordered pair of finite bounds")
                object.__setattr__(self, name, tuple(value))
            elif (not _finite_real(value) or value < 0 or ("scale" in name and value == 0)):
                raise ValueError(f"{name} must be finite and nonnegative, with positive scales")


def _finite_real(value):
    return isinstance(value, Real) and not isinstance(value, bool) and isfinite(value)


def _outside(value, bounds):
    lower, upper = bounds
    return max(0.0, lower - value, value - upper)


def interval_reward(result, previous_action, config):
    """Evaluate actual measures and actions of the interval beginning at result.start."""
    physical = result.physical
    temperature, humidity, co2 = (read_number(physical, path) for _, path in MEASUREMENTS[:3])
    occupants = read_number(physical, ("occupancy", "people"))
    occupied = occupants > 0
    season = SEASONS[result.start.month - 1]
    temperature_bounds = (getattr(config, f"{season}_temperature_c") if occupied
                          else config.unoccupied_temperature_c)
    humidity_bounds = config.occupied_humidity_pct if occupied else None
    co2_limit = config.occupied_co2_limit_ppm if occupied else None
    beta = config.occupied_temperature_weight if occupied else config.unoccupied_temperature_weight

    energy_kwh = joules_to_kwh(read_number(physical, ("energy", "total_j")))
    action_change = (sum(abs(a - previous) for a, previous in zip(result.applied, previous_action, strict=True))
                     if previous_action is not None else 0)
    components = {
        "energy": energy_kwh / config.energy_scale_kwh,
        "temperature": _outside(temperature, temperature_bounds) / config.temperature_scale_c,
        "co2": max(0.0, co2 - co2_limit) / config.co2_scale_ppm if occupied else 0.0,
        "humidity": _outside(humidity, humidity_bounds) / config.humidity_scale_pct if occupied else 0.0,
        "action_change": action_change / config.action_scale,
    }
    weighted = {
        "energy": components["energy"],
        "temperature": beta * components["temperature"],
        "co2": config.co2_weight * components["co2"],
        "humidity": config.humidity_weight * components["humidity"],
        "action_change": config.action_weight * components["action_change"],
    }
    total = -sum(weighted.values())
    return total, {
        "components": components,
        "weighted": weighted,
        "total": total,
        "constraints": {
            "season": season,
            "occupied": occupied,
            "occupants": occupants,
            "temperature_c": temperature_bounds,
            "co2_max_ppm": co2_limit,
            "relative_humidity_pct": humidity_bounds,
            "temperature_weight": beta,
        },
    }
