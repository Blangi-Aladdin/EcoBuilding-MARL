"""Disjoint weather splits and reproducible EcoBuilding episode manifests."""

from calendar import isleap
from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path
from random import Random

from .sinergym_adapter.model import Episode, WEEKDAYS


SPLITS = ("train", "validation", "test")
DAY = timedelta(days=1)
DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "configs/rl/office_mdp.json"


def _days(start, end):
    return {start + i * DAY for i in range((end - start).days + 1)}


def _one_season(start, days):
    seasons = {(start + i * DAY).month % 12 // 3 for i in range(days)}
    return next(iter(seasons)) if len(seasons) == 1 else None


def _four_seasons(starts, episode_days):
    return {_one_season(start, episode_days) for start in starts} >= set(range(4))


def _seed(value):
    if type(value) is not int or value < 0:
        raise ValueError("Seeds must be nonnegative integers")
    return value


@dataclass(frozen=True)
class EpisodeScenario:
    """A standalone reset specification shared by both evaluation agents."""

    date: date
    occupancy_seed: int
    episode_days: int = 7
    history_days: int = 7

    @property
    def episode(self):
        history_start = self.date - self.history_days * DAY
        return Episode((self.date.month, self.date.day), self.episode_days, self.history_days,
                       start_day=WEEKDAYS[history_start.weekday()])

    def reset_options(self):
        return {"episode": self.episode, "occupancy_mode": "dynamic", "occupancy_seed": self.occupancy_seed}

    def to_record(self):
        episode = self.episode
        return {"control_start": self.date.strftime("%m-%d"), "start_day": episode.start_day,
                "occupancy_seed": self.occupancy_seed}

    @classmethod
    def from_record(cls, record, reference_year):
        scenario = cls(date.fromisoformat(f"{reference_year}-{record['control_start']}"),
                       _seed(record["occupancy_seed"]))
        if scenario.episode.start_day != record["start_day"]:
            raise ValueError("Manifest weekday does not match the synthetic calendar")
        return scenario


@dataclass(frozen=True)
class WeatherSplit:
    weather_days: tuple[date, ...]
    admissible_starts: tuple[date, ...]
    occupancy_seeds: tuple[int, ...]
    fixed_starts: tuple[date, ...]


class EpisodePlan:
    def __init__(self, config):
        self.episode_days = config["episode_days"]
        self.history_days = config["history_days"]
        self.decision_interval_seconds = config["decision_interval_seconds"]
        self.occupancy_mode = config["occupancy_mode"]
        self.gamma = config["gamma"]
        if ((self.episode_days, self.history_days, self.decision_interval_seconds, self.occupancy_mode)
                != (7, 7, 900, "dynamic")
                or not all(type(x) is int for x in
                           (self.episode_days, self.history_days, self.decision_interval_seconds))):
            raise ValueError("Expected seven control days, seven history days, 900 s and dynamic occupancy")
        if type(self.gamma) not in (float, int) or not 0 < self.gamma <= 1:
            raise ValueError("Gamma must be in (0, 1]")

        calendar = config["calendar"]
        self.reference_year = calendar["reference_year"]
        if (type(self.reference_year) is not int or not 1 <= self.reference_year < 9999
                or isleap(self.reference_year) or calendar["january_1"] != "Sunday"
                or date(self.reference_year, 1, 1).weekday() != 6):
            raise ValueError("The synthetic calendar must be a non-leap year beginning on Sunday")
        self.selection_seed = _seed(config["episode_selection_seed"])

        if config["splits"].keys() != set(SPLITS):
            raise ValueError("Expected train, validation and test splits")
        self.splits = {}
        owned_days, used_seeds = set(), set()
        for name in SPLITS:
            split = self._load_split(name, config["splits"][name])
            if owned_days.intersection(split.weather_days):
                raise ValueError(f"Weather overlap across splits: {name}")
            if used_seeds.intersection(split.occupancy_seeds):
                raise ValueError(f"Occupancy seed overlap across splits: {name}")
            owned_days.update(split.weather_days)
            used_seeds.update(split.occupancy_seeds)
            self.splits[name] = split
        if len(owned_days) != 365:
            raise ValueError("The three weather splits must cover all 365 days")
        if self.selection_seed in used_seeds:
            raise ValueError("The episode selection seed must be separate from occupancy seeds")

    @classmethod
    def load(cls, path=DEFAULT_CONFIG):
        with Path(path).open(encoding="utf-8") as stream:
            return cls(json.load(stream))

    def _date(self, value):
        return date.fromisoformat(f"{self.reference_year}-{value}")

    def _load_split(self, name, config):
        weather = set()
        for first, last in config["blocks"]:
            start, end = self._date(first), self._date(last)
            days = _days(start, end)
            if not days or weather.intersection(days):
                raise ValueError(f"Reversed or overlapping weather block: {name}")
            weather.update(days)

        starts = []
        for start in sorted(weather):
            if not _days(start - self.history_days * DAY, start + (self.episode_days - 1) * DAY) <= weather:
                continue
            try:
                EpisodeScenario(start, 0, self.episode_days, self.history_days).episode
            except ValueError:
                # Episode rejects windows crossing the year or a potential leap day.
                continue
            starts.append(start)
        if not _four_seasons(starts, self.episode_days):
            raise ValueError(f"Missing full-season control windows: {name}")

        low, high = map(_seed, config["occupancy_seed_range"])
        if low > high:
            raise ValueError(f"Reversed seed range: {name}")
        seeds = tuple(range(low, high + 1))
        fixed = tuple(map(self._date, config.get("fixed_starts", ())))
        if name == "train":
            if fixed:
                raise ValueError("Training starts are selected by the episode RNG")
        elif (len(fixed) != len(seeds) or len(set(fixed)) != len(fixed) or not set(fixed) <= set(starts)
              or not _four_seasons(fixed, self.episode_days)
              or any(_one_season(d, self.episode_days) is None for d in fixed)):
            raise ValueError(f"Invalid fixed evaluation starts: {name}")
        return WeatherSplit(tuple(sorted(weather)), tuple(starts), seeds, fixed)

    def scenarios(self, split):
        spec = self.splits[split]
        starts = spec.fixed_starts
        if split == "train":
            rng = Random(self.selection_seed)
            starts = [rng.choice(spec.admissible_starts) for _ in spec.occupancy_seeds]
        return tuple(EpisodeScenario(start, seed, self.episode_days, self.history_days)
                     for start, seed in zip(starts, spec.occupancy_seeds, strict=True))

    def _manifest_metadata(self, split):
        return {"split": split, "reference_year": self.reference_year, "january_1": "Sunday",
                "episode_days": self.episode_days, "history_days": self.history_days,
                "decision_interval_seconds": self.decision_interval_seconds,
                "occupancy_mode": self.occupancy_mode, "gamma": self.gamma,
                "episode_selection_seed": self.selection_seed if split == "train" else None}

    def manifest(self, split):
        return {**self._manifest_metadata(split),
                "scenarios": [scenario.to_record() for scenario in self.scenarios(split)]}

    def write_manifest(self, split, path):
        """Save the selected schedule to a new JSON file."""
        manifest = self.manifest(split)
        with Path(path).open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2)
            stream.write("\n")

    def load_manifest(self, path):
        """Replay the recorded dates without drawing from the training RNG."""
        with Path(path).open(encoding="utf-8") as stream:
            data = json.load(stream)
        records = data.pop("scenarios")
        split = data["split"]
        if split not in self.splits or data != self._manifest_metadata(split):
            raise ValueError("Manifest metadata differs from the episode plan")
        scenarios = tuple(EpisodeScenario.from_record(row, self.reference_year) for row in records)
        spec = self.splits[split]
        dates = tuple(scenario.date for scenario in scenarios)
        if (tuple(scenario.occupancy_seed for scenario in scenarios) != spec.occupancy_seeds
                or not set(dates) <= set(spec.admissible_starts)
                or (split != "train" and dates != spec.fixed_starts)):
            raise ValueError("Manifest dates or occupancy seeds differ from the split")
        return scenarios
