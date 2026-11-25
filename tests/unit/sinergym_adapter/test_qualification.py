"""Qualification with the real adapter, native Sinergym worker and simulated API."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from itertools import product
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch
import warnings

import gymnasium as gym
from gymnasium.utils.env_checker import check_env as gym_check
import numpy as np
from stable_baselines3.common.env_checker import check_env as sb3_check
from sinergym.simulators.eplus import EnergyPlus

from ecobuilding.sinergym_adapter import DEFAULT_FIELDS, EcoBuildingEnv, Episode, Field
from ecobuilding.sinergym_adapter.model import check_model_changes, prepare_episode_inputs
from ecobuilding.sinergym_adapter.simulator import EcoBuildingSimulator
from ecobuilding.sinergym_adapter.transport import EpisodeError, Result
from .doubles import WorkerFactory, ZONE

ROOT = Path(__file__).resolve().parents[3]
MODEL = ROOT / "models/office_1zone.epJSON"
WEATHER = ROOT / "models/weather/FRA_BF_Belfort.Fontaine.072960_TMYx.2011-2025.epw"
OFF = (0, 0, 0)


class Qualification(unittest.TestCase):
    def setUp(self):
        # The inner instance is replaced with an API double before inherited start().
        # This backstop prevents a real call even if the injection is accidentally bypassed.
        guard = patch("pyenergyplus.runtime.Runtime.run_energyplus", side_effect=AssertionError("Physical run forbidden"))
        self.addCleanup(guard.stop)
        guard.start()
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name)

    def create(self, episode=None, factory=None, **kwargs):
        factory = factory or WorkerFactory()
        override = patch("ecobuilding.sinergym_adapter.environment.EcoBuildingSimulator", factory)
        override.start()
        self.addCleanup(override.stop)
        kwargs.setdefault("fields", DEFAULT_FIELDS)
        kwargs.setdefault("reward_mode", "legacy_zero")
        env = EcoBuildingEnv(MODEL, WEATHER, self.output, episode or Episode((8, 7)), **kwargs)
        self.addCleanup(env.close)
        return env, factory

    def replay(self, env, *, options=None, plan=(OFF,)):
        initial, meta = env.reset(seed=42, options=options)
        self.assertTrue(env.observation_space.contains(initial))
        self.assertFalse(meta["controlled"])
        self.assertIsNone(meta["decision_id"])
        self.assertIsNone(meta["applied"])
        self.assertIsNone(meta["requested"])
        episode_id, end = env.episode_id, meta["end"]
        from datetime import datetime
        initial_energy = meta["physical"]["energy"]["total_j"]
        total = 0
        for i in range(env.episode.steps):
            action = plan[i % len(plan)]
            obs, reward, terminated, truncated, info = env.step(np.array(action, dtype=np.int64))
            self.assertTrue(env.observation_space.contains(obs))
            self.assertEqual((reward, terminated, truncated), (0.0, False, i == env.episode.steps - 1))
            self.assertEqual(env.episode_id, episode_id)
            self.assertEqual(info["decision_id"], i)
            self.assertEqual((info["requested"], info["applied"]), (action, action))
            self.assertEqual(info["physical"]["actions"]["active_action"], action)
            self.assertEqual(info["start"], end)
            self.assertEqual(datetime.fromisoformat(info["end"]) - datetime.fromisoformat(end), timedelta(seconds=900))
            self.assertEqual(info["physical"]["time"]["hvac_seconds"], [300, 600])
            self.assertEqual(info["physical"]["energy"]["total_j"], 92700)
            self.assertEqual(info["physical"]["energy"]["heating_j"], 72000)
            self.assertEqual(info["physical"]["energy"]["cooling_dx_j"], 18000)
            self.assertEqual(info["physical"]["energy"]["ventilation_j"], 2700)
            total += info["physical"]["energy"]["total_j"]
            end = info["end"]
        self.assertEqual(initial_energy, 92700)
        self.assertEqual(total, env.episode.steps * 92700)
        return end

    def test_T01_configuration_and_calendar(self):
        env, _ = self.create(fields=(Field(("occupancy", "people"), "people"),))
        self.assertIsInstance(env, gym.Env)
        self.assertEqual(env.action_space.nvec.tolist(), [3, 3, 3])
        self.assertEqual(env.observation_space.shape, (1,))
        self.assertEqual(env.observation_space.dtype, np.float32)
        self.assertEqual(env.episode.history_days, 7)
        for first, days, history in (((1, 1), 1, 7), ((12, 31), 2, 7), ((2, 29), 1, 7),
                                     ((3, 1), 1, 7), ((8, 7), 1, 0), ((8, 7), 0, 7)):
            with self.subTest(first=first, days=days, history=history), self.assertRaises(ValueError):
                Episode(first, days, history)
        for timeout in (-1, 0, np.inf, np.nan):
            with self.assertRaises(ValueError):
                EcoBuildingEnv(MODEL, WEATHER, self.output, env.episode, startup_timeout=timeout)
        for options in ({"occupancy_mode": "explicit", "occupancy_profile": [0]},
                        {"occupancy_mode": "explicit", "occupancy_profile": [3] * 96},
                        {"occupancy_mode": "bad"}, {"occupancy_seed": 42}):
            with self.assertRaises(ValueError):
                env.reset(options=options)

    def test_T01_invalid_actions_leave_same_decision(self):
        env, factory = self.create()
        env.reset()
        worker = factory.workers[0]
        for action in ([0, 1], [0, 1, 2, 0], [-1, 0, 0], [3, 0, 0], [1.0, 0, 0],
                       ["1", 0, 0], [True, 0, 0], [np.nan, 0, 0], [np.inf, 0, 0],
                       np.zeros((1, 3), int), None):
            with self.subTest(action=action), self.assertRaises(ValueError):
                env.step(action)
        self.assertFalse(worker.exchange.writes)
        self.assertEqual(worker.completed, 0)
        self.assertEqual(env.step([2, 1, 0])[4]["decision_id"], 0)

    def test_T03_inherited_start_requests_before_work(self):
        env, factory = self.create()
        env.reset()
        worker = factory.workers[0]
        self.assertIs(EcoBuildingSimulator.start, EnergyPlus.start)
        events = worker.api.events
        run = next(i for i, e in enumerate(events) if e[0] == "run")
        before = [e[0] for e in events[:run]]
        self.assertEqual(before.count("new_state"), 1)
        self.assertEqual(before.count("register"), 9)
        self.assertEqual(before.count("request_variable"), 27)
        self.assertEqual(len(set(e[2:] for e in events[:run] if e[0] == "request_variable")), 27)
        self.assertLess(max(i for i,v in enumerate(before) if v == "register"),
                        min(i for i,v in enumerate(before) if v == "request_variable"))
        self.assertEqual(events[run][2][::2], ("-w", "-d", str(next(self.output.glob("*/*.epJSON")))))
        self.assertEqual(events[run][2][1], str(WEATHER))
        self.assertEqual([f.__name__ for f in worker.api.runtime.callbacks[ZONE]],
                         ["_collect_obs_and_info", "_process_action", "_process_context"])

    def test_T03_start_failures_clean_allocated_state(self):
        for target, method, allocated in (
            ("state_manager", "new_state", False),
            ("runtime", "set_console_output_status", True),
            ("runtime", "callback_progress", True),
            ("exchange", "request_variable", True),
        ):
            with self.subTest(method=method):
                def setup(worker):
                    def fail(*args):
                        raise RuntimeError("injected startup failure")
                    setattr(getattr(worker.api, target), method, fail)
                env, factory = self.create(factory=WorkerFactory(setup=setup))
                with self.assertRaisesRegex(RuntimeError, "injected"):
                    env.reset()
                worker = factory.workers[0]
                self.assertFalse(worker.api.state_manager.live)
                self.assertFalse(worker.worker_alive())
                self.assertEqual(any(e[0] == "delete_state" for e in worker.api.events), allocated)
                env.close()

    def test_T04_callbacks_and_T05_all_actions(self):
        env, factory = self.create(trace=True)
        plan = ((0, 0, 0), (2, 2, 2), (2, 2, 2), (1, 1, 1), OFF) + tuple(product(range(3), repeat=3))
        end = self.replay(env, plan=plan)
        self.assertEqual(end, "2025-08-08T00:00:00")
        worker = factory.workers[0]
        self.assertEqual(worker.phase, "end")
        trace = worker.trace
        action_checks = [x for x in trace if x[0] == "_process_action"]
        self.assertEqual(len(action_checks), 97)  # historical, initial and 95 intermediate
        decision = [x[0] for x in trace if x[2] == 1][1:]
        self.assertEqual(decision, ["_before_weather", "_before_heat_balance", "_after_predictor",
                                    "_system_report", "_after_predictor", "_system_report", "_collect_obs_and_info"])
        speed_handle = worker.exchange.handles[(1, "OFFICE DX UNIT")]
        self.assertIn(2, [v for _,h,v in worker.exchange.writes if h == speed_handle])
        self.assertIn(None, [v for _,h,v in worker.exchange.writes if h == speed_handle])
        env.close()

    def test_T06_week_across_month_and_complete_day(self):
        env, factory = self.create(episode=Episode((7, 29), days=7))
        self.assertEqual(self.replay(env), "2025-08-05T00:00:00")
        self.assertEqual(factory.workers[0].completed, 672)
        env.close()
        env, factory = self.create()
        self.assertEqual(self.replay(env), "2025-08-08T00:00:00")
        self.assertEqual(factory.workers[0].completed, 96)
        env.close()

    def test_T05_reject_mismatched_results(self):
        for field, change in (
            ("requested", lambda r: (1, 0, 0)),
            ("decision_id", lambda r: 5),
            ("episode_id", lambda r: r.episode_id - 1),
            ("start", lambda r: r.start + timedelta(seconds=1)),
        ):
            with self.subTest(field=field):
                def setup(worker):
                    real = worker.transport.publish
                    def publish(message):
                        if message.kind == "transition":
                            message = replace(message, **{field: change(message)})
                        real(message)
                    worker.transport.publish = publish
                env, factory = self.create(factory=WorkerFactory(setup=setup))
                env.reset()
                with self.assertRaises(EpisodeError):
                    env.step(OFF)
                self.assertFalse(factory.workers[0].worker_alive())
                env.close()

    def test_T06_last_normal_only_after_worker_success(self):
        for code in (3, None):
            with self.subTest(code=code):
                env, factory = self.create(factory=WorkerFactory(last_code=code))
                env.reset()
                for _ in range(95):
                    env.step(OFF)
                with self.assertRaisesRegex(EpisodeError, "exit code"):
                    env.step(OFF)
                self.assertEqual(factory.workers[0].completed, 96)
                env.close()

    def test_T07_occupancy_profiles_and_causality(self):
        env, factory = self.create(episode=Episode((8, 7), start_day="Saturday"))
        profile = [0] * 32 + [2] * 20 + [1] * 28 + [0] * 16
        _, info = env.reset(options={"occupancy_mode": "explicit", "occupancy_profile": profile})
        self.assertEqual(info["physical"]["occupancy"]["people"], 1)
        self.assertFalse(factory.workers[0].exchange.writes)
        for count in profile:
            obs, _, _, _, info = env.step((2, 2, 2))
            self.assertEqual(obs[3], count)
            self.assertNotIn("occupancy_profile", str(info))
            self.assertNotIn("occupancy_seed", str(info))
        env.close()
        options = {"occupancy_mode": "dynamic", "occupancy_seed": 42}
        for seed in (4, 123):
            env.reset(seed=seed, options=options)
            env.close()
        self.assertEqual(factory.workers[-2].profile, factory.workers[-1].profile)
        env.reset(seed=42, options={"occupancy_mode": "dynamic", "occupancy_seed": 43})
        self.assertNotEqual(factory.workers[-1].profile, factory.workers[-2].profile)
        env.close()
        for _ in range(2):
            env.reset(seed=89, options={"occupancy_mode": "dynamic"})
            env.close()
        self.assertEqual(factory.workers[-1].profile, factory.workers[-2].profile)

    def test_T07_projection_and_isolation(self):
        env, factory = self.create()
        obs, info = env.reset()
        np.testing.assert_array_equal(obs, np.array([24, 55, 610, 1, 92700], np.float32))
        self.assertAlmostEqual(info["physical"]["diagnostics"]["substep_means"]["indoor_rh_pct"], 53.0)
        info["physical"]["indoor"]["indoor_c"] = 999
        self.assertEqual(factory.workers[0].observer.get_observation()["indoor"]["indoor_c"], 24)
        from datetime import datetime
        for value in (None, np.nan, np.inf, 1e39):
            message = Result(1, None, datetime.now(), datetime.now(), {
                "indoor": {"indoor_c": value, "indoor_rh_pct": 0, "co2_ppm": 0},
                "occupancy": {"people": 0}, "energy": {"total_j": 0}})
            with self.subTest(value=value), self.assertRaises(EpisodeError):
                env._project(message)
        with self.assertRaisesRegex(EpisodeError, "Missing"):
            env._project(replace(message, physical={}))

    def test_T08_callback_errors_reach_facade(self):
        for attribute, value, regex in (
            ("ready", False, "not ready"),
            ("missing", ("Zone Mean Air Temperature", "OFFICE"), "unavailable"),
            ("read_error", ("Zone Mean Air Temperature", "OFFICE"), "API error"),
            ("bad_duration", True, "timestep|durations"),
        ):
            with self.subTest(attribute=attribute):
                def setup(worker):
                    setattr(worker.exchange, attribute, value)
                env, factory = self.create(factory=WorkerFactory(setup=setup))
                with self.assertRaisesRegex(EpisodeError, regex) as error:
                    env.reset()
                self.assertIn("Episode 1", str(error.exception))
                self.assertIsNotNone(error.exception.__cause__)
                self.assertTrue(factory.workers[0].api.runtime.stop_requested.is_set())
                env.close()

    def test_T08_partial_write_aborts_without_compensation(self):
        env, factory = self.create(factory=WorkerFactory(setup=lambda w: setattr(w.exchange, "fail_write", 2)))
        env.reset()
        worker = factory.workers[0]
        with self.assertRaisesRegex(EpisodeError, "decision 0"):
            env.step((2, 2, 2))
        self.assertEqual(len(worker.exchange.writes), 2)
        self.assertEqual(worker.completed, 0)
        with self.assertRaisesRegex(EpisodeError, "Episode failed"):
            env.step(OFF)

    def test_T08_worker_exit_without_result(self):
        env, factory = self.create(factory=WorkerFactory(driver=lambda *args: 0))
        with self.assertRaisesRegex(EpisodeError, "worker exited"):
            env.reset()
        self.assertFalse(factory.workers[0].api.state_manager.live)

    def test_T09_reset_and_close_12_cycles(self):
        env, factory = self.create()
        env.close()
        with self.assertRaises(gym.error.ResetNeeded):
            env.step(OFF)
        for i in range(12):
            _, info = env.reset(seed=i if i % 2 else None)
            self.assertEqual(env.episode_id, i + 1)
            if i % 2:
                env.close()
                env.close()
                with self.assertRaises(gym.error.ResetNeeded):
                    env.step(OFF)
            if i:
                self.assertFalse(factory.workers[-2].worker_alive())
                self.assertFalse(factory.workers[-2].api.state_manager.live)
        env.close()
        self.assertEqual(len({w.exchange.handles[(i, "OFFICE DX UNIT")] for i,w in enumerate(factory.workers,1)}), 12)

    def test_T09_close_during_startup_and_retains_stuck_thread(self):
        entering, release = Event(), Event()
        def driver(worker, runtime, state):
            entering.set()
            if not release.wait(3):
                return 99
            return 0
        env, factory = self.create(factory=WorkerFactory(driver=driver), shutdown_timeout=0.05)
        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(env.reset)
            try:
                self.assertTrue(entering.wait(1))
                with self.assertRaisesRegex(EpisodeError, "state retained"):
                    env.close()
                with self.assertRaises(EpisodeError):
                    pending.result(1)
                self.assertTrue(factory.workers[0].api.state_manager.live)
                with self.assertRaisesRegex(EpisodeError, "state retained"):
                    env.reset()
            finally:
                release.set()
                factory.workers[0].energyplus_thread.join(1)
        env.close()
        self.assertFalse(factory.workers[0].api.state_manager.live)

    def test_T10_model_allowlist_and_reference_protection(self):
        episode = Episode((8, 7))
        original = MODEL.read_bytes()
        dest = self.output / "episode"
        copy, weather, output = prepare_episode_inputs(MODEL, WEATHER, dest, episode)
        self.assertEqual(weather, WEATHER)
        self.assertEqual(MODEL.read_bytes(), original)
        self.assertFalse(output.exists())
        self.assertFalse(list(dest.glob("*.ddy")))
        prepared, reference = json.loads(copy.read_bytes()), json.loads(original)
        additions = {k:v for k,v in prepared.get("Output:Meter", {}).items()
                     if k not in reference.get("Output:Meter", {})}
        check_model_changes(reference, prepared, {"Output:Meter": additions} if additions else {})
        prepared["Site:Location"].clear()
        with self.assertRaisesRegex(ValueError, "outside the allowlist"):
            check_model_changes(reference, prepared, {"Output:Meter": additions} if additions else {})
        with self.assertRaises(FileExistsError):
            prepare_episode_inputs(MODEL, WEATHER, dest, episode)
        for model, epw in ((self.output / "missing", WEATHER), (MODEL, self.output / "missing")):
            with self.assertRaises(FileNotFoundError):
                prepare_episode_inputs(model, epw, self.output / "unused", episode)

    def test_T09_sb3_checker(self):
        env, _ = self.create()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            sb3_check(env, warn=True)
        for warning in caught:
            print("SB3 warning:", warning.message)

    def test_T09_gymnasium_checker(self):
        env, _ = self.create()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            gym_check(env)
        for warning in caught:
            print("Gymnasium warning:", warning.message)

    def test_T08_runtime_exception_preserves_cause(self):
        original = RuntimeError("exception from runtime executor")
        def driver(*args):
            raise original
        env, _ = self.create(factory=WorkerFactory(driver=driver))
        with self.assertRaisesRegex(EpisodeError, "exception from runtime executor") as error:
            env.reset()
        self.assertIs(error.exception.__cause__, original)

    def test_T08_startup_and_transition_deadlines(self):
        entered, release = Event(), Event()
        def wait_for_release(*args):
            entered.set()
            self.assertTrue(release.wait(2))
            return 0
        env, factory = self.create(factory=WorkerFactory(driver=wait_for_release),
                                   startup_timeout=0.05, shutdown_timeout=0.05)
        try:
            with self.assertRaisesRegex(TimeoutError, "timed out"):
                env.reset()
            self.assertTrue(entered.is_set())
            self.assertTrue(factory.workers[0].api.state_manager.live)
        finally:
            release.set()
        env.close()

        entered, release = Event(), Event()
        def setup(worker):
            apply = worker.hvac.apply
            def pause(action):
                entered.set()
                self.assertTrue(release.wait(2))
                return apply(action)
            worker.hvac.apply = pause
        env, factory = self.create(factory=WorkerFactory(setup=setup), transition_timeout=0.05, shutdown_timeout=0.05)
        env.reset()
        try:
            with self.assertRaisesRegex(TimeoutError, "timed out"):
                env.step(OFF)
            self.assertTrue(entered.is_set())
            self.assertEqual(factory.workers[0].completed, 0)
        finally:
            release.set()
        env.close()

    def test_T09_close_during_step_wakes_waiting_facade(self):
        entered, release = Event(), Event()
        def driver(worker, runtime, state):
            publish = worker.transport.publish
            def gated_publish(message):
                if message.kind == "transition":
                    entered.set()
                    self.assertTrue(release.wait(2))
                publish(message)
            worker.transport.publish = gated_publish
            return factory.drive(worker, runtime, state)
        factory = WorkerFactory(driver=driver)
        env, _ = self.create(factory=factory)
        env.reset()
        with ThreadPoolExecutor(2) as pool:
            pending = pool.submit(env.step, (2, 0, 1))
            try:
                self.assertTrue(entered.wait(1))
                with self.assertRaisesRegex(EpisodeError, "already in progress"):
                    env.step(OFF)
                closing = pool.submit(env.close)
                # Instrument the real cancel signal, independently of cleanup's lifecycle lock.
                with factory.workers[0].transport._ready:
                    self.assertTrue(factory.workers[0].transport._ready.wait_for(
                        factory.workers[0].transport.stopped, timeout=1))
                self.assertTrue(factory.workers[0].api.state_manager.live)
            finally:
                release.set()
            with self.assertRaises(EpisodeError):
                pending.result(2)
            closing.result(2)
        self.assertFalse(factory.workers[0].api.state_manager.live)

    def test_T03_thread_construction_failure_and_uncertain_launch(self):
        from types import SimpleNamespace
        import sinergym.simulators.eplus as native_module

        for constructing in (True, False):
            with self.subTest(constructing=constructing):
                env, factory = self.create()
                def fail(*args, **kwargs):
                    raise RuntimeError("injected thread launch failure")
                if constructing:
                    stub = fail
                else:
                    # No real thread is launched. The adapter sees an object
                    # whose launch status cannot safely be determined.
                    stub = lambda **kwargs: SimpleNamespace(start=fail, ident=None, is_alive=lambda: False)
                with patch.object(native_module, "threading", SimpleNamespace(Thread=stub)):
                    with self.assertRaisesRegex(RuntimeError, "thread launch failure"):
                        env.reset()
                worker = factory.workers[0]
                self.assertFalse(any(e[0] == "run" for e in worker.api.events))
                if not constructing:
                    self.assertTrue(worker.api.state_manager.live)
                    with self.assertRaisesRegex(EpisodeError, "launch status is unknown"):
                        env.reset()
                    # The test owns the stub and can now certify there was no start.
                    worker.energyplus_thread = None
                env.close()
                self.assertFalse(worker.api.state_manager.live)

    def test_T06_last_report_with_non_exiting_worker(self):
        entered, release = Event(), Event()
        def driver(worker, runtime, state):
            code = factory.drive(worker, runtime, state)
            entered.set()
            self.assertTrue(release.wait(2))
            return code
        factory = WorkerFactory(driver=driver)
        env, _ = self.create(factory=factory, shutdown_timeout=0.05)
        env.reset()
        for _ in range(95):
            env.step(OFF)
        try:
            with self.assertRaisesRegex(TimeoutError, "did not exit"):
                env.step(OFF)
            self.assertTrue(entered.is_set())
            self.assertEqual(factory.workers[0].completed, 96)
            self.assertTrue(factory.workers[0].api.state_manager.live)
        finally:
            release.set()
        env.close()

    def test_T09_reset_after_worker_failure_and_after_normal_end(self):
        calls = 0
        def driver(worker, runtime, state):
            nonlocal calls
            calls += 1
            if calls == 1:
                return 7
            return factory.drive(worker, runtime, state)
        factory = WorkerFactory(driver=driver)
        env, _ = self.create(factory=factory)
        with self.assertRaisesRegex(EpisodeError, "exit code 7"):
            env.reset()
        self.assertFalse(factory.workers[0].api.state_manager.live)
        self.replay(env)
        with self.assertRaises(gym.error.ResetNeeded):
            env.step(OFF)
        _, info = env.reset()
        self.assertIsNone(info["decision_id"])
        self.assertEqual(env.episode_id, 3)
        self.assertFalse(factory.workers[1].api.runtime.callbacks)
        env.close()

    def test_T09_concurrent_close_joins_and_destroys_once(self):
        env, factory = self.create()
        env.reset()
        worker = factory.workers[0]
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(env.close) for _ in range(2)]
            for future in futures:
                future.result(2)
        self.assertFalse(worker.worker_alive())
        self.assertEqual([e[0] for e in worker.api.events].count("delete_state"), 1)
