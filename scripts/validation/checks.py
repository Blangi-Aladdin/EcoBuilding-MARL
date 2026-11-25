"""Compare named observations to EnergyPlus reports and validated control runs."""
from ast import literal_eval
from collections import defaultdict
import csv
from datetime import datetime
import json
from math import isclose

from ecobuilding.observations import ObservationManager, VARIABLES
from ecobuilding.simulation import write_csv

def read(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def equal(actual, expected):
    assert isclose(actual,expected,abs_tol=1e-6,rel_tol=1e-9),(actual,expected)


def col(rows, spec):
    prefix = f"{spec.key}:{spec.name} [".upper()
    return next((k for k in rows[0] if k.upper().startswith(prefix) and k.endswith("(TimeStep)")),None)


def from_observation(obs,key,samples):
    if key == "dx_speed_level":
        return sum(float(x[key])*float(x["seconds"]) for x in samples)/900, "weighted_reported_speed"
    if key in ("indoor_c","dx_availability_schedule","cooling_setpoint_c"):
        return obs["diagnostics"]["api_zone_end"][key],"zone_end"
    group = {"both":"substep_means","mean":"substep_means","sum":"substep_energy_j",
             "zone":"api_zone_end","zone_sum":"api_zone_end"}[VARIABLES[key].mode]
    return obs["diagnostics"][group][key],group


def analyze(root, model, weather_path, names):
    if not __debug__:
        raise RuntimeError("Run validation without Python optimization")
    candidate_folders = [root / name for name in names]
    native_outputs = json.loads(model.read_bytes())["Output:Variable"]
    with weather_path.open() as f:
        for _ in range(8):
            next(f)
        epw = {(int(r[1]),int(r[2]),int(r[3])):r for r in csv.reader(f)}
    validation, energy, chronology, handles, runs, weather = [], [], [], [], [], []
    weeks = []
    versus_end = defaultdict(float)
    clocks = defaultdict(float)
    with (root/"observations.jsonl").open("w") as export:
        for folder in candidate_folders:
            label = folder.name
            assert "0 Warning; 0 Severe Errors" in (folder/"eplusout.end").read_text()
            obs = [json.loads(r) for r in (folder/"observations.jsonl").read_text().splitlines()]
            commands = read(folder/"commandes.csv")
            runs.append(dict(case=label,steps=len(obs),warning=0,severe=0,
                             environment=obs[0]["time"]["environment"]))
            if label.startswith("long-"):
                assert len(obs)==672 and len({tuple(o["actions"]["active_action"]) for o in obs})==27
            assert len(commands)==len(obs)
            for record in read(folder/"handles.csv"):
                assert int(record["handle"]) >= 0
                handles.append(dict(case=label,**record))
            samples, events = defaultdict(list), defaultdict(list)
            for row in read(folder/"mesures-sous-pas.csv"):
                samples[int(row["step"])].append(row)
            for row in read(folder/"chronologie.csv"):
                events[int(row["step"])].append(row)
            raw_csv = read(folder/"eplusout.csv")
            tcol = col(raw_csv,VARIABLES["indoor_c"])
            csv_rows = [row for row in raw_csv if row[tcol]][-len(obs):]
            assert len(csv_rows)==len(obs)
            columns = {k:col(raw_csv,v) for k,v in VARIABLES.items()}
            diffs = defaultdict(float)
            methods = {}
            prev = None
            for i,(o,c,r) in enumerate(zip(obs,commands,csv_rows),1):
                ObservationManager.validate_observation(o)
                export.write(json.dumps({"scenario":label,"step":i,**o},allow_nan=False)+"\n")
                t = o["time"]
                start,end = (datetime.fromisoformat(t[key]) for key in ("start","end"))
                assert end > start and (not prev or prev["time"]["end"]==t["start"])
                assert t["dst"] is False and t["day_of_year_api"]==start.timetuple().tm_yday
                if prev:
                    was_midnight = start.hour == start.minute == 0
                    previous_weekday = prev["time"]["weekday_api"]
                    assert t["weekday_api"] == (previous_weekday%7+1 if was_midnight else previous_weekday)
                hour = t["hour_api"]
                assert start.hour==hour and start.minute==15*(t["zone_step"]-1)
                raw_end = f"{hour:02d}:{15*t['zone_step']:02d}" if t["zone_step"] < 4 else f"{hour+1:02d}:00"
                assert r["Date/Time"].strip()==start.strftime("%m/%d")+"  "+raw_end+":00"
                assert c["people_exposed"] == ("" if not prev else str(prev["occupancy"]["people"]))
                assert o["occupancy"]["people"]==int(c["expected_people"])
                chronological = events[i]
                assert chronological[0]["phase"]=="before_weather_occupancy"
                entry = chronological[1]
                assert entry["phase"]=="before_heat_balance_action"
                assert entry["exposed_previous_end"]==("" if not prev else prev["time"]["end"])
                if prev:
                    equal(float(entry["people_raw"]),prev["occupancy"]["people"])
                first_predictor = next(e for e in chronological if e["phase"]=="after_predictor")
                equal(float(first_predictor["people_raw"]),o["occupancy"]["people"])
                assert chronological[-1]["phase"]=="zone_end_observation"
                if (label=="occupation-F" and 48<=i<=56) or (label=="calendar" and 95<=i<=98):
                    chronology.extend(dict(case=label,**e) for e in chronological)
                action = o["actions"]["active_action"]
                equipment = o["equipment"]
                e = o["energy"]
                if action is not None:
                    h,dx,v = action
                    equal(equipment["heat_electric_w"],1000*h)
                    equal(equipment["heat_convective_w"],1000*h)
                    equal(e["heating_kwh"],.25*h)
                    equal(equipment["vent_m3_h"],(0,40,120)[v])
                    equal(equipment["vent_electric_w"],(0,20/3,20)[v])
                    assert set(equipment["dx_speed_when_cooling"])<=({dx} if dx else set())
                    if dx==0:
                        equal(e["cooling_dx_j"],0)
                        equal(equipment["dx_total_w"],0)
                equal(equipment["infiltration_m3_h"],12)
                diag = o["diagnostics"]
                equal(e["cooling_dx_j"], diag["substep_energy_j"]["dx_coil_j"]+diag["substep_energy_j"]["dx_fan_j"])
                for key, csv_column in columns.items():
                    if not csv_column:
                        continue
                    actual, method = from_observation(o,key,samples[i])
                    expected = float(r[csv_column])
                    equal(actual,expected)
                    diffs[key]=max(diffs[key],abs(actual-expected))
                    methods[key] = method
                    if key in ("indoor_rh_pct","co2_ppm"):
                        versus_end[key]=max(versus_end[key], abs(diag["api_zone_end"][key]-expected))
                    if key=="indoor_c":
                        versus_end["indoor_c_mean"]=max(versus_end["indoor_c_mean"],
                                                       abs(diag["substep_means"][key]-expected))
                facility = r.get("Electricity:Facility [J](TimeStep)")
                if facility is not None:
                    facility = float(facility)
                    equal(e["total_j"],facility)
                energy.append(dict(case=label,step=i,start=t["start"],end=t["end"],
                                   heating_zone_j=e["heating_j"],
                                   heating_integrated_j=diag["heating_integral_j"],cooling_dx_j=e["cooling_dx_j"],
                                   ventilation_j=e["ventilation_j"],total_j=e["total_j"],
                                   facility_csv_j=facility,delta_j=None if facility is None else e["total_j"]-facility,
                                   total_kwh=e["total_kwh"],mean_w=e["total_mean_w"]))
                if label in ("matrix-summer","matrix-winter") and start.minute==45:
                    # Weather records use hour 1..24, radiation is an hourly energy density.
                    source = epw[start.month,start.day,start.hour+1]
                    outdoor = o["outdoor"]
                    for key,epw_index in (("outdoor_c",6),("outdoor_rh_pct",8),("wind_m_s",21)):
                        equal(outdoor[key],float(source[epw_index]))
                    weather.append(dict(case=label,source_year=source[0],epw_hour=source[3],
                                        end=t["end"],epw_drybulb_c=source[6],api_zone_drybulb_c=outdoor["outdoor_c"],
                                        epw_rh_pct=source[8],api_rh_pct=outdoor["outdoor_rh_pct"],
                                        epw_direct_wh_m2=source[14],api_direct_w_m2=outdoor["direct_solar_w_m2"],
                                        epw_diffuse_wh_m2=source[15],api_diffuse_w_m2=outdoor["diffuse_solar_w_m2"],
                                        epw_wind_m_s=source[21],api_wind_m_s=outdoor["wind_m_s"]))
                clocks[label]=max(clocks[label],abs(t["minute_api"]-15*t["zone_step"]))
                prev=o
            for key in VARIABLES:
                validation.append(dict(case=label,logical=key,csv_column=columns[key],method=methods.get(key),
                                       steps=len(obs) if columns[key] else 0,max_abs_error=diffs.get(key)))
            check_scenario(label, obs, commands, events, columns)
            if label.startswith("long-"):
                weeks.append(dict(case=label, steps=len(obs), substeps=sum(map(len, samples.values())),
                                  simultaneous_steps=sum(o["energy"]["heating_j"] > 0 and o["equipment"]["dx_total_w"] > 0 for o in obs),
                                  total_kwh=sum(o["energy"]["total_kwh"] for o in obs)))
    if "native-before" in names and "release" in names:
        native = [json.loads(line) for line in (root / "native-before/observations.jsonl").read_text().splitlines()]
        released = [json.loads(line) for line in (root / "release/observations.jsonl").read_text().splitlines()]
        release_record, = read(root / "release/release.csv")
        assert release_record["step"] == "60"
        assert [write[0] for write in json.loads(release_record["writes"])] == ["reset_actuator"] * 5
        for reference, actual in zip(native[60:], released[60:]):
            for key in ("heat_electric_w", "vent_m3_s", "dx_availability_schedule", "cooling_setpoint_c"):
                equal(actual["diagnostics"]["substep_means"][key], reference["diagnostics"]["substep_means"][key])
    if "native-before" in names:
        for case in ("native-after", "native-no-reports"):
            if case in names:
                for filename in ("observations.jsonl", "mesures-sous-pas.csv"):
                    assert (root / "native-before" / filename).read_bytes() == (root / case / filename).read_bytes()
    catalog=[]
    for k,v in VARIABLES.items():
        native=any(x["key_value"].upper()==v.key and x["variable_name"]==v.name
                   and x["reporting_frequency"].lower()=="timestep" for x in native_outputs.values())
        rule=next((r["method"] for r in validation if r["logical"] == k and r["method"]), None)
        catalog.append(dict(logical=k,energyplus_name=v.name,key=v.key,native_unit=v.unit,target_unit=v.unit,
                            data_type="float; observed as integer" if k in ("people","dx_speed_level") else "float",
                            native_timestep_export=native,api_available_without_added_reports=True,
                            native_csv_available=native,instrumented_csv_available=True,
                            optional=v.optional,measurement=v.mode,comparison_rule=rule,
                            callback=("zone end and finalized HVAC end" if v.mode=="both" else
                                      "zone end" if v.mode in ("zone","zone_sum") else "finalized HVAC end"),
                            update_frequency=("zone report" if v.mode in ("zone","zone_sum") else
                                              "each finalized HVAC interval plus zone snapshot" if v.mode=="both"
                                              else "each finalized HVAC interval"),
                            domain=({"people":"0, 1 or 2 people",
                                     "dx_speed_level":"1 or 2 when producing cooling",
                                     "dx_availability_schedule":"fraction; native schedule 0 or 1",
                                     "indoor_rh_pct":"nonnegative; >100 flagged, no clipping",
                                     "outdoor_rh_pct":"nonnegative; >100 flagged, no clipping"}
                                    .get(k,"nonnegative" if v.nonnegative else "finite; signed allowed")),
                            role=v.role))
    for filename,data in (("catalogue-observations",catalog),("validation-api-csv",validation),
                          ("chronologie-callbacks",chronology),("bilan-energetique",energy),
                          ("handles",handles),("runs",runs),("semaines",weeks),("comparaison-epw",weather)):
        write_csv(root/(filename+".csv"),data)
    print("Runs",len(runs),"steps",sum(r["steps"] for r in runs))
    print("Maximum differences for mismatched reporting conventions",dict(versus_end))
    print("Max minute API discrepancy",max(clocks.values()))
    print("Largest CSV errors",sorted(((r["max_abs_error"],r["logical"],r["case"]) for r in validation
                                      if r["max_abs_error"] is not None),reverse=True)[:8])


def check_scenario(label, obs, commands, events, columns):
    from run import COMBINATIONS, TRANSITIONS

    actions = [o["actions"]["active_action"] for o in obs]
    if label != "native-no-reports":
        assert all(columns.values()), (label, [k for k, v in columns.items() if not v])
    if label.startswith("matrix-"):
        assert actions[20:74] == [list(a) for a in COMBINATIONS for _ in range(2)]
        if label == "matrix-summer":
            speeds = {v for o in obs for v in o["equipment"]["dx_speed_when_cooling"]}
            assert speeds == {1, 2}
    if label.startswith("long-"):
        assert any(o["energy"]["heating_j"] > 0 and o["equipment"]["dx_total_w"] > 0 for o in obs)
        assert all(commands[i]["wrote"] == "False" for i in range(len(obs)) if i % 19 in (1, 2, 3))
    if label.startswith("winter-cooling-"):
        level = int(label[-1])
        assert {v for o in obs for v in o["equipment"]["dx_speed_when_cooling"]} == {level}
    if label == "transitions":
        assert actions[32:46] == [list(a) for a in TRANSITIONS for _ in range(2)]
        assert commands[44]["method"] == "all_off"
        assert obs[44]["energy"]["total_j"] == 0
    if label == "release":
        assert obs[59]["diagnostics"]["cooling_setpoint_override_active"]
        for o in obs[60:]:
            assert o["actions"]["active_action"] is None and o["actions"]["last_applied"] == [2, 2, 2]
            assert not o["diagnostics"]["cooling_setpoint_override_active"]
    if label == "leave-active":
        assert actions[-1] == [2, 2, 2] and obs[-1]["occupancy"]["people"] == 2
        assert obs[-1]["energy"]["total_j"] > 0
    if label == "calendar":
        assert obs[95]["time"]["end"] == obs[96]["time"]["start"]
        assert obs[95]["time"]["start"][5:10] == "07-31"
        assert obs[96]["time"]["start"][5:10] == "08-01"
    for o, command in zip(obs, commands):
        assert o["actions"]["active_action"] == (list(literal_eval(command["requested"])) if command["requested"] != "" else None)
        predictor = [row for row in events[int(command["step"])] if row["phase"] == "after_predictor"]
        active = o["actions"]["active_action"]
        for row in predictor:
            expected = str(active[1] if active is not None and float(row["load_w"]) < 0 else 0)
            assert row["speed_override"] == expected, (label, command["step"], row, expected)
