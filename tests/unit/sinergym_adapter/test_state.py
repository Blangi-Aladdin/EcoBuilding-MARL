"""Exercise the causal MDP state with software doubles."""

from datetime import datetime, timedelta
from math import cos, sin, tau
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
from gymnasium.spaces import Box

from ecobuilding.sinergym_adapter import EcoBuildingEnv, Episode, STATE_NAMES
from ecobuilding.sinergym_adapter.transport import EpisodeError, Result

from .doubles import WorkerFactory


class StateTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        root = Path(__file__).resolve().parents[3]
        self.model = root / "models/office_1zone.epJSON"
        self.weather = self.root / "weather.epw"
        self.weather.touch()  # Software doubles only require an existing path.
        guard = patch("pyenergyplus.runtime.Runtime.run_energyplus", side_effect=AssertionError("Physical run forbidden"))
        guard.start()
        self.addCleanup(guard.stop)
        self.env = EcoBuildingEnv(self.model, self.weather, self.root, Episode((8, 7)), reward_mode="legacy_zero")
        self.addCleanup(self.env.close)

    def test_state_order_units_and_bounds(self):
        start = datetime(2025, 8, 7, 13, 15)
        physical = {
            "diagnostics": {"substep_means": {"indoor_c": 21, "indoor_rh_pct": 43, "co2_ppm": 654}},
            "indoor": {"indoor_c": 99, "indoor_rh_pct": 99, "co2_ppm": 999},
            "outdoor": {"outdoor_c": 14, "outdoor_rh_pct": 66, "direct_solar_w_m2": 123,
                        "diffuse_solar_w_m2": 45, "wind_m_s": 5},
            "occupancy": {"people": 2}, "energy": {"total_j": 1_800_000},
            "time": {"weekday_api": 2},
        }
        result = Result(1, 0, start, start + timedelta(minutes=15), physical, (2, 0, 1), (2, 0, 1))
        vector, info = self.env._project(result, previous_temperature=20.25)
        hour_angle, year_angle = tau * 13.5 / 24, tau * 218 / 365
        expected = [21, 43, 654, 14, 66, 123, 45, 5, 2, sin(hour_angle), cos(hour_angle),
                    0, 1, sin(year_angle), cos(year_angle), 2, 0, 1, 0.75, 0.5]
        np.testing.assert_allclose(vector, expected, atol=1e-7)
        self.assertEqual(STATE_NAMES, (
            "indoor_temperature", "indoor_relative_humidity", "indoor_co2", "outdoor_temperature",
            "outdoor_relative_humidity", "direct_solar_radiation", "diffuse_solar_radiation", "wind_speed",
            "occupant_count", "hour_sin", "hour_cos", "weekday_sin", "weekday_cos", "day_of_year_sin",
            "day_of_year_cos", "previous_heating_action", "previous_cooling_action",
            "previous_ventilation_action", "delta_indoor_temperature", "previous_energy_kwh",
        ))
        self.assertIsInstance(self.env.observation_space, Box)
        self.assertEqual(vector.shape, (20,))
        self.assertEqual(vector.dtype, np.float32)
        self.assertTrue(self.env.observation_space.contains(vector))
        self.assertIs(info["physical"], physical)
        physical["outdoor"].pop("wind_m_s")
        with self.assertRaisesRegex(EpisodeError, "wind_m_s"):
            self.env._project(result, previous_temperature=20.25)

    def test_midnight_history_and_transition_alignment(self):
        base_factory = WorkerFactory()

        def factory(*args, **kwargs):
            worker = base_factory(*args, **kwargs)
            exchange = worker.exchange
            read = exchange.get_variable_value

            def read_at_interval(state, handle):
                value = read(state, handle)
                if handle == exchange.handles.get((state, ("Zone Mean Air Temperature", "OFFICE"))):
                    return value + (0.75 if exchange.when.day == 7 else 0.0)
                return value

            exchange.get_variable_value = read_at_interval
            return worker

        with patch("ecobuilding.sinergym_adapter.environment.EcoBuildingSimulator", factory):
            initial, info = self.env.reset(seed=42, options={
                "occupancy_mode": "explicit", "occupancy_profile": [2, 0] + [1] * 94})
            self.assertEqual(info["end"], "2025-08-07T00:00:00")
            # August 7 is Thursday in 2025, but Monday in the configured simulation.
            np.testing.assert_allclose(initial[9:15], [0, 1, 0, 1, sin(tau*218/365), cos(tau*218/365)])
            np.testing.assert_array_equal(initial[15:], np.zeros(5))
            self.assertEqual(initial[0], 24)
            self.assertEqual(initial[1], 53)
            self.assertEqual(initial[8], 1)
            self.assertEqual(info["physical"]["energy"]["total_j"], 92700)
            with self.assertRaises(ValueError):
                self.env.step([9, 0, 0])
            first, reward, terminated, truncated, transition = self.env.step([1, 2, 0])
            self.assertEqual((reward, terminated, truncated), (0.0, False, False))
            self.assertEqual(transition["start"], info["end"])
            self.assertEqual(transition["end"], "2025-08-07T00:15:00")
            self.assertEqual(transition["applied"], (1, 2, 0))
            self.assertEqual(first[8], 2)
            np.testing.assert_allclose(first[9:11], [sin(tau/96), cos(tau/96)])
            np.testing.assert_allclose(first[15:], [1, 2, 0, 0.75, 92700/3600000])
            first[0] = -100
            transition["physical"]["diagnostics"]["substep_means"]["indoor_c"] = -100
            second, *_, second_info = self.env.step([0, 1, 2])
            self.assertEqual(second_info["start"], transition["end"])
            self.assertEqual(second[8], 0)
            np.testing.assert_allclose(second[15:], [0, 1, 2, 0, 92700/3600000])
            reset, reset_info = self.env.reset(seed=42)
            np.testing.assert_array_equal(reset, initial)
            self.assertIsNone(reset_info["applied"])
            self.assertTrue(self.env.observation_space.contains(reset))
