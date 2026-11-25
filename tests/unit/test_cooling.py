import unittest


import numpy as np

from ecobuilding.actions import ActuationError, HVACController
from test_actions import Exchange


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        self.api = Exchange()
        self.controller = HVACController(self.api, cooling_setpoint_c=25)
        self.controller.initialize(1)

    def sync(self, load):
        self.api.load = load
        self.assertEqual(self.controller.synchronize_cooling(), load)
        return self.controller.cooling_speed_override

    def test_retains_level_through_physical_transitions(self):
        for level in (1,2):
            self.controller.apply(np.array([2,level,1], dtype=np.int64))
            for load, speed in ((800,0),(0,0),(-300,level),(0,0),(-500,level),(800,0),
                                (-200,level)):
                self.assertEqual(self.sync(load), speed)
                self.assertEqual(self.controller.get_last_action(), (2,level,1))
        self.controller.all_off()
        self.assertEqual(self.sync(-1000), 0)

    def test_unchanged_predictor_context_avoids_duplicate_writes(self):
        self.controller.apply((0,2,0))
        self.assertEqual(self.sync(-1000), 2)
        calls = self.api.calls.copy()
        self.assertEqual(self.sync(-1500), 2)
        self.assertEqual(self.api.calls, calls)

    def test_invalid_vector_preserves_pending_command(self):
        self.controller.apply((0,1,0))
        before = self.api.calls.copy()
        with self.assertRaises(ValueError):
            self.controller.apply((2,2,False))
        self.assertEqual(self.api.calls, before)
        self.assertEqual(self.sync(-500), 1)

    def test_release_and_detach_clear_speed_request(self):
        self.controller.apply((2,2,2))
        self.assertEqual(self.sync(-500), 2)
        self.controller.release()
        self.assertEqual(self.sync(-200), 0)
        self.assertEqual(self.controller.get_last_action(), (2,2,2))
        self.controller.detach()
        self.controller.initialize(2)
        self.assertIsNone(self.controller.get_last_action())
        self.assertEqual(self.sync(-500), 0)

    def test_deferred_write_failure_blocks_controller(self):
        self.controller.apply((0,2,0))
        self.api.fail_at = len(self.api.calls)+1
        with self.assertRaises(ActuationError):
            self.sync(-300)
        self.assertEqual(self.controller.get_last_action(), (0,2,0))
        with self.assertRaises(RuntimeError):
            self.controller.all_off()

    def test_missing_predictor_handle_is_reported(self):
        self.controller.detach()
        self.api.get_variable_handle = lambda *args: -1
        with self.assertRaisesRegex(RuntimeError, "predictor variable"):
            self.controller.initialize(2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
