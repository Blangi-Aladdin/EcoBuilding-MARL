"""Prepare episode inputs without adapting the reference building to a DDY."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path


@dataclass(frozen=True)
class Episode:
    """Month/day window without an imposed year, matching the 36.7 replays."""

    first: tuple[int, int]
    days: int = 1
    history_days: int = 7
    start_day: str = "Monday"

    def __post_init__(self):
        if (type(self.days) is not int or self.days < 1 or
                type(self.history_days) is not int or self.history_days < 1 or
                len(self.first) != 2 or any(type(part) is not int for part in self.first)):
            raise ValueError("Use a month/day, positive control and history day counts")
        object.__setattr__(self, "first", tuple(self.first))
        if self.start_day not in WEEKDAYS:
            raise ValueError("Use an explicit weekday for the start of history")
        if self.history_start.year != 2001 or self.last_day.year != 2001:
            raise ValueError("Year boundaries are outside the prototype calendar")
        if self.history_start <= date(2001, 2, 28) < self.last_day:
            raise ValueError("Windows spanning a potential leap day are unsupported")

    @property
    def control_start(self):
        return date(2001, *self.first)

    @property
    def history_start(self):
        return self.control_start - timedelta(days=self.history_days)

    @property
    def last_day(self):
        return self.control_start + timedelta(days=self.days - 1)

    @property
    def steps(self):
        return self.days * 96

    @property
    def first_weekday(self):
        return (WEEKDAYS.index(self.start_day) + self.history_days) % 7


WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def check_model_changes(reference, copy, reporting_additions):
    """Compare all objects except the allowlisted fields and explicit reporting additions."""
    normalized = deepcopy(copy)
    original_period = next(iter(reference["RunPeriod"].values()))
    period = next(iter(normalized["RunPeriod"].values()))
    for name in ("begin_month", "begin_day_of_month", "end_month",
                 "end_day_of_month", "day_of_week_for_start_day"):
        period[name] = original_period[name]
    for object_type, objects in reporting_additions.items():
        for name, value in objects.items():
            if name in reference.get(object_type, {}) or normalized[object_type].pop(name) != value:
                raise ValueError(f"Invalid reporting addition: {name}")
        if object_type not in reference:
            if normalized[object_type]:
                raise ValueError(f"Unexpected reporting objects: {object_type}")
            del normalized[object_type]
    if normalized != reference:
        raise ValueError("Episode copy changes reference objects outside the allowlist")


def prepare_episode_inputs(model_path, weather_path, episode_dir, episode, *, report_facility=True):
    model_path, weather_path, episode_dir = (Path(p).resolve() for p in (model_path, weather_path, episode_dir))
    if not model_path.is_file() or not weather_path.is_file():
        raise FileNotFoundError(f"Missing input model or EPW: {model_path}, {weather_path}")
    reference = json.loads(model_path.read_bytes())
    if len(reference["RunPeriod"]) != 1 or len(reference["Timestep"]) != 1:
        raise ValueError("A unique RunPeriod and Timestep are required")
    if next(iter(reference["Timestep"].values()))["number_of_timesteps_per_hour"] != 4:
        raise ValueError("The model must retain four zone steps per hour")
    period = next(iter(reference["RunPeriod"].values()))
    if (period.get("use_weather_file_daylight_saving_period") != "No" or
            reference.get("RunPeriodControl:DaylightSavingTime") or
            "begin_year" in period or "end_year" in period):
        raise ValueError("Expected the validated year-free calendar without DST")
    model = deepcopy(reference)
    next(iter(model["RunPeriod"].values())).update(
        begin_month=episode.history_start.month, begin_day_of_month=episode.history_start.day,
        end_month=episode.last_day.month, end_day_of_month=episode.last_day.day,
        day_of_week_for_start_day=episode.start_day,
    )
    additions = {}
    meter = {"key_name": "Electricity:Facility", "reporting_frequency": "Timestep"}
    if report_facility and meter not in model.get("Output:Meter", {}).values():
        additions["Output:Meter"] = {"Prototype facility electricity": meter}
        model.setdefault("Output:Meter", {}).update(additions["Output:Meter"])
    check_model_changes(reference, model, additions)
    episode_dir.mkdir(parents=True, exist_ok=False)
    copy_path = episode_dir / model_path.name
    copy_path.write_text(json.dumps(model, indent=2) + "\n", encoding="utf-8")
    return copy_path, weather_path, episode_dir / "output"
