"""Calendar, separation and reproducibility checks without a simulator."""

from datetime import date, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ecobuilding.episodes import DEFAULT_CONFIG, EpisodePlan


def control_days(start):
    return {start + timedelta(days=i) for i in range(7)}


class EpisodePlanTests(unittest.TestCase):
    def setUp(self):
        self.plan = EpisodePlan.load()

    def test_split_sizes_dates_and_full_windows(self):
        expected_ranges = {
            "train": (("01-23", "02-22"), ("03-08", "03-30"), ("04-28", "05-11"),
                      ("06-19", "08-09"), ("09-17", "11-10"), ("12-24", "12-25")),
            "validation": (("05-25", "06-05"), ("11-24", "12-10")),
            "test": (("01-08", "01-09"), ("04-13", "04-14"), ("08-23", "09-03")),
        }
        seen = set()
        for (name, split), (weather_count, start_count) in zip(
                self.plan.splits.items(), ((255, 177), (55, 29), (55, 16)), strict=True):
            weather = set(split.weather_days)
            expected = {day for day in weather
                        if any(lo <= day.strftime("%m-%d") <= hi for lo, hi in expected_ranges[name])}
            self.assertEqual(set(split.admissible_starts), expected)
            self.assertEqual((len(weather), len(expected)), (weather_count, start_count))
            self.assertFalse(seen & weather)
            seen.update(weather)
            union = set()
            seasons = set()
            for start in split.admissible_starts:
                prep = {start - timedelta(days=i) for i in range(1, 8)}
                control = control_days(start)
                window = prep | control
                self.assertEqual(len(window), 14)
                self.assertLessEqual(window, weather)
                self.assertEqual(min(window).year, max(window).year)
                self.assertFalse(min(window) <= date(2006, 2, 28) < max(window))
                union.update(window)
                period_seasons = {day.month % 12 // 3 for day in control}
                if len(period_seasons) == 1:
                    seasons.update(period_seasons)
            self.assertEqual(union, weather)
            self.assertEqual(seasons, {0, 1, 2, 3})
        self.assertEqual(len(seen), 365)

    def test_evaluation_scenarios_and_seeds(self):
        validated = {
            "validation": ("05-25", "06-01", "06-05", "11-24", "12-01", "12-10"),
            "test": ("01-08", "01-09", "04-13", "04-14", "08-23", "08-24", "08-25",
                     "09-01", "09-02", "09-03"),
        }
        used_seeds = {self.plan.selection_seed}
        for name, base in (("train", 0), ("validation", 10000), ("test", 20000)):
            scenarios = self.plan.scenarios(name)
            seeds = [s.occupancy_seed for s in scenarios]
            count = 200 if name == "train" else len(validated[name])
            self.assertEqual(seeds, list(range(base, base + count)))
            self.assertFalse(used_seeds.intersection(seeds))
            used_seeds.update(seeds)
            if name == "train":
                continue
            self.assertEqual(tuple(s.date.strftime("%m-%d") for s in scenarios), validated[name])
            seasons = set()
            for scenario in scenarios:
                period = {d.month % 12 // 3 for d in control_days(scenario.date)}
                self.assertEqual(len(period), 1)
                seasons.update(period)
            self.assertEqual(seasons, {0, 1, 2, 3})

    def test_manifest_reproducibility_and_reset_options(self):
        self.assertEqual(self.plan.selection_seed, 380803)
        self.assertEqual(self.plan.gamma, 0.99)
        self.assertEqual(date(self.plan.reference_year, 1, 1).weekday(), 6)
        with TemporaryDirectory() as directory:
            for name in self.plan.splits:
                path = Path(directory) / f"{name}.json"
                self.plan.write_manifest(name, path)
                original = path.read_bytes()
                self.assertEqual(json.loads(original), EpisodePlan.load().manifest(name))
                scenarios = self.plan.load_manifest(path)
                self.assertEqual(scenarios, self.plan.scenarios(name))
                for scenario in scenarios:
                    options = scenario.reset_options()
                    self.assertEqual(options["occupancy_mode"], "dynamic")
                    self.assertEqual(options["occupancy_seed"], scenario.occupancy_seed)
                    self.assertEqual(options["episode"].steps, 672)
                    self.assertEqual(options["episode"].first_weekday, scenario.date.weekday())
                with self.assertRaises(FileExistsError):
                    self.plan.write_manifest(name, path)
                manifest = json.loads(original)
                record = manifest["scenarios"][0]
                record["start_day"] = "Friday" if record["start_day"] != "Friday" else "Monday"
                path.write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError, "weekday"):
                    self.plan.load_manifest(path)

    def test_invalid_configurations(self):
        changes = (
            (lambda c: c.update(history_days=6), "seven"),
            (lambda c: c["calendar"].update(reference_year=2024), "calendar"),
            (lambda c: c.update(episode_selection_seed=0), "selection seed"),
            (lambda c: c["splits"]["train"].update(occupancy_seed_range=[0, 10000]), "seed overlap"),
            (lambda c: c["splits"]["train"]["blocks"].__setitem__(0, ["01-15", "02-28"]), "Weather overlap"),
            (lambda c: c["splits"]["train"]["blocks"].__setitem__(0, ["01-17", "02-28"]), "365"),
            (lambda c: c["splits"]["validation"]["fixed_starts"].__setitem__(0, "05-24"), "fixed"),
            (lambda c: c["splits"]["validation"]["fixed_starts"].__setitem__(0, "05-26"), "fixed"),
        )
        for change, message in changes:
            config = json.loads(DEFAULT_CONFIG.read_text())
            change(config)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                EpisodePlan(config)
