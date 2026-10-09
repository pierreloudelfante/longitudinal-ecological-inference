from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from code_longitudinal import run_r_ei_all_2x2 as runner


class HistoricalRSeeds(unittest.TestCase):
    def contracts(self):
        directory = runner.R_REPLAY_CONTRACT.parent
        return tuple(json.loads((directory / name).read_text(encoding="utf-8")) for name in
                     ("r_replay_240.json", "expected_results_610.json", "krt_replay_240.json"))

    def test_every_dispatch_seed_matches_pinned_manifest(self):
        manifest, _, _ = self.contracts()
        self.assertEqual(len(manifest["entries"]), 240)
        for row in manifest["entries"]:
            self.assertEqual(runner._stable_seed(row["election_id"], row["scenario_id"]), row["seed"])
        self.assertEqual(runner._stable_seed("pre_2022_r1", "H0A"), 20260827)

    def test_reduced_counts_do_not_change_or_shrink_historical_seed_contract(self):
        manifest, _, _ = self.contracts()
        selected = [row for row in manifest["entries"] if row["election_id"] == "pre_2022_r1"]
        self.assertEqual(len(selected), 10)
        with patch.object(runner, "EXPECTED_ELECTIONS", {row["scenario_id"]: 1 for row in selected}):
            self.assertEqual(len(runner._reference_seeds()), 240)
            for row in selected:
                self.assertEqual(runner._stable_seed(row["election_id"], row["scenario_id"]), row["seed"])

    def test_missing_duplicate_invalid_or_unpinned_seeds_fail(self):
        manifest, reference, krt = self.contracts()
        for mutation in ("missing", "duplicate", "bad_seed", "wrong_reference", "wrong_table"):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(manifest)
                if mutation == "missing": changed["entries"].pop()
                if mutation == "duplicate": changed["entries"][-1] = dict(changed["entries"][0])
                if mutation == "bad_seed": changed["entries"][0]["seed"] = -1
                if mutation == "wrong_reference": changed["source_archive_sha256"] = "0" * 64
                if mutation == "wrong_table": changed["source_table_sha256"] = "0" * 64
                with self.assertRaises(ValueError):
                    runner._validate_reference_seeds(changed, reference, krt)

    def test_unknown_pair_has_no_derived_seed_fallback(self):
        with self.assertRaises(ValueError):
            runner._stable_seed("pre_1900_r1", "H0A")

    def test_previous_success_with_wrong_seed_is_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_csv = root / "pre_2022_r1__H0A__panel__n2000.csv"
            input_csv.write_text("test fixture", encoding="utf-8")
            manifest_path = root / "manifest_r.json"
            required_outputs = ("commune_latent_summaries_r.csv", "aggregate_summaries_r.csv")
            for name in required_outputs:
                (root / name).write_text("fixture_value\n1\n", encoding="utf-8")
            manifest = {"status": "success", "n_communes": 2000,
                        "election_id": "pre_2022_r1", "scenario_id": "H0A",
                        "seed": 1287497612, "input_sha256": runner.file_sha256(input_csv),
                        "mathematical_identity_with_python_model": False}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertFalse(runner._manifest_is_reusable(manifest_path, input_csv, "H0A"))
            manifest["seed"] = 20260827
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertTrue(runner._manifest_is_reusable(manifest_path, input_csv, "H0A"))
            for name in required_outputs:
                with self.subTest(missing_or_empty_output=name):
                    output = root / name
                    output.unlink()
                    self.assertFalse(runner._manifest_is_reusable(manifest_path, input_csv, "H0A"))
                    output.touch()
                    self.assertFalse(runner._manifest_is_reusable(manifest_path, input_csv, "H0A"))
                    output.write_text("fixture_value\n1\n", encoding="utf-8")
                    self.assertTrue(runner._manifest_is_reusable(manifest_path, input_csv, "H0A"))


if __name__ == "__main__":
    unittest.main()
