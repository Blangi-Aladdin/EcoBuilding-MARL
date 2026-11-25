"""Run deterministic validation scenarios with the configured EnergyPlus model."""

import argparse
from datetime import date, timedelta
from itertools import product
import json
from pathlib import Path
from random import Random

from ecobuilding.occupancy_profiles import DETERMINISTIC, STEPS, generate
from ecobuilding.simulation import Scenario, SimulationRunner

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/validation/lot1.json"
COMBINATIONS = tuple(product(range(3), repeat=3))
TRANSITIONS = ((0, 0, 0), (2, 0, 1), (1, 0, 2), (0, 2, 2), (0, 1, 0), (2, 2, 2), (0, 0, 0))


def action_plan(mode, length, level, seed):
    rng = Random(seed)
    off = (0, 0, 0)
    actions = []
    for slot in range(length):
        if mode == "matrix":
            action = COMBINATIONS[(slot - 20) // 2] if 20 <= slot < 74 else off
        elif mode == "long":
            action = actions[-1] if slot and slot % 19 in (1, 2, 3) else tuple(rng.randrange(3) for _ in off)
        elif mode == "occupancy":
            block = (slot + 2) // 4
            action = (block % 3, (block + 1) % 3, (block + 2) % 3)
        elif mode == "leave-active":
            action = (2, 2, 2) if slot >= 92 else off
        elif mode == "winter-cooling":
            action = (2, level if slot >= 32 else 0, 0)
        elif mode == "release":
            action = (2, 2, 2) if 44 <= slot < 60 else off if slot < 60 else None
        elif mode == "transitions":
            action = TRANSITIONS[(slot - 32) // 2] if 32 <= slot < 46 else off
        elif mode == "native":
            action = None
        else:
            raise ValueError(f"Unknown validation mode {mode}")
        actions.append(action)
    return tuple(actions)


def build_case(name, config):
    settings = dict(config["cases"][name])
    month, day = settings.pop("first")
    days = settings.pop("days", 1)
    first = date(2001, month, day)
    start = first - timedelta(days=config["history_days"])
    end = first + timedelta(days=days - 1)
    mode = settings.pop("mode", "native")
    fixture = settings.pop("profile", None)
    actions = action_plan(mode, days * STEPS, settings.pop("level", 0), config["action_seed"])
    profile = DETERMINISTIC[fixture] if fixture else None
    if mode == "long":
        profile = generate(config["occupancy_seed"])
    if mode == "leave-active":
        profile = (2,) * STEPS
    return Scenario(name, (start.month, start.day, end.month, end.day), (month, day),
                    actions, tuple(profile) if profile is not None else None, **settings)


def run_cases(config, output, names):
    from pyenergyplus.api import EnergyPlusAPI

    runner = SimulationRunner(EnergyPlusAPI(), cooling_setpoint_c=config["cooling_setpoint_c"],
                              step_minutes=config["step_minutes"])
    for name in names:
        print(f"Running {name}", flush=True)
        runner.run(ROOT / config["model"], ROOT / config["weather"], output / name, build_case(name, config))


def main():
    from checks import analyze

    config = json.loads(CONFIG.read_bytes())
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--case", choices=config["cases"], action="append")
    group.add_argument("--weeks", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / config["output"])
    args = parser.parse_args()
    names = args.case or [name for name in config["cases"] if not args.weeks or name.startswith("long-")]
    run_cases(config, args.output.resolve(), names)
    analyze(args.output.resolve(), ROOT / config["model"], ROOT / config["weather"], names)


if __name__ == "__main__":
    main()
