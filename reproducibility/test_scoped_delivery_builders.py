"""Focused scope checks: no estimations and no reference results as candidate inputs."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import pandas as pd

from reproducibility.replication_scope import get_scope
from code_longitudinal import build_professor_release_assets as assets
from code_longitudinal import build_density_report_atlas as atlas
from reproducibility.certify_reproduction import compare_numeric_text, compare_table


class ScopedDeliveryBuilders(unittest.TestCase):
    def test_frozen_full_expectations_are_unchanged(self):
        with patch.dict(os.environ, LONGITUDINAL_REPLICATION_SCOPE="full"):
            entries = assets.scope_reference_entries()
            self.assertEqual(len(entries), 240)
            self.assertEqual({s: sum(e["reference_mcmc_status"] == s for e in entries) for s in ("pass", "caveat", "fail")}, {"pass": 41, "caveat": 88, "fail": 111})
            self.assertEqual(assets.scope_text("240 couples ; 95 % ; selection_240.csv"), "240 couples ; 95 % ; selection_240.csv")
            self.assertEqual(assets.scope_text("145 PyMC ; 95 NumPyro"), "93 PyMC ; 147 NumPyro")

    def test_scoped_expectations_use_frozen_entries_and_exact_pair_set(self):
        with patch.dict(os.environ, LONGITUDINAL_REPLICATION_SCOPE="court"):
            scope = get_scope()
            entries = assets.scope_reference_entries()
            self.assertEqual({(e["election_id"], e["scenario_id"]) for e in entries}, scope.pairs)
            frame = pd.DataFrame(sorted(scope.pairs), columns=["election_id", "scenario_id"])
            assets.assert_pair_scope(frame)
            with self.assertRaises(AssertionError):
                assets.assert_pair_scope(frame.iloc[1:])
            with self.assertRaises(AssertionError):
                assets.assert_pair_scope(pd.concat([frame, pd.DataFrame([("leg_1962_r1", "H0A")], columns=frame.columns)]))

    def test_coverage_prose_does_not_rewrite_paths_or_scientific_thresholds(self):
        with patch.dict(os.environ, LONGITUDINAL_REPLICATION_SCOPE="court"):
            scope = get_scope()
            text = assets.scope_text("240 couples ; 480 figures ; 292 NLS ; 960 ajustements ; 95 % ; 2000 draws ; selection_240.csv ; compare_python_r_ei_full_240")
            self.assertIn(f"{scope.pair_count} couples", text)
            self.assertIn(f"{scope.density_count} figures", text)
            for unchanged in ("95 %", "2000 draws", "selection_240.csv", "compare_python_r_ei_full_240"):
                self.assertIn(unchanged, text)

    def test_atlas_labels_scope_and_clears_empty_series(self):
        with patch.dict(os.environ, LONGITUDINAL_REPLICATION_SCOPE="court"), tempfile.TemporaryDirectory() as temporary:
            scope = get_scope()
            rows = [{"method": method, "scenario_id": s, "election_type": "legislative" if e.startswith("leg_") else "presidential", "election_id": e, "year": int(e.split("_")[1]), "round": 1, "finite_both": 2000, "total_rows": 2000, "warning": "", "report_png": f"03_FIGURES/{method}/{s}/{e}.png"} for method in atlas.METHOD_LABELS for e, s in sorted(scope.pairs)]
            output = Path(temporary)
            atlas.build_full_size_reader(pd.DataFrame(rows), output)
            text = (output / "01_RAPPORT/ANNEXE_ATLAS_DENSITES.html").read_text(encoding="utf-8")
            self.assertIn(f"soit {scope.density_count} PNG", text)
            self.assertNotIn("couvrent toutes les législatives", text)
            self.assertIn('document.getElementById("figures").replaceChildren()', text)
            self.assertIn("if(!pairs.length)return", text)
            self.assertIn("Hors périmètre", text)


@unittest.skipUnless(os.environ.get("LONGITUDINAL_TEST_REFERENCE_ZIP"), "explicit comparison-only reference fixture not supplied")
class HistoricalProducerReferenceFixtures(unittest.TestCase):
    """Development comparison, NEVER a reproduction run or candidate estimation."""

    def setUp(self):
        self.reference = zipfile.ZipFile(os.environ["LONGITUDINAL_TEST_REFERENCE_ZIP"])
        self.addCleanup(self.reference.close)
        self.policy = json.loads((assets.ROOT / "reproducibility/contract_v2/certification_policy_v1.json").read_text())
        self.scenarios = pd.read_csv(io.BytesIO(self.reference.read("06_DOCUMENTATION/MODEL_SCENARIOS.csv")))

    def test_historical_three_markdown_outputs_strictly_match(self):
        krt = pd.read_csv(io.BytesIO(self.reference.read("05_DIAGNOSTICS/diagnostics_KRT_resume.csv")))
        nls = pd.read_csv(io.BytesIO(self.reference.read("05_DIAGNOSTICS/diagnostics_NLS_resume.csv")))
        stats = {"krt_mcmc": krt["mcmc_status"].value_counts().to_dict(), "nls_diagnostics": nls["diagnostic_status"].value_counts().to_dict()}
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, LONGITUDINAL_REPLICATION_SCOPE="full"):
            destination = Path(temporary)
            with patch.object(assets, "LIGHT", destination), patch.object(assets, "DOC_DIR", destination / "06_DOCUMENTATION"), patch.object(assets, "report_statistics", return_value=stats), patch.object(pd, "read_csv", return_value=self.scenarios):
                # An empty row inventory avoids a large table fixture. It is not
                # asserted to reproduce the dictionary, only these three texts.
                assets.build_documentation({})
            for name in ("00_README_PROFESSEUR.md", "06_DOCUMENTATION/REPRODUCE.md", "06_DOCUMENTATION/CHANGELOG.md"):
                result = compare_numeric_text(name, self.reference.read(name), (destination / name).read_bytes(), "md", self.policy)
                self.assertTrue(result["pass"], result)

    def test_historical_panel_csv_shapes_and_values(self):
        panel_path = assets.ROOT / "panel/longitudinal_2000_v1.parquet"
        if not panel_path.is_file():
            self.skipTest("the raw-derived master panel is not available for this development fixture")
        frames = {
            assets.PANEL: pd.read_parquet(panel_path),
            assets.KRT_AGG: pd.read_parquet(io.BytesIO(self.reference.read("02_TABLES_PRINCIPALES/longitudinal_krt_aggregate.parquet"))),
            assets.R_AGG: pd.read_parquet(io.BytesIO(self.reference.read("02_TABLES_PRINCIPALES/longitudinal_r_ei_aggregate.parquet"))),
            assets.NLS: pd.read_parquet(io.BytesIO(self.reference.read("02_TABLES_PRINCIPALES/longitudinal_nls.parquet"))),
        }
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, LONGITUDINAL_REPLICATION_SCOPE="full"):
            destination = Path(temporary)
            with patch.object(assets, "PANEL_DIR", destination), patch.object(pd, "read_parquet", side_effect=lambda path: frames[path].copy()), patch.object(pd, "read_csv", return_value=self.scenarios):
                assets.build_panel_and_harmonisation()
            for filename, shape in (("balance_checks_summary.csv", (8, 9)), ("HARMONISATION_POLITIQUE.csv", (10, 7)), ("coverage_by_election.csv", (26, 11))):
                name = "04_PANEL_ET_HARMONISATION/" + filename
                actual = pd.read_csv(destination / filename)
                self.assertEqual(actual.shape, shape)
                result = compare_table(name, self.reference.read(name), (destination / filename).read_bytes(), self.policy)
                self.assertTrue(result["pass"], result)


if __name__ == "__main__":
    unittest.main()
