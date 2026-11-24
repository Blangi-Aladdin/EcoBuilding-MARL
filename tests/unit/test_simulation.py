import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock

from ecobuilding.simulation import Scenario, SimulationRunner


class SimulationTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.api = MagicMock()
        self.api.state_manager.new_state.return_value = 123
        self.runner = SimulationRunner(self.api, cooling_setpoint_c=25)
        self.model = self.root / "office.epJSON"
        self.weather = self.root / "weather.epw"
        self.model.write_text(json.dumps({
            "Timestep": {"steps": {"number_of_timesteps_per_hour": 4}},
            "RunPeriod": {"period": {}}, "Output:Variable": {},
        }))
        self.weather.touch()
        self.scenario = Scenario("case", (8, 1, 8, 8), (8, 8), (None,) * 96)

    def run_case(self):
        return self.runner.run(self.model, self.weather, self.root / "output", self.scenario)

    def test_missing_input_never_allocates_state(self):
        self.weather.unlink()
        with self.assertRaises(FileNotFoundError):
            self.run_case()
        self.api.state_manager.new_state.assert_not_called()

    def test_invalid_output_never_allocates_state(self):
        (self.root / "output").touch()
        with self.assertRaises(FileExistsError):
            self.run_case()
        self.api.state_manager.new_state.assert_not_called()

    def test_invalid_action_never_allocates_state(self):
        self.scenario = Scenario("case", (8, 1, 8, 8), (8, 8), ((0, 0, 3),) * 96)
        with self.assertRaises(ValueError):
            self.run_case()
        self.api.state_manager.new_state.assert_not_called()

    def test_incomplete_and_failed_runs_clean_state(self):
        for status in (0, 1):
            with self.subTest(status=status):
                self.api.runtime.run_energyplus.return_value = status
                with self.assertRaisesRegex(RuntimeError, f"exit {status}, 0/96 steps"):
                    self.runner.run(self.model, self.weather, self.root / f"output-{status}", self.scenario)
        self.assertEqual(self.api.runtime.clear_callbacks.call_count, 2)
        self.assertEqual(self.api.state_manager.delete_state.call_count, 2)

    def test_interruption_cleans_state(self):
        self.api.runtime.run_energyplus.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.run_case()
        self.api.runtime.clear_callbacks.assert_called_once_with()
        self.api.state_manager.delete_state.assert_called_once_with(123)

    def test_callback_exception_stops_and_cleans_state(self):
        callback = self.api.runtime.callback_begin_zone_timestep_before_set_current_weather

        def run(state, arguments):
            self.api.exchange.month.side_effect = ValueError("unavailable clock")
            callback.call_args.args[1](state)
            return 0

        self.api.runtime.run_energyplus.side_effect = run
        with self.assertRaisesRegex(RuntimeError, "callback exogenous failed") as error:
            self.run_case()
        self.assertIsInstance(error.exception.__cause__, ValueError)
        self.api.runtime.stop_simulation.assert_called_once_with(123)
        self.api.runtime.clear_callbacks.assert_called_once_with()
        self.api.state_manager.delete_state.assert_called_once_with(123)
        self.assertIsNone(self.runner.hvac.get_last_action())
        self.assertIsNone(self.runner.observer.get_observation())
