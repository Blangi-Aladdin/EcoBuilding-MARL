"""Cross-component checks for the default MDP with no native EnergyPlus runs."""

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import warnings

from gymnasium.error import ResetNeeded
from gymnasium.spaces import MultiDiscrete
from gymnasium.utils.env_checker import check_env as gym_check
import numpy as np
from stable_baselines3.common.env_checker import check_env as sb3_check

from ecobuilding.episodes import EpisodePlan
from ecobuilding.occupancy_profiles import generate
from ecobuilding.sinergym_adapter import EcoBuildingEnv, Episode

from .doubles import WorkerFactory


class MDPQualification(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        output = Path(directory.name)
        model = Path(__file__).resolve().parents[3] / "models/office_1zone.epJSON"
        weather = output / "fixture.epw"
        weather.touch()
        guard = patch("pyenergyplus.runtime.Runtime.run_energyplus",
                      side_effect=AssertionError("Physical run forbidden"))
        guard.start()
        self.addCleanup(guard.stop)
        self.factory = WorkerFactory()
        substitute = patch("ecobuilding.sinergym_adapter.environment.EcoBuildingSimulator", self.factory)
        substitute.start()
        self.addCleanup(substitute.stop)
        self.env = EcoBuildingEnv(model, weather, output, Episode((8, 7)))
        self.addCleanup(self.env.close)

    def assert_observation(self, vector):
        self.assertEqual(vector.shape, (20,))
        self.assertEqual(vector.dtype, np.float32)
        self.assertTrue(np.isfinite(vector).all())
        self.assertTrue(self.env.observation_space.contains(vector))

    def test_manifest_scenario_runs_complete_default_mdp(self):
        def inject_hot_zone(worker):
            exchange = worker.exchange
            read = exchange.get_variable_value

            def hot_temperature(state, handle):
                if handle == exchange.handles.get((state, ("Zone Mean Air Temperature", "OFFICE"))):
                    return 38.0
                return read(state, handle)

            exchange.get_variable_value = hot_temperature

        self.factory.setup = inject_hot_zone
        scenario = EpisodePlan.load().scenarios("validation")[0]
        expected = generate(scenario.occupancy_seed, days=7, start_weekday=scenario.date.weekday())
        self.assertIsInstance(self.env.action_space, MultiDiscrete)
        np.testing.assert_array_equal(self.env.action_space.nvec, [3, 3, 3])

        vector, initial = self.env.reset(options=scenario.reset_options())
        worker = self.factory.workers[-1]
        self.assertEqual(worker.episode_config, scenario.episode)
        self.assertEqual(list(worker.profile), expected)
        self.assert_observation(vector)
        np.testing.assert_array_equal(vector[15:], np.zeros(5))
        self.assertNotIn("reward", initial)
        previous_end = datetime.fromisoformat(initial["end"])
        observations = 1
        for index, people in enumerate(expected):
            action = (2, 1, 0) if index % 2 == 0 else (0, 2, 2)
            vector, reward, terminated, truncated, info = self.env.step(action)
            self.assert_observation(vector)
            observations += 1
            self.assertEqual(info["decision_id"], index)
            self.assertEqual(datetime.fromisoformat(info["start"]), previous_end)
            previous_end += timedelta(seconds=900)
            self.assertEqual(datetime.fromisoformat(info["end"]), previous_end)
            self.assertEqual(info["requested"], action)
            self.assertEqual(info["applied"], action)
            np.testing.assert_array_equal(vector[15:18], action)
            breakdown = info["reward"]
            self.assertEqual(breakdown["constraints"]["occupants"], people)
            self.assertEqual(info["physical"]["occupancy"]["people"], people)
            self.assertEqual(vector[8], people)
            self.assertEqual(reward, breakdown["total"])
            self.assertEqual(reward, -sum(breakdown["weighted"].values()))
            self.assertEqual(breakdown["components"]["action_change"], 0 if index == 0 else 5/6)
            self.assertGreater(breakdown["weighted"]["temperature"], 0)
            self.assertFalse(terminated)
            self.assertEqual(truncated, index == 671)

        self.assertEqual(observations, 673)
        self.assertFalse(worker.worker_alive())
        self.assertEqual(worker.sim_results["exit_code"], 0)
        with self.assertRaises(ResetNeeded):
            self.env.step((0, 0, 0))

    def test_future_occupancy_changes_do_not_change_prefix(self):
        def run_prefix(future):
            initial, initial_info = self.env.reset(seed=42, options={
                "occupancy_mode": "explicit", "occupancy_profile": [1] + [future] * 95})
            first = self.env.step((2, 1, 0))
            diverging = self.env.step((0, 1, 2))
            return initial, initial_info, first, diverging

        vacant = run_prefix(0)
        occupied = run_prefix(2)
        np.testing.assert_array_equal(vacant[0], occupied[0])
        self.assertEqual(vacant[1], occupied[1])
        np.testing.assert_array_equal(vacant[2][0], occupied[2][0])
        self.assertEqual(vacant[2][1:], occupied[2][1:])
        self.assertEqual((vacant[3][0][8], occupied[3][0][8]), (0, 2))
        np.testing.assert_array_equal(occupied[0][15:], np.zeros(5))
        self.assertEqual(occupied[2][4]["reward"]["components"]["action_change"], 0)

    def test_gymnasium_checker_on_default_mdp(self):
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            gym_check(self.env)
        for warning in recorded:
            print("MDP Gymnasium warning:", warning.message)
        self.assertTrue(all(any(text in str(warning.message) for text in (
            "minimum value is -infinity", "maximum value is infinity", "not having a spec",
        )) for warning in recorded), [str(warning.message) for warning in recorded])

    def test_sb3_checker_on_default_mdp(self):
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            sb3_check(self.env, warn=True)
        self.assertFalse(recorded, [str(warning.message) for warning in recorded])
