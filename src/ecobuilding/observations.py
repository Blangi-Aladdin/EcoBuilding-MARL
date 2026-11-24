"""Observe completed EnergyPlus zone timesteps without writing to the model."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isclose, isfinite
from numbers import Real


@dataclass(frozen=True)
class Variable:
    name: str
    key: str
    unit: str
    mode: str
    role: str
    optional: bool = False
    nonnegative: bool = False


OFFICE = "OFFICE"
ENV = "ENVIRONMENT"
DX = "OFFICE DX UNIT"
HEATER = "OFFICE ELECTRIC RESISTANCE"
VARIABLES = {
    "indoor_c": Variable("Zone Mean Air Temperature", OFFICE, "C", "both", "agent"),
    "indoor_rh_pct": Variable("Zone Air Relative Humidity", OFFICE, "%", "both", "agent", nonnegative=True),
    "co2_ppm": Variable("Zone Air CO2 Concentration", OFFICE, "ppm", "both", "agent", nonnegative=True),
    "outdoor_c": Variable("Site Outdoor Air Drybulb Temperature", ENV, "C", "zone", "agent"),
    "outdoor_rh_pct": Variable("Site Outdoor Air Relative Humidity", ENV, "%", "zone", "agent", nonnegative=True),
    "direct_solar_w_m2": Variable("Site Direct Solar Radiation Rate per Area", ENV, "W/m2", "zone", "agent", nonnegative=True),
    "diffuse_solar_w_m2": Variable("Site Diffuse Solar Radiation Rate per Area", ENV, "W/m2", "zone", "agent", nonnegative=True),
    "wind_m_s": Variable("Site Wind Speed", ENV, "m/s", "zone", "agent", nonnegative=True),
    "people": Variable("Zone People Occupant Count", OFFICE, "people", "zone", "agent", nonnegative=True),
    "heat_electric_w": Variable("Electric Equipment Electricity Rate", HEATER, "W", "mean", "energy", nonnegative=True),
    "heat_convective_w": Variable("Electric Equipment Convective Heating Rate", HEATER, "W", "mean", "evaluation", nonnegative=True),
    "heat_j": Variable("Electric Equipment Electricity Energy", HEATER, "J", "zone_sum", "energy", nonnegative=True),
    "dx_total_w": Variable("Unitary System Total Cooling Rate", DX, "W", "mean", "evaluation", nonnegative=True),
    "dx_sensible_w": Variable("Unitary System Sensible Cooling Rate", DX, "W", "mean", "evaluation"),
    "dx_latent_w": Variable("Unitary System Latent Cooling Rate", DX, "W", "mean", "evaluation"),
    "dx_electric_w": Variable("Unitary System Electricity Rate", DX, "W", "mean", "energy", nonnegative=True),
    "dx_speed_level": Variable("Unitary System DX Coil Speed Level", DX, "1", "stage", "diagnostic"),
    "dx_availability_schedule": Variable("Schedule Value", "DX SCHEDULED AVAILABILITY", "1", "both", "diagnostic"),
    "cooling_setpoint_c": Variable("Zone Thermostat Cooling Setpoint Temperature", OFFICE, "C", "both", "diagnostic"),
    "predicted_load_w": Variable("Zone Predicted Sensible Load to Setpoint Heat Transfer Rate", OFFICE, "W", "mean", "diagnostic"),
    "dx_air_kg_s": Variable("System Node Mass Flow Rate", "OFFICE COOLING SUPPLY", "kg/s", "mean", "diagnostic", nonnegative=True),
    "dx_coil_j": Variable("Cooling Coil Electricity Energy", "OFFICE DX TWO-STAGE COIL", "J", "sum", "diagnostic", True, True),
    "dx_fan_j": Variable("Fan Electricity Energy", "OFFICE DX FAN", "J", "sum", "diagnostic", True, True),
    "vent_j": Variable("Zone Ventilation Fan Electricity Energy", OFFICE, "J", "sum", "energy", nonnegative=True),
    "vent_m3_s": Variable("Zone Ventilation Outdoor Density Volume Flow Rate", OFFICE, "m3/s", "mean", "evaluation", nonnegative=True),
    "vent_inlet_c": Variable("Zone Ventilation Air Inlet Temperature", OFFICE, "C", "mean", "evaluation"),
    "infiltration_m3_s": Variable("Zone Infiltration Outdoor Density Volume Flow Rate", OFFICE, "m3/s", "mean", "evaluation", nonnegative=True),
}

CANDIDATE_FIELDS = {
    "temperature_c": ("indoor", "indoor_c"),
    "relative_humidity_pct": ("indoor", "indoor_rh_pct"),
    "co2_ppm": ("indoor", "co2_ppm"),
    "outdoor_temperature_c": ("outdoor", "outdoor_c"),
    "outdoor_relative_humidity_pct": ("outdoor", "outdoor_rh_pct"),
    "direct_solar_w_m2": ("outdoor", "direct_solar_w_m2"),
    "diffuse_solar_w_m2": ("outdoor", "diffuse_solar_w_m2"),
    "wind_m_s": ("outdoor", "wind_m_s"),
    "occupants": ("occupancy", "people"),
    "presence": ("occupancy", "presence"),
}


def joules_to_kwh(value):
    return value / 3_600_000


def m3_s_to_m3_h(value):
    return value * 3600


def numeric_candidate(observation):
    """Named scalars suitable for later NumPy conversion."""
    return {name: observation[group][key] for name, (group, key) in CANDIDATE_FIELDS.items()}


def zone_interval(year, month, day, hour, slot, steps_per_hour):
    base = datetime(year, month, day)
    if not 0 <= hour < 24 or not 1 <= slot <= steps_per_hour:
        raise ValueError("Invalid EnergyPlus hour or zone slot")
    duration = 3600 / steps_per_hour
    start = base + timedelta(seconds=hour*3600 + (slot-1)*duration)
    return start, start + timedelta(seconds=duration)


class ObservationManager:
    def __init__(self, exchange, variables=VARIABLES):
        self.exchange = exchange
        self.variables = variables
        self.detach()

    def request_variables(self, state):
        for spec in self.variables.values():
            self.exchange.request_variable(state, spec.name, spec.key)

    def initialize(self, state):
        if self._state is not None:
            raise RuntimeError("Detach before initializing a new state")
        if not self.exchange.api_data_fully_ready(state):
            raise RuntimeError("EnergyPlus API data is not ready")
        handles = {k: self.exchange.get_variable_handle(state, v.name, v.key)
                   for k, v in self.variables.items()}
        missing = [k for k, h in handles.items() if h < 0 and not self.variables[k].optional]
        if missing:
            raise RuntimeError(f"Required EnergyPlus variables unavailable: {missing}")
        self._state, self._handles = state, handles
        return dict(handles)

    def detach(self):
        self._state = self._environment = self._last = None
        self._handles = {}
        self._samples = []

    def _check_context(self):
        if self._state is None:
            raise RuntimeError("Initialize ObservationManager before collecting")
        if self.exchange.warmup_flag(self._state):
            raise RuntimeError("Warmup samples cannot be included")
        environment = self.exchange.current_environment_num(self._state)
        if self._environment is not None and self._environment != environment:
            raise RuntimeError("Detach or reset before collecting a different environment")
        self._environment = environment

    def _read(self, keys):
        values = {}
        for key in keys:
            handle = self._handles[key]
            if handle < 0:
                values[key] = None
                continue
            value = self.exchange.get_variable_value(self._state, handle)
            spec = self.variables[key]
            self._validate_value(key, value, spec.nonnegative)
            values[key] = value
        if self.exchange.api_error_flag(self._state):
            raise RuntimeError("EnergyPlus reported an observation API error")
        return values

    @staticmethod
    def _validate_value(key, value, nonnegative=False):
        if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
            raise ValueError(f"Invalid numeric observation {key}: {value}")
        if nonnegative and value < 0:
            raise ValueError(f"Negative observation {key}: {value}")

    def collect_system_step(self):
        self._check_context()
        seconds = self.exchange.system_time_step(self._state) * 3600
        end_seconds = self.exchange.current_time(self._state) * 3600
        if not isfinite(seconds) or seconds <= 0 or not isfinite(end_seconds):
            raise ValueError("Invalid finalized HVAC timestep")
        if self._samples and not isclose(end_seconds - self._samples[-1]["end_seconds"],
                                         seconds, rel_tol=0, abs_tol=1e-5):
            raise ValueError("Duplicate, missing or unordered HVAC timestep")
        values = self._read(k for k,v in self.variables.items()
                            if v.mode in ("mean", "both", "sum", "stage"))
        self._samples.append({"seconds": seconds, "end_seconds": end_seconds, **values})
        return dict(self._samples[-1])

    def finalize_zone_step(self, *, requested=None, last_applied=None, hvac_overrides_active=False,
                           cooling_speed_override=0, cooling_setpoint_override_active=False, occupancy_override_active=False):
        self._check_context()
        e, s = self.exchange, self._state
        year, month, day = e.calendar_year(s), e.month(s), e.day_of_month(s)
        hour, slot, steps_h = e.hour(s), e.zone_time_step_number(s), e.num_time_steps_in_hour(s)
        start, end = zone_interval(year, month, day, hour, slot, steps_h)
        seconds = e.zone_time_step(s) * 3600
        if not self._samples or not isclose(sum(r["seconds"] for r in self._samples), seconds,
                                            rel_tol=0, abs_tol=1e-6):
            raise ValueError("HVAC durations do not close the zone timestep")
        endpoint = hour*3600 + slot*3600/steps_h
        if not isclose(self._samples[-1]["end_seconds"], endpoint, rel_tol=0, abs_tol=1e-5):
            raise ValueError("Last HVAC endpoint differs from the zone boundary")
        if self._last and self._last["time"]["end"] != start.isoformat():
            raise ValueError("Duplicate or missing zone timestep")
        final = self._read(k for k,v in self.variables.items() if v.mode in ("zone","both","zone_sum"))
        integrals, summed = {}, {}
        for key, spec in self.variables.items():
            if spec.mode not in ("mean", "both", "sum"):
                continue
            values = [r[key] for r in self._samples]
            if spec.mode == "sum":
                summed[key] = None if values[0] is None else sum(values)
            else:
                integrals[key] = sum(r[key] * r["seconds"] for r in self._samples)
        means = {k:v/seconds for k,v in integrals.items()}
        people = final["people"]
        if people not in (0,1,2):
            raise ValueError(f"Unexpected discrete occupancy {people}")
        heating_j, dx_j, vent_j = final["heat_j"], integrals["dx_electric_w"], summed["vent_j"]
        for a,b in ((heating_j,integrals["heat_electric_w"]),
                    (means["dx_total_w"], means["dx_sensible_w"]+means["dx_latent_w"])):
            if not isclose(a,b,rel_tol=1e-9,abs_tol=1e-6):
                raise ValueError(f"Inconsistent energy or power: {a} versus {b}")
        total = heating_j + dx_j + vent_j
        stages = sorted({r["dx_speed_level"] for r in self._samples if r["dx_total_w"] > 1e-6})
        if any(stage not in (1,2) for stage in stages):
            raise ValueError(f"Invalid active DX stage {stages}")
        time = dict(start=start.isoformat(), end=end.isoformat(), year=year, weather_year_api=e.year(s), month=month, day=day,
                    weekday_api=e.day_of_week(s), day_of_year_api=e.day_of_year(s), hour_api=hour,
                    minute_api=e.minutes(s), zone_step=slot, zone_seconds=seconds,
                    hvac_seconds=[r["seconds"] for r in self._samples],
                    dst=e.daylight_savings_time_indicator(s), environment=self._environment)
        obs = {
            "time": time,
            "indoor": {k:final[k] for k in ("indoor_c","indoor_rh_pct","co2_ppm")},
            "outdoor": {k:final[k] for k,v in self.variables.items() if v.key == ENV},
            "occupancy": {"people": int(people), "presence": int(people>0)},
            "actions": dict(requested=requested,last_applied=last_applied,
                            active_action=last_applied if hvac_overrides_active else None,
                            hvac_overrides_active=hvac_overrides_active,
                            occupancy_override_active=occupancy_override_active),
            "equipment": {**{k:v for k,v in means.items() if k not in final},
                          "dx_speed_when_cooling": [int(stage) for stage in stages],
                          "dx_active": bool(stages), "heating_active": heating_j > 0,
                          "ventilation_active": means["vent_m3_s"] > 0,
                          "vent_m3_h": m3_s_to_m3_h(means["vent_m3_s"]),
                          "infiltration_m3_h": m3_s_to_m3_h(means["infiltration_m3_s"]),
                          "vent_electric_w": vent_j/seconds},
            "energy": {"heating_j":heating_j, "cooling_dx_j":dx_j, "ventilation_j":vent_j, "total_j":total,
                       "heating_kwh":joules_to_kwh(heating_j), "cooling_dx_kwh":joules_to_kwh(dx_j),
                       "ventilation_kwh":joules_to_kwh(vent_j), "total_kwh":joules_to_kwh(total),
                       "total_mean_w":total/seconds},
            "diagnostics": {"api_zone_end":final, "substep_means":means, "substep_energy_j":summed,
                            "heating_integral_j":integrals["heat_electric_w"],
                            "cooling_speed_override":cooling_speed_override,
                            "cooling_setpoint_override_active":cooling_setpoint_override_active,
                            "unusual":[k for k in ("indoor_rh_pct","outdoor_rh_pct") if final[k]>100],
                            "unavailable":[k for k,h in self._handles.items() if h<0]},
        }
        self.validate_observation(obs)
        self._last = deepcopy(obs)
        self._samples.clear()
        return obs

    def get_observation(self):
        return deepcopy(self._last)

    @staticmethod
    def validate_observation(obs):
        required = {"time","indoor","outdoor","occupancy","actions","equipment","energy","diagnostics"}
        if not isinstance(obs, dict) or not required.issubset(obs):
            raise ValueError("Incomplete zone observation")
        start, end = (datetime.fromisoformat(obs["time"][k]) for k in ("start","end"))
        seconds = obs["time"]["zone_seconds"]
        if seconds != 900 or (end-start).total_seconds() != seconds:
            raise ValueError("Invalid 15-minute observation interval")
        hvac_seconds = obs["time"]["hvac_seconds"]
        if (not hvac_seconds or any(not isfinite(x) or x<=0 for x in hvac_seconds)
            or not isclose(sum(hvac_seconds), seconds, rel_tol=0, abs_tol=1e-6)):
            raise ValueError("Invalid HVAC duration breakdown")
        actions = obs["actions"]
        if type(actions["hvac_overrides_active"]) is not bool or type(actions["occupancy_override_active"]) is not bool:
            raise ValueError("Invalid override status")
        if actions["active_action"] != (actions["last_applied"] if actions["hvac_overrides_active"] else None):
            raise ValueError("Inconsistent active and historical HVAC action")
        for action in (obs["actions"][key] for key in ("requested","last_applied","active_action")):
            if action is not None and (not isinstance(action,(list,tuple)) or len(action)!=3 or any(type(x) is not int or not 0<=x<=2 for x in action)):
                raise ValueError("Invalid HVAC action in observation")
        people = obs["occupancy"]["people"]
        if type(people) is not int or people not in (0,1,2) or obs["occupancy"]["presence"] != int(people>0):
            raise ValueError("Inconsistent occupancy")
        for key, value in numeric_candidate(obs).items():
            ObservationManager._validate_value(key, value, key not in ("temperature_c","outdoor_temperature_c"))
        equipment = obs["equipment"]
        levels = equipment["dx_speed_when_cooling"]
        if any(type(x) is not int or x not in (1,2) for x in levels) or equipment["dx_active"] != bool(levels):
            raise ValueError("Inconsistent active DX stages")
        if obs["diagnostics"]["cooling_speed_override"] not in (0,1,2):
            raise ValueError("Invalid DX speed override")
        energy = obs["energy"]
        for key in ("heating_j","cooling_dx_j","ventilation_j","total_j","total_kwh","total_mean_w"):
            ObservationManager._validate_value(key, energy[key], True)
        checks = {"total_j":sum(energy[k] for k in ("heating_j","cooling_dx_j","ventilation_j")),
                  "total_kwh":joules_to_kwh(energy["total_j"]), "total_mean_w":energy["total_j"]/seconds}
        if any(not isclose(energy[k], v, rel_tol=1e-9, abs_tol=1e-6) for k,v in checks.items()):
            raise ValueError("Inconsistent energy units or balance")
