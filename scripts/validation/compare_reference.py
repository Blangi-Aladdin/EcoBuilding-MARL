"""Compare replay exports against optional local references from 36.5.1 and 36.6."""

import argparse
from collections import defaultdict
import csv
import json
from math import isclose
from pathlib import Path


def observations(folder):
    return [json.loads(line) for line in (folder / "observations.jsonl").read_text().splitlines()]


def compare(actual, expected, path, maxima):
    category = path.split(".")[0]
    if type(actual) in (int, float) and type(expected) in (int, float):
        assert isclose(actual, expected, abs_tol=1e-6, rel_tol=1e-9), (path, actual, expected)
        maxima[category] = max(maxima[category], abs(actual - expected))
    elif isinstance(actual, dict) and isinstance(expected, dict):
        assert actual.keys() == expected.keys(), path
        for key in actual:
            compare(actual[key], expected[key], f"{path}.{key}" if path else key, maxima)
    elif isinstance(actual, list) and isinstance(expected, list):
        assert len(actual) == len(expected), path
        for a, b in zip(actual, expected):
            compare(a, b, path, maxima)
    else:
        assert type(actual) is type(expected) and actual == expected, (path, actual, expected)
        maxima[category] = max(maxima[category], 0)


def comparison_3651(replay, prior):
    mappings = {
        "energy.heating_j": "heat_j", "energy.cooling_dx_j": "dx_j",
        "energy.ventilation_j": "vent_j", "energy.total_j": "facility_j",
        "indoor.indoor_c": "indoor_c", "occupancy.people": "occupants",
        "diagnostics.substep_means.indoor_rh_pct": "rh_pct",
        "diagnostics.substep_means.co2_ppm": "co2_ppm",
    }
    assert len(replay) == len(prior)
    maxima = defaultdict(float)
    for obs, row in zip(replay, prior):
        for path, column in mappings.items():
            value = obs
            for key in path.split("."):
                value = value[key]
            compare(value, float(row[column]), path, maxima)
    return maxima


def main():
    if not __debug__:
        raise RuntimeError("Run comparison without Python optimization")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay", type=Path)
    parser.add_argument("reference_366", type=Path)
    parser.add_argument("reference_3651", type=Path)
    args = parser.parse_args()
    mapping = {"matrix-winter": "matrix-winter-after", "matrix-summer": "matrix-summer-after",
               **{k: k for k in ("long-winter", "long-summer", "long-autumn", "winter-cooling-1", "winter-cooling-2")}}
    rows = []
    for folder in sorted(args.replay.iterdir()):
        if not (folder / "observations.jsonl").exists() or not folder.is_dir():
            continue
        replay = observations(folder)
        reference = args.reference_366 / folder.name
        if reference.exists():
            previous = observations(reference)
            assert len(replay) == len(previous)
            maxima = defaultdict(float)
            for obs, prior in zip(replay, previous):
                compare(obs, prior, "", maxima)
            assert (folder / "mesures-sous-pas.csv").read_bytes() == (reference / "mesures-sous-pas.csv").read_bytes()
            rows.extend(("36.6", folder.name, len(replay), k, v) for k, v in maxima.items())
        elif folder.name != "transitions":
            raise FileNotFoundError(reference)
        if folder.name in mapping:
            with (args.reference_3651 / mapping[folder.name] / "mesures-15min.csv").open(newline="") as stream:
                maxima = comparison_3651(replay, list(csv.DictReader(stream)))
            rows.extend(("36.5.1", folder.name, len(replay), k, v) for k, v in maxima.items())
    with (args.replay / "non-regression.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("reference", "case", "steps", "category", "max_absolute_delta"))
        writer.writerows(rows)
    print(f"{len({r[:2] for r in rows})} scenario/reference pairs, largest absolute delta {max(r[-1] for r in rows):.12g}")


if __name__ == "__main__":
    main()
