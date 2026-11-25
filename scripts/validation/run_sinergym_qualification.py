"""Orchestrate historical Sinergym qualification using regenerated direct references."""

import argparse
import csv
from hashlib import sha256
from itertools import product
import io
import json
from pathlib import Path
from random import Random
import resource
import subprocess
import sys
from tempfile import mkdtemp

from run import build_case, run_cases

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/validation/lot2_sinergym.json"


def digest(values):
    return sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def load():
    from ecobuilding.sinergym_adapter import Episode

    config = json.loads(CONFIG.read_text())
    reference = json.loads((ROOT / config["reference_config"]).read_text())
    for key in ("model", "weather"):
        with (ROOT / reference[key]).open("rb") as stream:
            if not stream.read(1):
                raise ValueError(f"Empty {key}")
    output = (ROOT / config["output_root"]).resolve()
    if not output.is_relative_to(ROOT / "simulation-outputs") or output == ROOT / "simulation-outputs":
        raise ValueError("Qualification output must have a dedicated ignored directory")

    specs = config["equivalence"]["cases"]
    cases = {name: build_case(name, reference) for name in specs}
    if set(cases) | config["equivalence"]["exclusions"].keys() != reference["cases"].keys():
        raise ValueError("Incomplete qualification inventory")
    for name, case in cases.items():
        if digest(case.actions) != specs[name]["actions_sha256"] or (
                case.profile is not None and digest(case.profile) != specs[name]["expected_people_sha256"]):
            raise ValueError(f"Historical inputs differ: {name}")
        Episode(case.first, len(case.actions) // 96, reference["history_days"], case.start_day)

    weeks = config["weekly_resets"]
    rng = Random(weeks["action_seed"])
    actions = tuple(product(range(3), repeat=3))
    weekly = [vector for _ in range(25) for vector in rng.sample(actions, len(actions))][:672]
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(("decision", "heating", "cooling", "ventilation"))
    writer.writerows((i, *a) for i, a in enumerate(weekly))
    if sha256(stream.getvalue().encode()).hexdigest() != weeks["actions_csv_sha256"]:
        raise ValueError("Weekly actions differ from the archived sequence")
    for spec in weeks["episodes"]:
        episode = Episode(spec["first"], spec["days"], spec["history_days"], spec["start_day"])
        if episode.steps != len(weekly) or spec["occupancy_mode"] not in ("native", "dynamic"):
            raise ValueError(f"Invalid historical week: {spec['case']}")
        if spec["occupancy_mode"] == "dynamic" and type(spec.get("occupancy_seed")) is not int:
            raise ValueError(f"Missing historical seed: {spec['case']}")
    return config, reference, output, cases, weekly


def write(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def equivalence(out, config, reference, cases):
    for folder in ("audit", "references-historiques", "sinergym", "comparaisons", "graphiques"):
        (out / folder).mkdir()
    direct = out / "reproductions-directes"
    run_cases(reference, direct, cases)
    specs = config["equivalence"]["cases"]
    with (out / "audit/inventaire-36.7.csv").open("w", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("case", "category"))
        for name, case in cases.items():
            folder = direct / name
            if "0 Warning; 0 Severe Errors" not in (folder / "eplusout.end").read_text():
                raise RuntimeError(f"EnergyPlus diagnostics differ: {name}")
            with (folder / "commandes.csv").open(newline="") as commands:
                people = [int(row["expected_people"]) for row in csv.DictReader(commands)]
            if digest(people) != specs[name]["expected_people_sha256"]:
                raise RuntimeError(f"Historical occupation differs: {name}")
            write(out / "references-historiques" / f"{name}.json",
                  dict(actions=case.actions, expected_people=people, profile=case.profile,
                       first=case.first, days=len(case.actions) // 96, start_day=case.start_day,
                       history_days=reference["history_days"]))
            writer.writerow((name, specs[name]["category"]))
    write(out / "audit/tolerances.json", config["equivalence"]["tolerances"])
    write(out / "audit/execution-inputs.json",
          {**reference, "gym_seed": config["gym_seed"]})
    for tool, timeout in (("_sinergym_replay.py", 240), ("_sinergym_compare.py", 120)):
        subprocess.run([sys.executable, str(Path(__file__).with_name(tool)), str(ROOT), str(out)],
                       check=True, timeout=timeout)


def weekly_resets(out, config, reference, actions):
    from ecobuilding.sinergym_adapter import EcoBuildingEnv, Episode

    from ecobuilding.occupancy_profiles import generate

    episodes = config["weekly_resets"]["episodes"]
    write(out / "actions.json", actions)
    env = EcoBuildingEnv(ROOT / reference["model"], ROOT / reference["weather"], out / "engine",
                         Episode((12, 17), days=7), reward_mode="legacy_zero",
                         cooling_setpoint_c=reference["cooling_setpoint_c"])
    trajectory_c = None
    for spec in episodes:
        profile = {"occupancy_mode": spec["occupancy_mode"]}
        if "occupancy_seed" in spec:
            profile["occupancy_seed"] = spec["occupancy_seed"]
        episode = Episode(spec["first"], spec["days"], spec["history_days"], spec["start_day"])
        expected_people = (generate(spec["occupancy_seed"], days=episode.days,
                                    start_weekday=episode.first_weekday)
                           if spec["occupancy_mode"] == "dynamic" else None)
        try:
            vector, info = env.reset(seed=config["gym_seed"], options={**profile, "episode": episode})
            worker = env._worker
            trace = [{"observation": vector.tolist(), "info": info}]
            for index, action in enumerate(actions):
                vector, reward, terminated, truncated, next_info = env.step(action)
                if ((reward, terminated, truncated) != (0.0, False, index == len(actions) - 1)
                        or next_info["decision_id"] != index or next_info["start"] != info["end"]
                        or next_info["requested"] != action or next_info["applied"] != action):
                    raise RuntimeError(f"Weekly temporal contract failed at {spec['case']}:{index}")
                if expected_people is not None and next_info["physical"]["occupancy"]["people"] != expected_people[index]:
                    raise RuntimeError(f"Weekly occupancy differs at {spec['case']}:{index}")
                info = next_info
                trace.append({"observation": vector.tolist(), "info": info})
            if worker.worker_alive() or worker.sim_results["exit_code"] != 0:
                raise RuntimeError("Week did not end naturally")
        finally:
            env.close()
        if worker.energyplus_state is not None or worker.worker_alive():
            raise RuntimeError("Weekly worker resources retained")
        if spec["case"] == "C":
            trajectory_c = trace
        if spec["case"] == "D" and trajectory_c != trace:
            raise RuntimeError("Weeks C and D differ")
        if spec["case"] == "E" and all(
                a["info"]["physical"]["occupancy"] == b["info"]["physical"]["occupancy"]
                for a, b in zip(trajectory_c[1:], trace[1:], strict=True)):
            raise RuntimeError("Week E did not vary with the occupancy seed")
        write(out / f"week-{spec['case']}.json", dict(inputs=spec, trajectory=trace,
              peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--equivalence", action="store_true")
    mode.add_argument("--weekly", action="store_true")
    args = parser.parse_args()
    config, reference, output, cases, actions = load()
    if args.validate_only:
        print(json.dumps(dict(status="validated_without_simulation", cases=list(cases),
                              weekly_actions=len(actions), weekly_episodes=len(config["weekly_resets"]["episodes"]),
                              output=str(output)), indent=2))
        return
    output.mkdir(parents=True, exist_ok=True)
    out = Path(mkdtemp(prefix="qualification-", dir=output))
    print(out, flush=True)
    write(out / "configuration.json", config)
    if args.weekly:
        weekly_resets(out, config, reference, actions)
    else:
        equivalence(out, config, reference, cases)


if __name__ == "__main__":
    main()
