"""Exercise all configured scenarios in a single EnergyPlus API process."""

import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/validation"))
from checks import analyze
from run import CONFIG, ROOT, run_cases


class EnergyPlusIntegration(unittest.TestCase):
    def test_full_replay(self):
        config = json.loads(CONFIG.read_bytes())
        with TemporaryDirectory() as temporary:
            output = Path(os.environ.get("ECOBUILDING_VALIDATION_OUTPUT", temporary))
            run_cases(config, output, config["cases"])
            analyze(output, ROOT / config["model"], ROOT / config["weather"], config["cases"])
