"""Replay EnergyPlus validation scenarios with the consolidated callbacks."""

import csv
from dataclasses import dataclass
import json
from pathlib import Path

from .actions import HVACController
from .observations import ObservationManager, VARIABLES, numeric_candidate
from .occupancy import OccupancyManager
from .occupancy_profiles import REFERENCE, STEPS


@dataclass(frozen=True)
class Scenario:
    name: str
    dates: tuple[int, int, int, int]
    first: tuple[int, int]
    actions: tuple
    profile: tuple | None = None
    start_day: str = "Monday"
    release_after: int | None = None
    all_off_step: int | None = None
    output_meter: bool = True
    instrument: bool = True


def write_csv(path, rows):
    if rows:
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


class SimulationRunner:
    """Run sequential scenarios with fresh EnergyPlus states in one process."""

    def __init__(self, api, *, cooling_setpoint_c, step_minutes=15):
        if step_minutes != 15:
            raise ValueError("ObservationManager requires a 15-minute zone step")
        self.api = api
        self.cooling_setpoint_c = cooling_setpoint_c
        self.hvac = HVACController(api.exchange, cooling_setpoint_c=cooling_setpoint_c)
        self.occupancy = OccupancyManager(api.exchange)
        self.observer = ObservationManager(api.exchange)
        self.steps_per_hour = 60 // step_minutes

    def run(self, model_path, weather_path, output, scenario):
        model_path, weather_path, output = map(Path, (model_path, weather_path, output))
        for path in (model_path, weather_path):
            if not path.is_file():
                raise FileNotFoundError(f"Required validation input is absent: {path}")
        actions = tuple(None if a is None else self.hvac.validate_action(a) for a in scenario.actions)
        if not actions or len(actions) % STEPS:
            raise ValueError("Supply complete 96-step validation days")
        if scenario.profile is not None:
            if len(scenario.profile) != len(actions):
                raise ValueError("Occupation and action profiles must cover the same steps")
            for people in scenario.profile:
                self.occupancy.fraction(people)
        if scenario.release_after is not None and not 1 <= scenario.release_after < len(actions):
            raise ValueError("Release must occur before the final step")
        if scenario.all_off_step is not None and (
            not 1 <= scenario.all_off_step <= len(actions) or actions[scenario.all_off_step - 1] != (0, 0, 0)
        ):
            raise ValueError("all_off_step requires a matching zero action")
        model = json.loads(model_path.read_bytes())
        if next(iter(model["Timestep"].values()))["number_of_timesteps_per_hour"] != self.steps_per_hour:
            raise ValueError("Model timestep differs from validation configuration")
        period = next(iter(model["RunPeriod"].values()))
        period.update(zip(("begin_month", "begin_day_of_month", "end_month", "end_day_of_month"), scenario.dates))
        period["day_of_week_for_start_day"] = scenario.start_day
        outputs = model["Output:Variable"]
        if scenario.instrument:
            for logical, spec in VARIABLES.items():
                existing = any(v["key_value"].upper() == spec.key and v["variable_name"] == spec.name
                               and v["reporting_frequency"].lower() == "timestep" for v in outputs.values())
                if not existing:
                    outputs["Observation " + logical] = {"key_value": spec.key, "variable_name": spec.name,
                                                        "reporting_frequency": "Timestep"}
        if scenario.output_meter:
            model.setdefault("Output:Meter", {})["Facility electricity"] = {
                "key_name": "Electricity:Facility", "reporting_frequency": "Timestep"}
        output.mkdir(parents=True, exist_ok=False)
        copy_path = output / "office_1zone.epJSON"
        copy_path.write_text(json.dumps(model, indent=2) + "\n", encoding="utf-8")
        state = self.api.state_manager.new_state()
        try:
            return self._run_state(state, weather_path, output, copy_path, scenario, actions)
        finally:
            self.observer.detach()
            self.hvac.detach()
            self.occupancy.detach()
            try:
                self.api.runtime.clear_callbacks()
            finally:
                self.api.state_manager.delete_state(state)

    def _run_state(self, state, weather, output, model, scenario, actions):
        e, runtime = self.api.exchange, self.api.runtime
        hvac, occupant, observer = self.hvac, self.occupancy, self.observer
        self.hvac.request_variables(state)
        self.observer.request_variables(state)
        commands, trace, raw, observations, errors, handles = [], [], [], [], [], []
        last = None
        controlled = False
        setpoint_overridden = False

        def guarded(function):
            def callback(s):
                try:
                    date = e.month(s), e.day_of_month(s)
                    if errors or e.warmup_flag(s) or not scenario.first <= date <= scenario.dates[2:]:
                        return
                    function(s)
                    if e.api_error_flag(s):
                        raise RuntimeError("EnergyPlus API error flag")
                except Exception as exc:
                    errors.append((function.__name__, exc))
                    runtime.stop_simulation(s)
            return callback

        def event(s, phase, index, people=None, load=None, speed=None, action=None, exposed=None):
            trace.append(dict(step=index, phase=phase, month=e.month(s), day=e.day_of_month(s),
                              raw_hour=e.hour(s), raw_minute=e.minutes(s), people_raw=people, load_w=load,
                              speed_override=speed, action=action, exposed_previous_end=exposed))

        @guarded
        def exogenous(s):
            if not handles:
                inventory = e.list_available_api_data_csv(s).decode()
                (output / "api-data.csv").write_text(inventory, encoding="utf-8")
                hvac.initialize(s)
                occupant.initialize(s)
                handles.extend(dict(logical=k, name=VARIABLES[k].name, key=VARIABLES[k].key, handle=h)
                               for k, h in observer.initialize(s).items())
            i = len(commands)
            previous = occupant.observe()
            if scenario.profile is not None:
                occupant.apply_profile(scenario.profile, i)
            event(s, "before_weather_occupancy", i + 1, people=previous)

        @guarded
        def apply(s):
            nonlocal last, controlled, setpoint_overridden
            i = len(commands)
            action = actions[i]
            previous = observer.get_observation()
            if (previous is None) != (i == 0):
                raise RuntimeError("Missing or residual observation at the decision boundary")
            entry_people = occupant.observe()
            explicit_off = i + 1 == scenario.all_off_step
            wrote = action is not None and (not controlled or action != last or explicit_off)
            if wrote:
                last = hvac.all_off() if explicit_off else hvac.apply(action)
                controlled = True
                setpoint_overridden = setpoint_overridden or action[1] != 0
            if action is None and controlled:
                raise RuntimeError("Schedule release before switching to native control")
            expected = (scenario.profile[i] if scenario.profile is not None else
                        REFERENCE[i % STEPS] if e.day_of_week(s) in (2, 3, 4, 5, 6) else 0)
            commands.append(dict(step=i + 1, requested=action, last_applied=last, active=action is not None,
                                 expected_people=expected, people_at_decision_raw=entry_people,
                                 people_exposed=None if previous is None else previous["occupancy"]["people"],
                                 wrote=wrote, method="all_off" if explicit_off else "apply" if wrote else ""))
            event(s, "before_heat_balance_action", i + 1, people=entry_people, action=action,
                  exposed=None if previous is None else previous["time"]["end"])

        @guarded
        def synchronize(s):
            load = hvac.synchronize_cooling()
            event(s, "after_predictor", len(commands), people=occupant.observe(), load=load,
                  speed=hvac.cooling_speed_override)

        @guarded
        def system_end(s):
            raw.append(dict(step=len(commands), **observer.collect_system_step()))
            event(s, "system_end_finalized", len(commands), people=occupant.observe(),
                  speed=hvac.cooling_speed_override)

        @guarded
        def zone_end(s):
            nonlocal controlled, setpoint_overridden
            command = commands[-1]
            obs = observer.finalize_zone_step(
                requested=command["requested"], last_applied=hvac.get_last_action(),
                hvac_overrides_active=command["active"], cooling_speed_override=hvac.cooling_speed_override,
                cooling_setpoint_override_active=setpoint_overridden,
                occupancy_override_active=scenario.profile is not None)
            observations.append(obs)
            event(s, "zone_end_observation", len(commands), people=obs["occupancy"]["people"],
                  speed=hvac.cooling_speed_override, action=command["requested"], exposed=obs["time"]["end"])
            if len(commands) == scenario.release_after:
                hvac.release()
                controlled = False
                setpoint_overridden = False
                write_csv(output / "release.csv", [{"step": len(commands), "last_action": hvac.get_last_action(),
                                                    "writes": json.dumps(hvac.get_last_writes())}])

        for register, callback in (
            (runtime.callback_begin_zone_timestep_before_set_current_weather, exogenous),
            (runtime.callback_begin_zone_timestep_before_init_heat_balance, apply),
            (runtime.callback_after_predictor_after_hvac_managers, synchronize),
            (runtime.callback_end_system_timestep_after_hvac_reporting, system_end),
            (runtime.callback_end_zone_timestep_after_zone_reporting, zone_end),
        ):
            register(state, callback)
        status = runtime.run_energyplus(state, ["-d", str(output), "-w", str(weather), str(model)])
        if errors:
            callback, error = errors[0]
            raise RuntimeError(f"{scenario.name}: EnergyPlus callback {callback} failed; see {output}") from error
        if status or len(observations) != len(actions):
            raise RuntimeError(f"{scenario.name}: EnergyPlus exit {status}, {len(observations)}/{len(actions)} steps")
        for filename, rows in (
            ("commandes", commands), ("chronologie", trace), ("mesures-sous-pas", raw), ("handles", handles),
            ("candidats-numeriques", [numeric_candidate(obs) for obs in observations]),
        ):
            write_csv(output / (filename + ".csv"), rows)
        with (output / "observations.jsonl").open("w", encoding="utf-8") as stream:
            for obs in observations:
                stream.write(json.dumps(obs, allow_nan=False) + "\n")
        return observations
