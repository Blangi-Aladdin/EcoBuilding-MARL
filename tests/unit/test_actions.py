import itertools
import unittest

import gymnasium as gym
import numpy as np

from ecobuilding.actions import ActuationError, HVACController


class Exchange:
    def __init__(self):
        self.ready = True
        self.missing = None
        self.lookups = []
        self.calls = []
        self.fail_at = None

    def api_data_fully_ready(self, state):
        return self.ready

    def get_actuator_handle(self, state, *key):
        self.lookups.append((state, key))
        return -1 if key[-1] == self.missing else state * 10 + len(self.lookups)

    load = 0.0

    def get_variable_handle(self, state, *key):
        return 99

    def get_variable_value(self, state, handle):
        return self.load

    def api_error_flag(self, state):
        return self.fail_at is not None and len(self.calls) >= self.fail_at

    def set_actuator_value(self, state, handle, value):
        self.calls.append((state, handle, value))

    def reset_actuator(self, state, handle):
        self.calls.append((state, handle, "reset"))


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.api = Exchange()
        self.controller = HVACController(self.api, cooling_setpoint_c=25)
        self.controller.initialize(1)

    def test_valid_inputs(self):
        for action in ([0,0,0], [2,0,1], [0,2,2], [1,1,1], [2,2,2], (1,0,2),
                       np.array([2,1,0], dtype=np.int64), np.array([1,0,2], dtype=np.int32)):
            with self.subTest(action=action):
                self.assertEqual(self.controller.apply(action), tuple(action))
                self.assertEqual(self.controller.get_last_action(), tuple(action))

    def test_invalid_inputs_leave_state_alone(self):
        valid = self.controller.apply((1,2,0))
        calls = self.api.calls.copy()
        for bad in ([-1,0,1], [0,3,1], [0,1], [0,1,2,0], [0,1.0,2], [True,0,1],
                    ["1",0,2], [None,0,1], np.array([np.nan,0,0]), np.array([0,np.inf,0]),
                    np.ones((1,3), dtype=int), np.ones((3,1), dtype=int), 2, [], None,
                    np.array([True,False,True])):
            with self.subTest(action=bad):
                with self.assertRaises(ValueError):
                    self.controller.apply(bad)
                self.assertEqual(self.controller.get_last_action(), valid)
                self.assertEqual(self.api.calls, calls)

    def test_space_and_all_27_combinations(self):
        space = gym.spaces.MultiDiscrete([3,3,3], seed=42)
        self.assertEqual(space.shape, (3,))
        np.testing.assert_array_equal(space.start, [0,0,0])
        np.testing.assert_array_equal(space.nvec-1, [2,2,2])
        combos = list(itertools.product(range(3), repeat=3))
        self.assertEqual(len(set(combos)), 27)
        for action in [np.asarray(a, dtype=space.dtype) for a in combos] + [space.sample() for _ in range(64)]:
            self.assertTrue(space.contains(action))
            self.assertEqual(self.controller.apply(action), tuple(action))
            self.api.load = -1000
            self.controller.synchronize_cooling()
            self.assertEqual(self.controller.cooling_speed_override, action[1])
            self.api.load = 1000
            self.controller.synchronize_cooling()
            self.assertEqual(self.controller.cooling_speed_override, 0)
        self.assertFalse(space.contains([0,3,1]))

    def test_physical_mapping(self):
        for level, flow in enumerate((0,40,120)):
            self.controller.apply((level,level,level))
            operations = self.controller.get_last_writes()
            self.assertEqual(operations[0][-1], level/2)
            self.assertAlmostEqual(operations[-1][-1], flow/3600)
            if level:
                self.assertEqual([op[-1] for op in operations[1:3]], [25,1])
            else:
                self.assertEqual(operations[1][-1], 0)
                self.assertEqual(operations[2][0], "reset_actuator")
                self.assertEqual(len(operations), 4)

    def test_off_release_and_detach(self):
        self.controller.apply([2,2,2])
        self.controller.all_off()
        self.assertEqual(self.controller.get_last_action(), (0,0,0))
        self.assertNotIn("SUMMER COOLING SETPOINT", [op[1] for op in self.controller.get_last_writes()])
        self.controller.release()
        self.assertEqual(self.controller.get_last_action(), (0,0,0))
        self.assertEqual(len(self.controller.get_last_writes()), 5)
        self.assertTrue(all(op[0] == "reset_actuator" for op in self.controller.get_last_writes()))
        self.controller.detach()
        self.assertIsNone(self.controller.get_last_action())
        self.controller.initialize(2)
        self.controller.apply((2,2,2))
        self.assertTrue(all(call[0] == 2 and call[1] >= 20 for call in self.api.calls[-4:]))
        self.assertEqual(len(self.api.lookups), 10)

    def test_partial_failure_is_reported_and_blocks_further_writes(self):
        old_action = self.controller.apply([0,0,0])
        self.api.fail_at = len(self.api.calls) + 3
        with self.assertRaisesRegex(ActuationError, "confirmed prior writes"):
            self.controller.apply([2,2,2])
        self.assertEqual(len(self.controller.get_last_writes()), 2)
        self.assertEqual(self.controller.get_last_action(), old_action)
        with self.assertRaises(RuntimeError):
            self.controller.all_off()
        self.assertEqual(len(self.api.calls), self.api.fail_at)

    def test_initialization_failures(self):
        self.controller.detach()
        self.api.ready = False
        with self.assertRaisesRegex(RuntimeError, "not ready"):
            self.controller.initialize(2)
        self.api.ready = True
        for key in ("BALANCED OUTDOOR AIR", "OFFICE DX UNIT"):
            self.api.missing = key
            with self.assertRaisesRegex(RuntimeError, key):
                self.controller.initialize(2)
        self.assertIsNone(self.controller.get_last_action())

    def test_invalid_cooling_setpoints(self):
        for setpoint in (20,21,float("nan"),float("inf"),True,"25"):
            with self.assertRaises(ValueError):
                HVACController(self.api, cooling_setpoint_c=setpoint)


if __name__ == "__main__":
    unittest.main(verbosity=2)
