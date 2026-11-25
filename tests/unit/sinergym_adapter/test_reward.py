"""Reward accounting using the real facade and software callbacks."""

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from ecobuilding.sinergym_adapter import EcoBuildingEnv, Episode, RewardConfig
from ecobuilding.sinergym_adapter.reward import interval_reward
from ecobuilding.sinergym_adapter.transport import Result

from .doubles import WorkerFactory


class RewardTests(unittest.TestCase):
    config = RewardConfig()

    @staticmethod
    def interval(start, *, temperature=22, humidity=50, co2=800, people=1,
                 energy_j=0, action=(2, 2, 1)):
        physical = {
            "diagnostics": {"substep_means": {
                "indoor_c": temperature, "indoor_rh_pct": humidity, "co2_ppm": co2}},
            "indoor": {"indoor_c": 22, "indoor_rh_pct": 50, "co2_ppm": 800},
            "occupancy": {"people": people}, "energy": {"total_j": energy_j},
        }
        return Result(1, 0, start, start + timedelta(minutes=15), physical, action, action)

    def test_five_components_and_weighted_sum(self):
        start = datetime(2025, 1, 1)
        result = self.interval(start, temperature=18, humidity=30, co2=1500, energy_j=900_000)
        reward, detail = interval_reward(result, (0, 1, 0), self.config)
        self.assertEqual(detail["components"], dict(
            energy=0.25, temperature=0.4, co2=0.5, humidity=0.5, action_change=4/6))
        for name, value in dict(energy=0.25, temperature=1.2, co2=1, humidity=0.05,
                                action_change=0.05*4/6).items():
            self.assertAlmostEqual(detail["weighted"][name], value)
        self.assertAlmostEqual(reward, -2.533333333333333)
        self.assertEqual(reward, detail["total"])

    def test_seasons_occupation_and_inclusive_bounds(self):
        for month, season, low, high in ((1,"winter",20,23), (4,"spring",20,26),
                                         (7,"summer",23,26), (10,"autumn",20,26)):
            for people in (0, 1, 2):
                bounds = (low, high) if people else (15, 28)
                for temperature, humidity in zip(bounds, (40, 60), strict=True):
                    with self.subTest(month=month, people=people, temperature=temperature):
                        result = self.interval(datetime(2025, month, 1), temperature=temperature,
                                               people=people, co2=1000, humidity=humidity)
                        reward, detail = interval_reward(result, None, self.config)
                        self.assertEqual(reward, 0)
                        self.assertEqual(detail["constraints"]["season"], season)
                        self.assertEqual(detail["constraints"]["temperature_c"], bounds)
                for temperature in (bounds[0] - 5, bounds[1] + 5):
                    result = self.interval(datetime(2025, month, 1), temperature=temperature,
                                           people=people, co2=2000, humidity=80)
                    _, detail = interval_reward(result, None, self.config)
                    self.assertEqual(detail["weighted"]["temperature"], 3 if people else 0.5)
                    self.assertEqual(detail["components"]["humidity"], 1 if people else 0)
                    self.assertEqual(detail["components"]["co2"], 1 if people else 0)

    def test_unbounded_penalties_and_config(self):
        result = self.interval(datetime(2025, 1, 1), temperature=3, humidity=0, co2=9000,
                               energy_j=3_600_000)
        _, detail = interval_reward(result, None, self.config)
        self.assertEqual(detail["components"]["temperature"], 3.4)
        self.assertEqual(detail["components"]["humidity"], 2)
        self.assertEqual(detail["components"]["co2"], 8)
        _, detail = interval_reward(result, (0, 0, 0), RewardConfig(
            winter_temperature_c=[0, 5], energy_scale_kwh=2, occupied_co2_limit_ppm=8500,
            co2_scale_ppm=500, co2_weight=4, occupied_humidity_pct=(0, 60), action_weight=0))
        self.assertEqual(detail["weighted"], dict(
            energy=0.5, temperature=0, co2=4, humidity=0, action_change=0))
        for settings in (dict(energy_scale_kwh=0), dict(co2_weight=-1),
                         dict(occupied_humidity_pct=(60, 40))):
            with self.assertRaises(ValueError):
                RewardConfig(**settings)

    def test_midnight_uses_actual_interval_month(self):
        for start, before, after in (
                (datetime(2025, 8, 31, 23, 45), "summer", "autumn"),
                (datetime(2025, 11, 30, 23, 45), "autumn", "winter"),
                (datetime(2025, 12, 31, 23, 45), "winter", "winter")):
            result = self.interval(start, temperature=21)
            _, detail = interval_reward(result, None, self.config)
            self.assertEqual(detail["constraints"]["season"], before)
            _, detail = interval_reward(self.interval(result.end, temperature=21), None, self.config)
            self.assertEqual(detail["constraints"]["season"], after)

    def test_facade_reward_alignment_actions_and_reset(self):
        model = Path(__file__).resolve().parents[3] / "models/office_1zone.epJSON"
        factory = WorkerFactory()
        with TemporaryDirectory() as directory, patch(
                "ecobuilding.sinergym_adapter.environment.EcoBuildingSimulator", factory), patch(
                "pyenergyplus.runtime.Runtime.run_energyplus", side_effect=AssertionError("Physical run forbidden")):
            root = Path(directory)
            weather = root / "fixture.epw"
            weather.touch()
            env = EcoBuildingEnv(model, weather, root, Episode((8, 31), days=2))
            try:
                initial, initial_info = env.reset(options=dict(
                    occupancy_mode="explicit", occupancy_profile=[0, 1] + [2] * 190))
                self.assertEqual(initial[8], 1)
                self.assertNotIn("reward", initial_info)
                first, reward, terminated, truncated, info = env.step([2, 2, 2])
                self.assertEqual(first[8], 0)
                self.assertEqual(info["start"], initial_info["end"])
                self.assertEqual(info["reward"]["components"]["action_change"], 0)
                self.assertAlmostEqual(reward, -92700/3600000)
                self.assertFalse(terminated or truncated)

                _, reward, _, _, info = env.step([0, 0, 0])
                self.assertTrue(info["reward"]["constraints"]["occupied"])
                self.assertEqual(info["reward"]["components"]["action_change"], 1)
                self.assertAlmostEqual(reward, -92700/3600000 - 0.05)
                for _ in range(94):
                    _, _, _, _, info = env.step([0, 0, 0])
                self.assertEqual(info["end"], "2025-09-01T00:00:00")
                self.assertEqual(info["reward"]["constraints"]["season"], "summer")
                _, _, _, _, info = env.step([0, 0, 0])
                self.assertEqual(info["reward"]["constraints"]["season"], "autumn")
                env.reset()
                _, _, _, _, info = env.step([2, 2, 2])
                self.assertEqual(info["reward"]["components"]["action_change"], 0)
            finally:
                env.close()
