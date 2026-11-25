"""Archive-independent regression tests for the qualification comparator."""

import csv
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

DEFAULT_TOOL = Path(__file__).resolve().parents[2] / "scripts/validation/_sinergym_compare.py"
TOOL = Path(os.environ.get("COMPARATOR_UNDER_TEST", DEFAULT_TOOL))
MODULE = importlib.util.spec_from_file_location("qualification_comparator", TOOL)
comparator = importlib.util.module_from_spec(MODULE)
MODULE.loader.exec_module(comparator)


class ComparatorRegression(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.direct = self.root / "reproductions-directes/case"
        self.sim = self.root / "sinergym/case"
        self.native = self.root / "sinergym/episodes/episode/output"
        for path in (self.direct, self.sim, self.native, self.root / "audit", self.root / "comparaisons"):
            path.mkdir(parents=True)
        comparator.ROOT = comparator.OUT = self.root
        comparator.history = self.direct.parent
        comparator.ABS, comparator.REL = 1e-6, 1e-9

        self.hvac_direct = self.hvac()
        self.hvac_sim = self.hvac()
        self.dx_direct = self.dx()
        self.dx_sim = self.dx()
        self.sim_temperature = 20.0

    @staticmethod
    def hvac():
        return [dict(step=step, seconds=450, end_seconds=end, dx_speed_level=0)
                for step in (1, 2) for end in (450, 900)]

    @staticmethod
    def dx():
        # Predictor callbacks may repeat indistinguishable records before a finalized report.
        return [dict(step=step, load_w=0.0, speed_override=0) for step in (1, 1, 2, 2)]

    @staticmethod
    def csv(path, rows):
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def jsonl(path, rows):
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def fixture(self):
        energy = dict(heating_j=0.0, cooling_dx_j=0.0, ventilation_j=0.0, total_j=0.0)
        equipment = dict(heat_electric_w=0.0, dx_total_w=0.0, dx_electric_w=0.0,
                         vent_m3_h=0.0, heating_active=False, dx_active=False)
        readings = dict(indoor_c=20.0, indoor_rh_pct=50.0, co2_ppm=420.0, people=0)
        times = ("00:00:00", "00:15:00", "00:30:00", "00:45:00")
        for folder, temperature in ((self.direct, 20.0), (self.sim, self.sim_temperature)):
            zones = [dict(time=dict(start=f"2014-01-27T{times[i]}", end=f"2014-01-27T{times[i+1]}"),
                          indoor=dict(indoor_c=temperature, indoor_rh_pct=50.0, co2_ppm=420.0),
                          occupancy=dict(people=0, presence=0), actions={}, equipment=equipment,
                          energy=energy) for i in (1, 2)]
            self.jsonl(folder / "observations.jsonl", zones)
        init = dict(time=dict(start="2014-01-27T00:00:00", end="2014-01-27T00:15:00"),
                    diagnostics=dict(api_zone_end=readings, substep_means=readings), energy=energy)
        (self.sim / "observation-initiale.json").write_text(json.dumps(dict(info=dict(physical=init))))
        (self.sim / "execution.json").write_text(json.dumps(dict(output_path=str(self.native))))
        for folder in (self.direct, self.native.parent):
            (folder / "office_1zone.epJSON").write_text("{}\n")
        (self.native / "eplusout.end").write_text("0 Warning; 0 Severe Errors\n")
        native = [dict(zip(("Date/Time", comparator.METER, *(
            f"OFFICE:{name} [](TimeStep)" for name in ("Zone Mean Air Temperature",
                "Zone Air Relative Humidity", "Zone Air CO2 Concentration", "Zone People Occupant Count"))),
            (f"01/27 {end}", 0, 20, 50, 420, 0))) for end in times[1:]]
        for folder in (self.direct, self.native):
            self.csv(folder / "eplusout.csv", native)
        self.csv(self.direct / "mesures-sous-pas.csv", self.hvac_direct)
        self.jsonl(self.sim / "mesures-sous-pas.jsonl", self.hvac_sim)
        self.csv(self.direct / "chronologie.csv", [dict(phase="after_predictor", **r) for r in self.dx_direct])
        self.jsonl(self.sim / "predicteur.jsonl", self.dx_sim)
        (self.root / "audit/inventaire-36.7.csv").write_text("case,category\ncase,A\n")
        (self.root / "audit/tolerances.json").write_text('{"abs_tol":1e-6,"rel_tol":1e-9}')

    def compare(self, status, field=None):
        self.fixture()
        report, _, errors, _, _ = comparator.compare_case("case", plot=False)
        self.assertEqual(report["status"], status)
        if field:
            self.assertIn(field, {error["field"] for error in errors})
        else:
            self.assertFalse(errors)

    def test_R01_exacte(self):
        self.compare("exact")

    def test_R02_hors_plage_sinergym(self):
        self.hvac_sim.append(dict(self.hvac_sim[-1], step=3))
        self.compare("divergence", "hvac.step_range.sinergym")

    def test_R03_hors_plage_direct(self):
        self.hvac_direct.append(dict(self.hvac_direct[-1], step=3))
        self.compare("divergence", "hvac.step_range.direct")

    def test_R04_sous_pas_supplementaire(self):
        self.hvac_sim.append(dict(self.hvac_sim[-1], end_seconds=901))
        self.compare("divergence", "hvac.substep_count")

    def test_R05_sous_pas_manquant(self):
        self.hvac_sim.pop()
        self.compare("divergence", "hvac.substep_count")

    def test_R06_repartition_compensee(self):
        self.hvac_sim[1]["step"] = 2
        self.compare("divergence", "hvac.substep_count")

    def test_R07_hors_plage_compense(self):
        self.hvac_sim[-1]["step"] = 3
        self.compare("divergence", "hvac.step_range.sinergym")

    def test_R08_hors_plage_identique(self):
        for rows in (self.hvac_direct, self.hvac_sim):
            rows.append(dict(rows[-1], step=3))
        self.compare("divergence", "hvac.step_range.sinergym")

    def test_R09_doublon_invalide(self):
        for rows in (self.hvac_direct, self.hvac_sim):
            rows[1] = rows[0].copy()
        self.compare("divergence", "hvac.duplicate.sinergym")

    def test_R10_repetitions_hvac_legitimes(self):
        self.compare("exact")

    def test_R11_ordre_hvac_inverse(self):
        self.hvac_sim[0], self.hvac_sim[1] = self.hvac_sim[1], self.hvac_sim[0]
        self.compare("divergence", "hvac.end_seconds")

    def test_R12_predicteur_hors_plage(self):
        for rows in (self.dx_direct, self.dx_sim):
            rows.append(dict(rows[-1], step=3))
        self.compare("divergence", "predictor.step_range.sinergym")

    def test_R13_predicteur_manquant(self):
        self.dx_sim.pop()
        self.compare("divergence", "predictor.count")

    def test_R14_repartition_predicteur(self):
        self.dx_sim[1]["step"] = 2
        self.compare("divergence", "predictor.step")

    def test_R15_repetitions_predicteur_legitimes(self):
        self.compare("exact")

    def test_R16_ecart_admissible(self):
        self.sim_temperature += 0.5e-6
        self.compare("equivalent")

    def test_R17_ecart_non_admissible(self):
        self.sim_temperature += 1e-4
        self.compare("divergence", "zone.indoor.indoor_c")

    def test_R18_propagation_du_verdict(self):
        self.hvac_sim.append(dict(self.hvac_sim[-1], step=3))
        self.fixture()
        result = subprocess.run([sys.executable, str(TOOL), str(self.root), str(self.root)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("case divergence", result.stdout)
