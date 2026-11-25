"""Opt-in physical qualification of the official Sinergym adapter."""

from datetime import datetime
from importlib.metadata import version
from math import isclose
import os
from pathlib import Path
import platform
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / 'models/office_1zone.epJSON'
WEATHER = ROOT / 'models/weather/FRA_BF_Belfort.Fontaine.072960_TMYx.2011-2025.epw'
ENABLE = 'ECOBUILDING_RUN_SINERGYM_INTEGRATION'
OUTPUT = 'ECOBUILDING_SINERGYM_INTEGRATION_OUTPUT'

WINTER = (1, 27)
SUMMER = (8, 7)
SEED = 42
SETPOINT = 25
OFF = (0, 0, 0)
FIRST_ACTIONS = ((2, 0, 0), (1, 0, 0), (0, 0, 1), (0, 0, 2), (2, 0, 2), OFF)
FIRST_ENERGY = ((1800000, 0), (900000, 0), (0, 6000), (0, 18000), (1800000, 18000), (0, 0))
WINTER_B = ((2, 1, 0),) * 96
SUMMER_D = tuple(action for action in (
    OFF, (0, 1, 0), (0, 2, 0), (0, 0, 1), (0, 1, 1), (0, 2, 1),
    (0, 2, 2), (0, 1, 2), (0, 0, 2), (0, 2, 2), (0, 1, 1), OFF,
) for _ in range(8))
OCCUPANCY_G = tuple(action for size, action in (
    (16, OFF), (8, (2, 0, 0)), (8, (1, 0, 0)), (8, (1, 0, 1)),
    (8, (0, 0, 2)), (4, OFF), (12, (1, 0, 1)), (8, (0, 0, 2)),
    (8, (1, 0, 0)), (8, (0, 0, 1)), (8, OFF),
) for _ in range(size))
INTERRUPTION_CYCLE = (OFF, (2, 0, 0), (1, 0, 1), (0, 0, 2))
EQUIVALENCE_ACTIONS = ((2, 0, 0),) * 32 + ((2, 1, 0),) * 64
DYNAMIC_OPTIONS = {'occupancy_mode': 'dynamic', 'occupancy_seed': SEED}


@unittest.skipUnless(os.environ.get(ENABLE) == '1', f'Set {ENABLE}=1 for physical simulation')
class SinergymEnergyPlusIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A requested physical run fails on missing prerequisites, including incompatible versions.
        from ecobuilding.sinergym_adapter import EcoBuildingEnv, Episode
        from pyenergyplus.api import EnergyPlusAPI

        cls.env_class, cls.episode_class, cls.energyplus_api = EcoBuildingEnv, Episode, EnergyPlusAPI
        for path in (MODEL, WEATHER):
            if not path.is_file() or not os.access(path, os.R_OK):
                raise FileNotFoundError(f'Physical integration fixture unavailable: {path}')
        executable = shutil.which('energyplus')
        if executable is None:
            raise RuntimeError('EnergyPlus executable is missing from PATH')
        engine = subprocess.check_output([executable, '--version'], text=True, timeout=10)
        if '25.1.0-1c11a3d85f' not in engine or EnergyPlusAPI().api_version() != '0.2':
            raise RuntimeError(f'Unqualified EnergyPlus executable or API: {engine.strip()}')
        if platform.python_version() != '3.12.3':
            raise RuntimeError('Python 3.12.3 is required for this qualification')
        for package, required in {'sinergym': '3.12.2', 'gymnasium': '1.2.3', 'numpy': '2.5.5'}.items():
            if version(package) != required:
                raise RuntimeError(f'{package} {required} is required for this qualification')
        output = os.environ.get(OUTPUT)
        if output and not Path(output).is_dir():
            raise NotADirectoryError(output)
        temporary = TemporaryDirectory(prefix='sinergym-integration-', dir=output)
        cls.addClassCleanup(temporary.cleanup)
        cls.output = Path(temporary.name)

    def create_env(self, first=WINTER):
        env = self.env_class(MODEL, WEATHER, self.output, self.episode_class(first),
                             cooling_setpoint_c=SETPOINT, reward_mode="legacy_zero")
        self.addCleanup(env.close)
        return env

    def reset(self, env, options=None):
        vector, info = env.reset(seed=SEED, options=options)
        self.assertTrue(env.observation_space.contains(vector))
        self.assertEqual(info['kind'], 'initial')
        self.assertFalse(info['controlled'])
        self.assertFalse(info['last'])
        for key in ('decision_id', 'requested', 'applied'):
            self.assertIsNone(info[key])
        self.assertEqual(env._worker.completed, 0)
        start, end = map(datetime.fromisoformat, (info['start'], info['end']))
        self.assertEqual((end.month, end.day, end.hour, end.minute), (*env.episode.first, 0, 0))
        self.assertEqual((end - start).total_seconds(), 900)
        self.assertFalse(info['physical']['actions']['hvac_overrides_active'])
        self.assertFalse(info['physical']['actions']['occupancy_override_active'])
        return vector, info

    def run_actions(self, env, actions, initial):
        previous = initial
        trajectory = []
        for index, action in enumerate(actions):
            with self.subTest(decision=index):
                vector, reward, terminated, truncated, info = env.step(action)
                self.assertTrue(env.observation_space.contains(vector))
                self.assertEqual((reward, terminated, truncated), (0.0, False, index == 95))
                self.assertEqual(info['decision_id'], index)
                self.assertTrue(info['controlled'])
                self.assertEqual(info['start'], previous['end'])
                self.assertEqual((info['requested'], info['applied']), (action, action))
                start, end = map(datetime.fromisoformat, (info['start'], info['end']))
                self.assertEqual((end - start).total_seconds(), 900)
                physical = info['physical']
                self.assertEqual(physical['actions']['active_action'], action)
                energy = physical['energy']
                self.assertTrue(isclose(energy['total_j'], sum(energy[k] for k in
                                ('heating_j', 'cooling_dx_j', 'ventilation_j')),
                                rel_tol=1e-9, abs_tol=1e-6))
                trajectory.append((vector.tolist(), info))
                previous = info
        if len(actions) == 96:
            from gymnasium.error import ResetNeeded
            self.assertFalse(env._worker.worker_alive())
            self.assertEqual(env._worker.sim_results['exit_code'], 0)
            with self.assertRaises(ResetNeeded):
                env.step(OFF)
        return trajectory

    def close_and_check(self, env):
        worker = env._worker
        thread = worker.energyplus_thread
        env.close()
        self.assertFalse(thread.is_alive())
        self.assertIsNone(worker.energyplus_state)
        self.assertIsNone(env._worker)
        env.close()

    def test_I01_initialization_and_close(self):
        env = self.create_env()
        self.reset(env)
        worker = env._worker
        self.close_and_check(env)
        self.assertEqual(worker.completed, 0)

    def test_I02_first_hvac_transitions(self):
        env = self.create_env()
        _, initial = self.reset(env)
        trajectory = self.run_actions(env, FIRST_ACTIONS, initial)
        self.assertEqual(len(trajectory), len(FIRST_ACTIONS))
        for (_, info), (heat, vent), action in zip(trajectory, FIRST_ENERGY, FIRST_ACTIONS, strict=True):
            physical = info['physical']
            for key, expected in (('heating_j', heat), ('ventilation_j', vent), ('cooling_dx_j', 0)):
                self.assertTrue(isclose(physical['energy'][key], expected, rel_tol=1e-9, abs_tol=1e-6))
            self.assertTrue(isclose(physical['equipment']['vent_m3_h'], (0, 40, 120)[action[2]],
                                    rel_tol=1e-9, abs_tol=1e-6))
        self.close_and_check(env)

    def test_I03_full_winter_day(self):
        env = self.create_env()
        _, initial = self.reset(env)
        records = [info['physical'] for _, info in self.run_actions(env, WINTER_B, initial)]
        self.assertEqual(len(records), 96)
        self.assertTrue(all(obs['energy']['heating_j'] > 0 for obs in records))
        active = [obs for obs in records if obs['equipment']['dx_active']]
        self.assertTrue(active)
        self.assertTrue(any(not obs['equipment']['dx_active'] and obs['energy']['cooling_dx_j'] == 0
                            for obs in records))
        self.assertTrue(all(obs['equipment']['dx_speed_when_cooling'] == [1] for obs in active))
        self.assertGreater(sum(obs['energy']['cooling_dx_j'] for obs in active), 0)
        self.close_and_check(env)

    def test_I04_full_summer_day(self):
        env = self.create_env(SUMMER)
        _, initial = self.reset(env)
        records = [info['physical'] for _, info in self.run_actions(env, SUMMER_D, initial)]
        self.assertEqual(len(records), 96)
        self.assertTrue(all(obs['energy']['heating_j'] == 0 for obs in records))
        self.assertEqual({stage for obs in records for stage in obs['equipment']['dx_speed_when_cooling']}, {1, 2})
        self.assertTrue(any(obs['energy']['cooling_dx_j'] > 0 and obs['energy']['ventilation_j'] > 0
                            for obs in records))
        for action, obs in zip(SUMMER_D, records, strict=True):
            self.assertTrue(isclose(obs['equipment']['vent_m3_h'], (0, 40, 120)[action[2]],
                                    rel_tol=1e-9, abs_tol=1e-6))

    def test_I05_dynamic_occupancy(self):
        from ecobuilding.occupancy_profiles import generate
        from ecobuilding.sinergym_adapter import STATE_NAMES

        occupant_index = STATE_NAMES.index("occupant_count")

        env = self.create_env()
        initial_vector, initial = self.reset(env, DYNAMIC_OPTIONS)
        expected = generate(SEED, days=1, start_weekday=env.episode.first_weekday)
        previous_vector, previous_info = initial_vector, initial
        self.assertEqual(initial_vector[occupant_index], initial['physical']['occupancy']['people'])
        for index, (vector, info) in enumerate(self.run_actions(env, OCCUPANCY_G, initial)):
            self.assertEqual(previous_info['end'], info['start'])
            self.assertEqual(previous_vector[occupant_index], previous_info['physical']['occupancy']['people'])
            self.assertEqual(vector[occupant_index], expected[index])
            self.assertEqual(info['physical']['occupancy']['people'], expected[index])
            self.assertEqual(set(info), {'kind', 'decision_id', 'start', 'end', 'requested',
                                        'applied', 'controlled', 'last', 'physical'})
            self.assertEqual(set(info['physical']['occupancy']), {'people', 'presence'})
            previous_vector, previous_info = vector, info

    def test_I06_reproducibility_and_reset(self):
        from ecobuilding.observations import ObservationManager

        env = self.create_env()
        initialize = ObservationManager.initialize
        with patch.object(ObservationManager, 'initialize', autospec=True, side_effect=initialize) as bind:
            _, first = self.reset(env, DYNAMIC_OPTIONS)
            first_info = self.run_actions(env, OCCUPANCY_G, first)
            old_worker = env._worker
            old_thread = old_worker.energyplus_thread
            old_state = old_worker.energyplus_state
            old_episode_id = env.episode_id
            _, second = self.reset(env, DYNAMIC_OPTIONS)
            self.assertFalse(old_thread.is_alive())
            self.assertIsNone(old_worker.energyplus_state)
            self.assertEqual(env.episode_id, old_episode_id + 1)
            self.assertIsNot(env._worker, old_worker)
            self.assertEqual(bind.call_count, 2)
            self.assertEqual(bind.call_args_list[0].args, (old_worker.observer, old_state))
            self.assertEqual(bind.call_args_list[1].args, (env._worker.observer, env._worker.energyplus_state))
            self.assertEqual(first, second)
            self.assertEqual(first_info, self.run_actions(env, OCCUPANCY_G, second))

    def test_I07_interruption_and_recovery(self):
        from gymnasium.error import ResetNeeded

        env = self.create_env()
        _, initial = self.reset(env)
        first = self.run_actions(env, INTERRUPTION_CYCLE[:1], initial)
        worker = env._worker
        self.close_and_check(env)
        self.assertEqual(worker.completed, 1)
        with self.assertRaises(ResetNeeded):
            env.step(OFF)
        _, new_initial = self.reset(env)
        self.assertEqual(new_initial, initial)
        replay = self.run_actions(env, INTERRUPTION_CYCLE, new_initial)
        self.assertEqual(len(replay), 4)
        self.assertEqual(first, replay[:1])
        self.close_and_check(env)

    def test_I08_targeted_physical_equivalence(self):
        from ecobuilding.simulation import Scenario, SimulationRunner

        env = self.create_env()
        episode = env.episode
        dates = (episode.history_start.month, episode.history_start.day, *episode.first)
        scenario = Scenario('winter-cooling-1', dates, episode.first, EQUIVALENCE_ACTIONS,
                            start_day=episode.start_day)
        with TemporaryDirectory(dir=self.output) as directory:
            direct = SimulationRunner(self.energyplus_api(), cooling_setpoint_c=SETPOINT).run(
                MODEL, WEATHER, Path(directory) / 'direct', scenario)
            _, initial = self.reset(env)
            trajectory = self.run_actions(env, EQUIVALENCE_ACTIONS, initial)
            # The 37.2.6 winter-cooling-1 comparison achieved exact equality.
            self.assertEqual(direct, [info['physical'] for _, info in trajectory])
        self.close_and_check(env)
