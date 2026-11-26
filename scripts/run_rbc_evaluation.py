"""Evaluate the seasonal RBC controller on the shared EcoBuilding manifests."""

import argparse
from datetime import datetime
from hashlib import file_digest
import json
from pathlib import Path

from ecobuilding.controllers import RBCConfig, SeasonalRBC
from ecobuilding.episodes import EpisodePlan
from ecobuilding.sinergym_adapter import EcoBuildingEnv


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models/office_1zone.epJSON"
EPW = ROOT / "models/weather/FRA_BF_Belfort.Fontaine.072960_TMYx.2011-2025.epw"
DEFAULT_RBC_CONFIG = ROOT / "configs/rbc/office_default.json"
TEMPERATURE_BOUNDS = (
    (20.0, 23.0), (20.0, 23.0), (20.0, 26.0), (20.0, 26.0),
    (20.0, 26.0), (23.0, 26.0), (23.0, 26.0), (23.0, 26.0),
    (20.0, 26.0), (20.0, 26.0), (20.0, 26.0), (20.0, 23.0),
)


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def violation(value, limits):
    low, high = limits
    if value < low:
        return low - value
    if value > high:
        return value - high
    return 0.0


def execute(output, scenario, controller, gym_seed):
    episode_output = output / "episode"
    env = EcoBuildingEnv(MODEL, EPW, episode_output, scenario.episode)
    controller.reset()
    totals = {
        "transitions": 0,
        "reward": 0.0,
        "energy_j": 0.0,
        "heating_j": 0.0,
        "cooling_dx_j": 0.0,
        "ventilation_j": 0.0,
        "occupied_steps": 0,
        "temperature_violation_steps": 0,
        "temperature_violation_c_sum": 0.0,
        "co2_violation_steps": 0,
        "humidity_violation_steps": 0,
        "action_changes": 0,
    }
    previous_action = None
    observations_path = output / "observations.jsonl"
    try:
        observation, info = env.reset(seed=gym_seed, options=scenario.reset_options())
        with observations_path.open("w", encoding="utf-8") as stream:
            stream.write(json.dumps({
                "step": None, "observation": observation.tolist(),
                "reward": None, "info": info,
            }, allow_nan=False) + "\n")
            for step in range(scenario.episode.steps):
                action = controller.act(observation, info)
                observation, reward, terminated, truncated, info = env.step(action)
                if terminated or truncated != (step == scenario.episode.steps - 1):
                    raise RuntimeError("Unexpected RBC episode boundary")

                physical = info["physical"]
                energy = physical["energy"]
                month = physical["time"]["month"]
                occupants = physical["occupancy"]["people"]
                temperature = physical["diagnostics"]["substep_means"]["indoor_c"]
                co2 = physical["diagnostics"]["substep_means"]["co2_ppm"]
                humidity = physical["diagnostics"]["substep_means"]["indoor_rh_pct"]
                occupied = occupants > 0
                limits = TEMPERATURE_BOUNDS[month - 1] if occupied else (15.0, 28.0)

                totals["transitions"] += 1
                totals["reward"] += reward
                totals["energy_j"] += energy["total_j"]
                totals["heating_j"] += energy["heating_j"]
                totals["cooling_dx_j"] += energy["cooling_dx_j"]
                totals["ventilation_j"] += energy["ventilation_j"]
                totals["occupied_steps"] += int(occupied)
                violation_c = violation(temperature, limits)
                totals["temperature_violation_steps"] += int(violation_c > 0)
                totals["temperature_violation_c_sum"] += violation_c
                totals["co2_violation_steps"] += int(occupied and co2 > 1000)
                totals["humidity_violation_steps"] += int(occupied and not 40 <= humidity <= 60)
                if previous_action is not None:
                    totals["action_changes"] += sum(
                        abs(current - previous)
                        for current, previous in zip(action, previous_action, strict=True)
                    )
                previous_action = action

                stream.write(json.dumps({
                    "step": step,
                    "observation": observation.tolist(),
                    "action": action,
                    "reward": reward,
                    "info": info,
                }, allow_nan=False) + "\n")
    finally:
        env.close()

    totals["heating_kwh"] = totals["heating_j"] / 3_600_000
    totals["cooling_dx_kwh"] = totals["cooling_dx_j"] / 3_600_000
    totals["ventilation_kwh"] = totals["ventilation_j"] / 3_600_000
    totals["energy_kwh"] = totals["energy_j"] / 3_600_000
    totals["natural_end"] = totals["transitions"] == scenario.episode.steps
    return totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("train", "validation", "test"), default="validation")
    parser.add_argument("--config", type=Path, default=DEFAULT_RBC_CONFIG)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--gym-seed", type=int, default=42)
    args = parser.parse_args()

    if args.output is None:
        parser.error("--output is required to keep RBC results outside source inputs")
    if args.gym_seed < 0:
        parser.error("--gym-seed must be nonnegative")
    if not MODEL.is_file():
        parser.error(f"Missing model: {MODEL}")
    if not EPW.is_file():
        parser.error(f"Missing EPW: {EPW}")

    config_path = args.config.resolve()
    if not config_path.is_file():
        parser.error(f"Missing RBC config: {config_path}")
    rbc_config = RBCConfig.load(config_path)
    controller = SeasonalRBC(rbc_config)
    plan = EpisodePlan.load()

    if args.manifest is not None:
        scenarios = plan.load_manifest(args.manifest)
    else:
        scenarios = plan.scenarios(args.split)

    output = args.output.resolve()
    if output.exists():
        parser.error("Output directory must be new")
    output.mkdir(parents=True)

    episode_summaries = []
    for index, scenario in enumerate(scenarios):
        episode_output = output / f"{args.split}-{index:03d}"
        episode_output.mkdir()
        totals = execute(episode_output, scenario, controller, args.gym_seed)
        totals.update({
            "control_start": scenario.date.strftime("%m-%d"),
            "occupancy_seed": scenario.occupancy_seed,
        })
        write_json(episode_output / "summary.json", totals)
        episode_summaries.append(totals)

    aggregate = {
        "split": args.split,
        "episodes": len(episode_summaries),
        "gym_seed": args.gym_seed,
        "controller": "SeasonalRBC",
        "controller_config": rbc_config.to_dict(),
        "model_sha256": digest(MODEL),
        "weather_sha256": digest(EPW),
        "episode_plan_config_sha256": digest(ROOT / "configs/rl/office_mdp.json"),
    }
    for key in (
        "transitions", "reward", "energy_kwh", "heating_kwh",
        "cooling_dx_kwh", "ventilation_kwh", "occupied_steps",
        "temperature_violation_steps", "temperature_violation_c_sum",
        "co2_violation_steps", "humidity_violation_steps", "action_changes",
    ):
        aggregate[key] = sum(row[key] for row in episode_summaries)
    write_json(output / "summary.json", aggregate)
    write_json(output / "episodes.json", episode_summaries)
    print(json.dumps(aggregate, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
