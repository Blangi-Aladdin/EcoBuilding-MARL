"""Run a configured EcoBuilding episode or validate its inputs without EnergyPlus."""

import argparse
from hashlib import file_digest
from importlib.metadata import version
import json
from math import isfinite
import os
from pathlib import Path
import platform
from secrets import randbits
import subprocess
from tempfile import mkdtemp

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs/simulation/sinergym_office.json"


def relative_path(value):
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Use a repository-relative path: {path}")
    resolved = (ROOT / path).resolve()
    if not resolved.is_relative_to(ROOT):
        raise ValueError(f"Path escapes the repository: {path}")
    return resolved


def load_config(path):
    from ecobuilding.actions import HVACController
    from ecobuilding.occupancy import OccupancyManager
    from ecobuilding.sinergym_adapter import EcoBuildingEnv, Episode, RewardConfig

    config = json.loads(path.read_text(encoding="utf-8"))
    required = {"model_path", "weather_path", "output_root", "episode", "action_blocks"}
    optional = {"seed", "occupancy", "cooling_setpoint_c", "fields",
                "startup_timeout", "transition_timeout", "shutdown_timeout", "trace", "reward_mode", "reward_config"}
    if not isinstance(config, dict) or required - config.keys() or config.keys() - required - optional:
        raise ValueError("Missing or unsupported episode configuration keys")

    model, weather, output = (relative_path(config[key]) for key in
                              ("model_path", "weather_path", "output_root"))
    for input_path in (model, weather):
        with input_path.open("rb") as stream:
            if not stream.read(1):
                raise ValueError(f"Empty input file: {input_path}")
    if not isinstance(json.loads(model.read_text(encoding="utf-8")), dict):
        raise ValueError("The epJSON model must be an object")
    for candidate in (output, *output.parents):
        if candidate.exists():
            if not candidate.is_dir():
                raise NotADirectoryError(candidate)
            if not os.access(candidate, os.W_OK | os.X_OK):
                raise PermissionError(f"Output directory parent is not writable: {candidate}")
            break
    if not output.is_relative_to(ROOT / "simulation-outputs") or output == ROOT / "simulation-outputs":
        raise ValueError("Choose a dedicated subdirectory of simulation-outputs")

    if not isinstance(config["episode"], dict):
        raise ValueError("episode must be an object")
    episode = Episode(**config["episode"])
    seed = config.get("seed")
    options = config.get("occupancy", {"occupancy_mode": "native"})
    if seed is not None and (type(seed) is not int or seed < 0):
        raise ValueError("Gymnasium seed must be a nonnegative integer or null")
    if not isinstance(options, dict):
        raise ValueError("occupancy must be an object")
    mode = options.get("occupancy_mode", "native")
    if mode not in ("native", "explicit", "dynamic"):
        raise ValueError("Unsupported occupancy mode")
    allowed = {"occupancy_mode"} | ({"occupancy_profile"} if mode == "explicit" else
                                   {"occupancy_seed"} if mode == "dynamic" else set())
    if options.keys() - allowed:
        raise ValueError("Occupancy options do not match the mode")
    if mode == "dynamic" and "occupancy_seed" in options:
        if type(options["occupancy_seed"]) is not int or options["occupancy_seed"] < 0:
            raise ValueError("Occupancy seed must be a nonnegative integer")
    if mode == "explicit":
        profile = options.get("occupancy_profile")
        if not isinstance(profile, list) or len(profile) != episode.steps:
            raise ValueError("Explicit occupation requires one count per interval")
        for people in profile:
            OccupancyManager.fraction(people)

    settings = {key: config[key] for key in optional & config.keys()
                if key not in {"fields", "seed", "occupancy", "reward_config"}}
    if "trace" in settings and type(settings["trace"]) is not bool:
        raise ValueError("trace must be a boolean")
    for key in settings.keys() - {"trace", "reward_mode"}:
        if type(settings[key]) not in (int, float) or not isfinite(settings[key]):
            raise ValueError(f"{key} must be a finite number")
    if "fields" in config:
        if not isinstance(config["fields"], list):
            raise ValueError("fields must be a list")
        fields = [parse_field(item) for item in config["fields"]]
        if len(set(fields)) != len(fields):
            raise ValueError("Observation fields must be distinct")
        settings["fields"] = fields

    if "reward_config" in config:
        parameters = config["reward_config"]
        if not isinstance(parameters, dict):
            raise ValueError("reward_config must be an object")
        settings["reward_config"] = RewardConfig(**parameters)

    actions = []
    if not isinstance(config["action_blocks"], list):
        raise ValueError("action_blocks must be a list")
    for block in config["action_blocks"]:
        if not isinstance(block, dict) or block.keys() != {"steps", "action"}:
            raise ValueError("Each action block needs steps and action")
        count = block["steps"]
        if type(count) is not int or not 1 <= count <= episode.steps - len(actions):
            raise ValueError("Action block exceeds the configured episode or is empty")
        actions.extend([HVACController.validate_action(block["action"])] * count)
    if len(actions) != episode.steps:
        raise ValueError(f"Supply exactly {episode.steps} actions")
    EcoBuildingEnv(model, weather, output, episode, **settings).close()
    HVACController(None, cooling_setpoint_c=settings.get("cooling_setpoint_c", 25))

    return config, model, weather, output, episode, seed, options, settings, actions


def parse_field(field):
    from ecobuilding.sinergym_adapter import DEFAULT_FIELDS, Field

    if not isinstance(field, dict) or field.keys() != {"path", "unit"}:
        raise ValueError("Each field needs path and unit")

    segments = field["path"]
    if not isinstance(segments, list) or any(type(key) is not str or not key for key in segments):
        raise ValueError("A field path must contain nonempty strings")
    projection = Field(tuple(segments), field["unit"])
    if projection not in DEFAULT_FIELDS:
        raise ValueError("The launcher accepts only the qualified observation fields")
    return projection


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def run_episode(inputs):
    from ecobuilding.sinergym_adapter import EcoBuildingEnv

    config, model, weather, output, episode, seed, options, settings, actions = inputs
    output.mkdir(parents=True, exist_ok=True)
    run = Path(mkdtemp(prefix="episode-", dir=output))
    seed = randbits(63) if seed is None else seed
    metadata = {"configuration": config, "gym_seed": seed, "actions": actions, "model_sha256": digest(model),
                "weather_sha256": digest(weather), "python": platform.python_version()}
    summary = {"status": "error", "transitions": 0, "energy_j": dict.fromkeys(
        ("heating_j", "cooling_dx_j", "ventilation_j", "total_j"), 0.0)}
    env = EcoBuildingEnv(model, weather, run / "engine", episode, **settings)
    try:
        metadata["versions"] = {name: version(name) for name in
                                ("sinergym", "gymnasium", "numpy", "stable-baselines3", "torch")}
        metadata["energyplus"] = subprocess.check_output(["energyplus", "--version"], text=True).strip()
        write_json(run / "inputs.json", metadata)
        with (run / "observations.jsonl").open("w", encoding="utf-8") as stream:
            initial, info = env.reset(seed=seed, options=options)
            stream.write(json.dumps({"observation": initial.tolist(), "info": info}, allow_nan=False) + "\n")
            for index, action in enumerate(actions, start=1):
                vector, reward, terminated, truncated, info = env.step(action)
                if terminated or truncated != (index == len(actions)):
                    raise RuntimeError("Unexpected episode boundary")
                stream.write(json.dumps(dict(observation=vector.tolist(), reward=reward, info=info,
                                             terminated=terminated, truncated=truncated), allow_nan=False) + "\n")
                summary["transitions"] = index
                for key in summary["energy_j"]:
                    summary["energy_j"][key] += info["physical"]["energy"][key]
        summary["status"] = "natural_end"
    except BaseException as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        try:
            env.close()
        except BaseException as exc:
            summary["status"] = "error"
            summary["cleanup_error"] = f"{type(exc).__name__}: {exc}"
            if "error" not in summary:
                raise
        finally:
            write_json(run / "summary.json", summary)
    return run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    try:
        inputs = load_config(args.config)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    if args.validate_only:
        _, model, weather, output, episode, *_ = inputs
        print(json.dumps(dict(status="validated_without_simulation", model=str(model), weather=str(weather),
                              output=str(output), transitions=episode.steps), indent=2))
    else:
        print(run_episode(inputs))


if __name__ == "__main__":
    main()
