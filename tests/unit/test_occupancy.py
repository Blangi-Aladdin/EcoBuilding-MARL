import unittest

from ecobuilding.occupancy import OccupancyManager
from ecobuilding.occupancy_profiles import DETERMINISTIC, STEPS, generate
from test_actions import Exchange


class OccupancyTests(unittest.TestCase):
    def test_validated_counts_and_release(self):
        api = Exchange()
        manager = OccupancyManager(api)
        manager.initialize(1)
        profile = (0, 1, 2)
        for i, fraction in enumerate((0, 0.5, 1)):
            self.assertEqual(manager.apply_profile(profile, i), fraction)
        for bad in (-1, 3, 1.5, True):
            with self.assertRaises(ValueError):
                manager.apply(bad)
        with self.assertRaises(ValueError):
            manager.apply_profile(profile, 3)
        manager.release()
        self.assertEqual([call[-1] for call in api.calls], [0, 0.5, 1, "reset"])
        manager.detach()
        with self.assertRaises(RuntimeError):
            manager.observe()
        manager.initialize(2)
        manager.apply(1)
        self.assertEqual(api.calls[-1][0], 2)

    def test_profiles_are_reproducible(self):
        first = generate(42)
        self.assertEqual(first, generate(42))
        self.assertNotEqual(first, generate(43))
        self.assertEqual(len(first), 7 * STEPS)
        self.assertEqual(set(first), {0, 1, 2})
        self.assertTrue(all(len(profile) == STEPS for profile in DETERMINISTIC.values()))
