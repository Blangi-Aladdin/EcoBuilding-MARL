"""Unit tests for the seasonal rule-based HVAC controller."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from ecobuilding.controllers import RBCConfig, SeasonalRBC
from ecobuilding.sinergym_adapter.state import STATE_NAMES


def observation(temperature=21.0, co2=700.0, occupants=1):
    values = np.zeros(20, dtype=np.float32)
    values[0], values[2], values[8] = temperature, co2, occupants
    return values


def info(month=1):
    return {"physical": {"time": {"month": month}}}


class RBCConfigTests(unittest.TestCase):
    def test_default_configuration(self):
        config = RBCConfig()
        self.assertEqual(config.occupied_low_co2_ppm, 800)
        self.assertEqual(config.occupied_high_co2_ppm, 1000)

    def test_load_and_invalid_keys(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "rbc.json"
            path.write_text(json.dumps({"heating_hysteresis_c": 0.7}))
            self.assertEqual(RBCConfig.load(path).heating_hysteresis_c, 0.7)
            path.write_text(json.dumps({"unknown": 1}))
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                RBCConfig.load(path)

    def test_invalid_numeric_values(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            RBCConfig(heating_hysteresis_c=float("inf"))
        with self.assertRaisesRegex(ValueError, "exit_ppm"):
            RBCConfig(occupied_low_co2_exit_ppm=900, occupied_low_co2_ppm=800)


class SeasonalRBCTests(unittest.TestCase):
    def setUp(self):
        self.controller = SeasonalRBC()

    def test_initial_action_is_all_off(self):
        self.assertEqual(self.controller.reset(), (0, 0, 0))
        self.assertEqual(self.controller.act(observation(21, 700, 1), info(1)), (0, 0, 0))

    def test_winter_heating_levels_and_hysteresis(self):
        self.assertEqual(self.controller.act(observation(18.0, 700, 1), info(1)), (2, 0, 0))
        self.assertEqual(self.controller.act(observation(19.5, 700, 1), info(1)), (1, 0, 0))
        self.assertEqual(self.controller.act(observation(20.0, 700, 1), info(1)), (1, 0, 0))
        self.assertEqual(self.controller.act(observation(20.6, 700, 1), info(1)), (0, 0, 0))

    def test_summer_cooling_levels_and_hysteresis(self):
        self.assertEqual(self.controller.act(observation(27.6, 700, 1), info(7)), (0, 2, 0))
        self.assertEqual(self.controller.act(observation(26.6, 700, 1), info(7)), (0, 1, 0))
        self.assertEqual(self.controller.act(observation(26.0, 700, 1), info(7)), (0, 1, 0))
        self.assertEqual(self.controller.act(observation(25.4, 700, 1), info(7)), (0, 0, 0))

    def test_co2_ventilation_hysteresis(self):
        self.assertEqual(self.controller.act(observation(21, 850, 1), info(1)), (0, 0, 1))
        self.assertEqual(self.controller.act(observation(21, 950, 1), info(1)), (0, 0, 1))
        self.assertEqual(self.controller.act(observation(21, 1050, 1), info(1)), (0, 0, 2))
        self.assertEqual(self.controller.act(observation(21, 950, 1), info(1)), (0, 0, 2))
        self.assertEqual(self.controller.act(observation(21, 850, 1), info(1)), (0, 0, 1))
        self.assertEqual(self.controller.act(observation(21, 650, 1), info(1)), (0, 0, 0))

    def test_unoccupied_temperature_and_no_ventilation(self):
        controller = SeasonalRBC()
        self.assertEqual(controller.act(observation(14, 1500, 0), info(1)), (1, 0, 0))
        self.assertEqual(controller.act(observation(12, 1500, 0), info(1)), (2, 0, 0))
        self.assertEqual(controller.act(observation(29, 1500, 0), info(7)), (0, 1, 0))
        self.assertEqual(controller.act(observation(31, 1500, 0), info(7)), (0, 2, 0))

    def test_dict_observation_and_invalid_inputs(self):
        values = dict(zip(STATE_NAMES, np.zeros(20, dtype=np.float32), strict=True))
        values.update(indoor_temperature=21.0, indoor_co2=700.0, occupant_count=1.0)
        values = dict(values)
        self.assertEqual(SeasonalRBC().act(values, info(1)), (0, 0, 0))
        with self.assertRaisesRegex(ValueError, "shape"):
            SeasonalRBC().act(np.zeros((20, 1), dtype=np.float32), info(1))
        with self.assertRaisesRegex(ValueError, "month"):
            SeasonalRBC().act(observation(), {})


if __name__ == "__main__":
    unittest.main()
