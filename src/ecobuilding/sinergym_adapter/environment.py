"""Gymnasium façade for the experimental EcoBuilding simulator."""

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from threading import Lock
from uuid import uuid4

import gymnasium as gym
import numpy as np

from ecobuilding.actions import HVACController
from ecobuilding.occupancy import OccupancyManager
from ecobuilding.occupancy_profiles import generate

from .model import Episode, prepare_episode_inputs
from .simulator import EcoBuildingSimulator, ZONE_STEP
from .transport import Action, EpisodeCancelled, EpisodeError


@dataclass(frozen=True)
class Field:
    path: tuple[str, ...]
    unit: str


DEFAULT_FIELDS = (
    Field(("indoor", "indoor_c"), "°C"),
    Field(("indoor", "indoor_rh_pct"), "%"),
    Field(("indoor", "co2_ppm"), "ppm"),
    Field(("occupancy", "people"), "people"),
    Field(("energy", "total_j"), "J"),
)


class EcoBuildingEnv(gym.Env):
    """Prototype with one interactive worker and a provisional numeric projection."""

    def __init__(self, model_path, weather_path, output_root, episode, *, fields=DEFAULT_FIELDS,
                 cooling_setpoint_c=25, startup_timeout=120, transition_timeout=15,
                 shutdown_timeout=10, trace=False):
        super().__init__()
        self.model_path, self.weather_path, self.output_root = map(Path, (model_path, weather_path, output_root))
        if not isinstance(episode, Episode):
            raise TypeError("episode must be an Episode")
        self.episode = episode
        self.fields = tuple(fields)
        if not self.fields or any(not isinstance(f, Field) or not f.path or not f.unit for f in self.fields):
            raise ValueError("Supply named observation paths with units")
        for timeout in (startup_timeout, transition_timeout, shutdown_timeout):
            if not isfinite(timeout) or timeout <= 0:
                raise ValueError("Timeouts must be positive and finite")
        self.startup_timeout = startup_timeout
        self.transition_timeout = transition_timeout
        self.shutdown_timeout = shutdown_timeout
        self.cooling_setpoint_c = cooling_setpoint_c
        self.trace = trace
        self.action_space = gym.spaces.MultiDiscrete([3, 3, 3])
        self.observation_space = gym.spaces.Box(-np.inf, np.inf, (len(self.fields),), dtype=np.float32)
        self._operation = Lock()
        self._lifecycle = Lock()
        self._worker = None
        self._episode_id = 0
        self._output_prefix = uuid4().hex
        self._decision = 0
        self._end = None
        self._status = "idle"

    def reset(self, *, seed=None, options=None):
        if not self._operation.acquire(blocking=False):
            raise EpisodeError("A reset or step is already in progress")
        try:
            with self._lifecycle:
                self._close_locked()
                episode, profile = self._reset_inputs(seed, options)
                self._episode_id += 1
                episode_dir = self.output_root / f"{self._output_prefix}-{self._episode_id}"
                model, weather, output = prepare_episode_inputs(
                    self.model_path, self.weather_path, episode_dir, episode,
                )
                worker = EcoBuildingSimulator(
                    self._episode_id, episode, profile,
                    cooling_setpoint_c=self.cooling_setpoint_c, trace=self.trace,
                )
                self._worker = worker
                self._status = "starting"
                try:
                    worker.start(str(model), str(weather), str(output), self._episode_id)
                except BaseException as exc:
                    self._fail(worker, exc)
                    raise
            try:
                result = worker.transport.receive_result(self.startup_timeout, worker.worker_alive)
                if (result.kind != "initial" or result.episode_id != self._episode_id or
                        result.requested is not None or result.applied is not None or result.last or
                        result.end - result.start != ZONE_STEP or
                        (result.end.month, result.end.day) != episode.first or
                        (result.end.hour, result.end.minute, result.end.second) != (0, 0, 0)):
                    raise EpisodeError("Unexpected initial observation")
                observation, info = self._project(result)
                with self._lifecycle:
                    worker.transport.check()
                    self._decision, self._end, self._status = 0, result.end, "ready"
                return observation, info
            except BaseException as exc:
                with self._lifecycle:
                    self._fail(worker, exc)
                raise
        finally:
            self._operation.release()

    @property
    def episode_id(self):
        """Technical identity outside Gymnasium's deterministic step payload."""
        with self._lifecycle:
            return self._episode_id if self._episode_id else None

    def step(self, action):
        if not self._operation.acquire(blocking=False):
            raise EpisodeError("A reset or step is already in progress")
        try:
            with self._lifecycle:
                worker = self._worker
                status = self._status
                if status in ("failed", "shutdown-failed"):
                    raise EpisodeError("Episode failed; close or reset after safe cleanup") from self._failure
                if status != "ready":
                    raise gym.error.ResetNeeded("A reset is required before step")
                values = HVACController.validate_action(action)
                if not self.action_space.contains(np.asarray(values)):
                    raise ValueError("Action is outside MultiDiscrete([3,3,3])")
                decision, start = self._decision, self._end
            try:
                worker.transport.send_action(Action(self._episode_id, decision, values))
                result = worker.transport.receive_result(self.transition_timeout, worker.worker_alive)
                last = decision + 1 == worker.episode_config.steps
                if (result.episode_id != self._episode_id or result.decision_id != decision or
                        result.start != start or result.end != start + ZONE_STEP or
                        result.requested != values or result.applied != values or result.last != last):
                    raise EpisodeError(f"Unexpected result for decision {decision}")
                observation, info = self._project(result)
                if last:
                    worker.confirm_exit(self.shutdown_timeout)
                with self._lifecycle:
                    worker.transport.check()
                    self._decision, self._end = decision + 1, result.end
                    self._status = "finished" if last else "ready"
                return observation, 0.0, False, last, info
            except BaseException as exc:
                with self._lifecycle:
                    self._fail(worker, exc)
                raise
        finally:
            self._operation.release()

    def close(self):
        with self._lifecycle:
            self._close_locked()

    def _close_locked(self):
        if self._worker is not None:
            try:
                self._worker.stop(self.shutdown_timeout)
            except BaseException as exc:
                self._failure = exc
                self._status = "shutdown-failed"
                raise
            self._worker = None
        self._status = "closed"

    def _fail(self, worker, cause):
        if self._worker is not worker or isinstance(cause, EpisodeCancelled):
            return
        worker.transport.fail(f"Episode {self._episode_id}, {self._status}: {cause}", cause)
        try:
            self._close_locked()
        except BaseException as cleanup:
            cause.add_note(f"Cleanup incomplete: {cleanup}")
        else:
            self._status = "failed"
        self._failure = cause

    def _reset_inputs(self, seed, options):
        options = dict(options or {})
        episode = options.pop("episode", self.episode)
        profile = options.pop("occupancy_profile", None)
        occupancy_seed = options.pop("occupancy_seed", None)
        mode = options.pop("occupancy_mode", "native")
        if options or not isinstance(episode, Episode):
            raise ValueError("Invalid reset options or episode")
        if mode not in ("native", "explicit", "dynamic"):
            raise ValueError("Choose native, explicit or dynamic occupancy")
        if (profile is not None) != (mode == "explicit") or (occupancy_seed is not None and mode != "dynamic"):
            raise ValueError("Supply a profile only in explicit mode and a seed only in dynamic mode")
        if occupancy_seed is not None and type(occupancy_seed) is not int:
            raise ValueError("The occupation seed must be an integer")
        super().reset(seed=seed)
        if mode == "dynamic":
            if occupancy_seed is None:
                occupancy_seed = int(self.np_random.integers(0, 2**63))
            profile = generate(occupancy_seed, days=episode.days, start_weekday=episode.first_weekday)
        if profile is not None:
            profile = tuple(profile)
            if len(profile) != episode.steps:
                raise ValueError("Occupancy profile must contain one count per controlled interval")
            for people in profile:
                OccupancyManager.fraction(people)
        return episode, profile

    def _project(self, result):
        values = []
        for field in self.fields:
            value = result.physical
            for key in field.path:
                if not isinstance(value, dict) or key not in value:
                    raise EpisodeError(f"Missing observation field {field.path}")
                value = value[key]
            if not isinstance(value, (int, float, np.number)) or not isfinite(value):
                raise EpisodeError(f"Unavailable or nonnumeric observation field {field.path}")
            values.append(value)
        with np.errstate(over="ignore", invalid="ignore"):
            observation = np.asarray(values, dtype=np.float32)
        if not np.isfinite(observation).all() or not self.observation_space.contains(observation):
            raise EpisodeError("Projection does not produce a finite Box observation")
        return observation, {
            "kind": result.kind, "decision_id": result.decision_id,
            "start": result.start.isoformat(), "end": result.end.isoformat(),
            "requested": result.requested, "applied": result.applied,
            "controlled": result.kind == "transition", "last": result.last, "physical": result.physical,
        }
