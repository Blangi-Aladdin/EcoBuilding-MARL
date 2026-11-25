"""Sinergym worker with EcoBuilding's physical callbacks and episode transport."""

from datetime import datetime, timedelta
from functools import wraps
from queue import Queue

from sinergym.simulators.eplus import EnergyPlus

from ecobuilding.actions import HVACController
from ecobuilding.cooling import CoolingCommand
from ecobuilding.observations import ObservationManager, zone_interval
from ecobuilding.occupancy import OccupancyManager

from .transport import EpisodeCancelled, EpisodeError, Result, Transport


ZONE_STEP = timedelta(seconds=900)


def callback(method):
    @wraps(method)
    def guarded(self, state):
        try:
            if self.transport.stopped():
                self.api.runtime.stop_simulation(state)
                return
            if self.terminal:
                return
            if self.exchange.warmup_flag(state):
                self.phase = "warm-up"
                return
            # EnergyPlus KindOfSim::RunPeriodWeather.
            if self.exchange.kind_of_sim(state) != 3:
                return
            if self.trace is not None:
                self.trace.append((method.__name__, self.phase, self.completed))
            method(self, state)
            if self.exchange.api_error_flag(state):
                raise EpisodeError("EnergyPlus data exchange error flag")
        except EpisodeCancelled:
            self.api.runtime.stop_simulation(state)
        except BaseException as exc:
            failed_phase = self.phase
            self.phase = "failure"
            self.transport.fail(
                f"Episode {self.transport.episode_id}, {failed_phase}, decision {self.completed}, "
                f"callback {method.__name__}: {exc}", exc,
            )
            self.api.runtime.stop_simulation(state)
    return guarded


class _RuntimeStatus:
    """Report native runtime failures through the owning worker's transport."""

    def __init__(self, runtime, worker):
        self._runtime = runtime
        self._worker = worker

    def __getattr__(self, name):
        return getattr(self._runtime, name)

    def run_energyplus(self, state, arguments):
        worker = self._worker
        episode = worker.transport.episode_id
        try:
            code = self._runtime.run_energyplus(state, arguments)
        except BaseException as exc:
            worker.phase = "failure"
            worker.transport.fail(
                f"Episode {episode}, decision {worker.completed}, EnergyPlus runtime: {exc}", exc
            )
            return 1
        if code != 0:
            worker.phase = "failure"
            worker.transport.fail(
                f"Episode {episode}, decision {worker.completed}, EnergyPlus exit code {code}"
            )
        return code


class EcoBuildingSimulator(EnergyPlus):
    """One Sinergym worker per episode. start() is inherited unchanged."""

    def __init__(self, episode_id, episode, profile, *, cooling_setpoint_c, trace=False, _api=None):
        super().__init__(
            name=f"EcoBuilding-{episode_id}", obs_queue=Queue(1), info_queue=Queue(1),
            act_queue=Queue(1), context_queue=Queue(1),
        )
        self.transport = Transport(episode_id)
        if _api is not None:
            self.api = _api
            self.exchange = _api.exchange
        self.api.runtime = _RuntimeStatus(self.api.runtime, self)
        self.episode_config = episode
        self.profile = profile
        self.trace = [] if trace else None
        self.phase = "warm-up"
        self.completed = 0
        self.terminal = False
        self.initial_published = False
        self.next_action = None
        self.applied = None
        self.hvac = HVACController(self.exchange, cooling_setpoint_c=cooling_setpoint_c)
        self.occupancy = OccupancyManager(self.exchange)
        self.observer = ObservationManager(self.exchange)
        self._requested_state = None
        self._bound = False
        self._origin = None
        self._zone = None
        self._action_applied_in_zone = False
        self._setpoint_overridden = False
        self._closed = False
        for name, function in (
            ("callback_begin_zone_timestep_before_set_current_weather", self._before_weather),
            ("callback_begin_zone_timestep_before_init_heat_balance", self._before_heat_balance),
            ("callback_after_predictor_after_hvac_managers", self._after_predictor),
            ("callback_end_system_timestep_after_hvac_reporting", self._system_report),
        ):
            self.register_simulator_callback(name, function)

    def make_eplus_args(self):
        arguments = super().make_eplus_args()
        state = self.energyplus_state
        if state is None:
            raise EpisodeError("Sinergym has not allocated a state")
        if self._requested_state != state:
            # The observation catalog already requests the predictor on this state.
            if not any((variable.name, variable.key) == CoolingCommand.LOAD
                       for variable in self.observer.variables.values()):
                self.hvac.request_variables(state)
            self.observer.request_variables(state)
            self._requested_state = state
        return arguments

    def worker_alive(self):
        return self.energyplus_thread is not None and self.energyplus_thread.is_alive()

    def confirm_exit(self, timeout):
        self.transport.check()
        thread = self.energyplus_thread
        if thread is None:
            raise EpisodeError("Sinergym worker is missing")
        thread.join(timeout)
        self.transport.check()
        if thread.is_alive():
            raise TimeoutError("EnergyPlus did not exit after the last physical report")
        code = self.sim_results.get("exit_code")
        if code != 0 or not self.terminal:
            raise EpisodeError(f"EnergyPlus did not finish the episode normally (exit code {code})")

    def stop(self, timeout):
        """Cancel first, join with a bound, and delegate only after the worker exits."""
        if self._closed:
            return
        self.transport.cancel()
        thread = self.energyplus_thread
        if thread is not None:
            if thread.ident is None:
                raise EpisodeError("Sinergym thread launch status is unknown; state retained")
            thread.join(timeout)
            if thread.is_alive():
                raise EpisodeError("EnergyPlus worker is still active; state retained")
        self.hvac.detach()
        self.occupancy.detach()
        self.observer.detach()
        if thread is not None:
            super().stop()
        elif self.energyplus_state is not None:
            # start() may fail after allocation but before the thread starts.
            try:
                self.api.runtime.clear_callbacks()
            finally:
                self.api.state_manager.delete_state(self.energyplus_state)
        self.energyplus_state = self.energyplus_thread = self._requested_state = None
        self._closed = True

    def _interval(self, state):
        e = self.exchange
        if e.daylight_savings_time_indicator(state) or e.num_time_steps_in_hour(state) != 4:
            raise EpisodeError("Expected four zone steps per hour and no DST")
        return zone_interval(e.calendar_year(state), e.month(state), e.day_of_month(state),
                             e.hour(state), e.zone_time_step_number(state), 4)

    @callback
    def _before_weather(self, state):
        start, end = self._interval(state)
        if self._origin is None:
            self._origin = datetime(start.year, *self.episode_config.first)
        if start < self._origin - ZONE_STEP:
            self.phase = "history"
            return
        expected = self._origin + self.completed * ZONE_STEP
        if not self.initial_published:
            if end != self._origin:
                raise EpisodeError("Missed the final preparatory zone step")
            self.phase = "initial"
        else:
            if start != expected or self.next_action is None or self._zone is not None:
                raise EpisodeError("Controlled zone boundary or pending action is inconsistent")
            self.phase = "control"
        if not self._bound:
            self.hvac.initialize(state)
            self.occupancy.initialize(state)
            self.observer.initialize(state)
            self._bound = True
        self._zone = (start, end)
        self._action_applied_in_zone = False
        if self.phase == "control" and self.profile is not None:
            self.occupancy.apply_profile(self.profile, self.completed)

    @callback
    def _before_heat_balance(self, state):
        if self.phase == "control":
            values = self.next_action.values
            if self.applied != values:
                self.applied = self.hvac.apply(values)
                self._setpoint_overridden |= values[1] != 0
            self._action_applied_in_zone = True

    @callback
    def _after_predictor(self, state):
        if self.phase == "control":
            self.hvac.synchronize_cooling()

    @callback
    def _system_report(self, state):
        if self.phase in ("initial", "control"):
            self.observer.collect_system_step()

    @callback
    def _collect_obs_and_info(self, state):
        if self.phase not in ("initial", "control"):
            return
        controlled = self.phase == "control"
        action = self.next_action
        if controlled and (not self._action_applied_in_zone or action is None or action.values != self.applied):
            raise EpisodeError("Finalized a zone without its applied action")
        physical = self.observer.finalize_zone_step(
            requested=action.values if controlled else None,
            last_applied=self.hvac.get_last_action(), hvac_overrides_active=controlled,
            cooling_speed_override=self.hvac.cooling_speed_override,
            cooling_setpoint_override_active=self._setpoint_overridden,
            occupancy_override_active=controlled and self.profile is not None,
        )
        start, end = (datetime.fromisoformat(physical["time"][key]) for key in ("start", "end"))
        if controlled and self.completed == 0:
            expected_weekday = (self.episode_config.first_weekday + 1) % 7 + 1
            if physical["time"]["weekday_api"] != expected_weekday:
                raise EpisodeError("The simulated weekday differs from the agreed episode calendar")
        if self.exchange.api_error_flag(state):
            raise EpisodeError("EnergyPlus API error before publication")
        if (start, end) != self._zone or end - start != ZONE_STEP:
            raise EpisodeError("EnergyPlus finalized an unexpected interval")
        decision = self.completed if controlled else None
        if controlled:
            self.completed += 1
        self.terminal = self.completed == self.episode_config.steps
        if self.terminal:
            self.phase = "end"
        self._zone = self.next_action = None
        self.initial_published = True
        self.transport.publish(Result(
            self.transport.episode_id, decision, start, end, physical,
            action.values if controlled else None, self.applied, self.terminal,
        ))

    @callback
    def _process_action(self, state):
        if not self.initial_published:
            return
        if self._zone is not None or self.next_action is not None:
            raise EpisodeError("Sinergym action callback was invoked outside its decision boundary")
        action = self.transport.receive_action()
        if action.decision_id != self.completed:
            raise EpisodeError(f"Expected decision {self.completed}, received {action.decision_id}")
        self.next_action = action

    def _process_context(self, state):
        """The occupation callback is the only owner of exogenous writes."""
