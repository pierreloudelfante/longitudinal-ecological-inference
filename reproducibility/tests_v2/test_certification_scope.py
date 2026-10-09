from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import pandas as pd
from PIL import Image

from reproducibility import certify_reproduction as c
from reproducibility.replication_scope import get_scope
from reproducibility.result_scope import project_result_contract


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "reproducibility/contract_v2"
MAIN = "02_TABLES_PRINCIPALES/test_estimates.csv"
DIAGNOSTIC = "05_DIAGNOSTICS/test_diagnostics.csv"
DENSITY = "03_FIGURES/densites_completes/krt_python/H0A/pre_2022_r1.png"
OUTSIDE_DENSITY = "03_FIGURES/densites_completes/krt_python/H0A/pre_1995_r1.png"


def png(colour):
    stream = io.BytesIO()
    Image.new("RGB", (24, 24), colour).save(stream, format="PNG")
    return stream.getvalue()


def csv(frame):
    return frame.to_csv(index=False).encode("utf-8")


class ScopeInventory(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads((CONTRACT / "expected_results_610.json").read_text(encoding="utf-8"))
        self.scope = get_scope("court")

    def test_full_contract_is_unchanged_and_not_mutated(self):
        self.assertEqual(project_result_contract(self.contract, get_scope("full")), self.contract)
        result = project_result_contract(self.contract, self.scope)
        self.assertEqual(len(self.contract["files"]), 610)
        self.assertEqual(len(result["files"]), 138)
        self.assertEqual(sum("/densites_completes/" in r["path"] for r in result["files"]), 26)
        self.assertEqual(sum("/atlas_densites_resumes/" in r["path"] for r in result["files"]), 22)

    def test_eight_final_schemas_and_count_contract_are_preserved(self):
        result = project_result_contract(self.contract, self.scope)
        original = {r["path"]: r for r in self.contract["files"]}
        tables = [r for r in result["files"] if "parquet" in r]
        self.assertEqual(len(tables), 8)
        self.assertEqual([r["parquet"]["rows"] for r in tables], [39, 39, 26000, 200, 364, 156, 39, 26000])
        for row in tables:
            self.assertEqual(row["parquet"]["columns"], original[row["path"]]["parquet"]["columns"])
        kept = {r["path"] for r in result["files"]}
        for row in self.contract["files"]:
            if "/densites_completes/" not in row["path"] and "/atlas_densites_resumes/" not in row["path"]:
                self.assertIn(row["path"], kept)

    def test_projection_fingerprints_include_all_direct_production_dependencies(self):
        required = {
            "code_longitudinal/build_full240_professor_release.py",
            "code_longitudinal/compare_python_r_ei_full_240.py",
            "code_longitudinal/spec_registry.py",
            "reproducibility/contract_v2/krt_replay_240.json",
            "reproducibility/reference/rxc_ineligible_audit.csv",
            "reproducibility/presentation/compose_slide_figures.ps1",
        }
        hashes = c.projection_code_hashes()
        self.assertTrue(required.issubset(hashes))
        self.assertEqual(set(hashes), set(c.PROJECTION_PRODUCTION_FILES))
        self.assertEqual(len(c.PROJECTION_PRODUCTION_FILES), len(set(c.PROJECTION_PRODUCTION_FILES)))
        for path in required:
            self.assertEqual(hashes[path], c.file_sha256(ROOT / path))


class SharedScopedCertification(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="certification scope ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reference = self.root / "reference.zip"
        self.candidate = self.root / "candidate.zip"
        self.contract = self.root / "contract.json"
        self.policy = self.root / "policy.json"
        self.policy.write_text(json.dumps({"default_numeric": {"atol": 0.0, "rtol": 0.0}}), encoding="utf-8")
        self.scope = get_scope("court")
        self.frame = pd.DataFrame({"election_id": ["pre_2022_r1", "pre_1995_r1"],
                                   "scenario_id": ["H0A", "H0A"], "estimate": [0.2, 0.3]})

    def archive(self, path, entries):
        with zipfile.ZipFile(path, "w") as out:
            for name, value in entries.items():
                out.writestr(name, value)

    def fixture(self, *, renders=False):
        reference = {MAIN: csv(self.frame), DIAGNOSTIC: csv(self.frame)}
        candidate = {MAIN: csv(self.frame.iloc[:1]), DIAGNOSTIC: csv(self.frame.iloc[:1])}
        if renders:
            reference.update({DENSITY: png("white"), OUTSIDE_DENSITY: png("white"),
                              "01_RAPPORT/RAPPORT_LONGITUDINAL.html": b"<html>2</html>"})
            candidate.update({DENSITY: png("white"), "01_RAPPORT/RAPPORT_LONGITUDINAL.html": b"<html>2</html>"})
        self.archive(self.reference, reference)
        self.archive(self.candidate, candidate)
        self.contract.write_text(json.dumps({
            "source_archive_sha256": c.file_sha256(self.reference),
            "files": [{"path": name, "sha256": hashlib.sha256(value).hexdigest()} for name, value in reference.items()],
        }), encoding="utf-8")
        return reference, candidate

    def compare(self, scope="court", comparison_reference_path=None):
        return c.compare_artifacts(self.reference, self.candidate, self.policy, self.contract, scope=scope,
                                   comparison_reference_path=comparison_reference_path)

    def projection_fixture(self, *, entries=None, change_receipt=None):
        # Synthetic independent oracle for unit tests, not an executed renderer.
        entries = dict(entries or {DENSITY: png("white"), "01_RAPPORT/RAPPORT_LONGITUDINAL.html": b"<html>2</html>"})
        receipt = {
            "schema_version": "scope_comparison_reference_v1", "generated_at_utc": c.utc_now(),
            "source_archive_sha256": c.file_sha256(self.reference), "scope": self.scope.as_dict(),
            "comparison_only": True, "derived_from_fixed_reference": True, "candidate_outputs_used": False,
            "renderer_code_sha256": c.file_sha256(ROOT / c.PROJECTION_RENDERER),
            "production_code_hashes": c.projection_code_hashes(),
            "files": [{"path": name, "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
                      for name, value in entries.items()],
        }
        if change_receipt:
            change_receipt(receipt)
        entries[c.COMPARISON_REFERENCE_RECEIPT] = json.dumps(receipt).encode("utf-8")
        projection = self.root / "comparison_only.zip"
        self.archive(projection, entries)
        return projection

    def test_same_comparison_entrypoint_scoped_success_is_not_full_certification(self):
        self.fixture()
        result = self.compare()
        self.assertTrue(result["semantic_tables_pass"])
        self.assertEqual(result["status"], "scoped_scientific_equivalence")
        self.assertFalse(result["exact_replay_pass"])
        self.assertFalse(result["full_campaign_certified"])
        self.assertEqual(result["verification_scope"], "selected_estimates_only")
        self.assertEqual(result["expected_file_count"], 2)

    def test_no_implicit_scope_from_worker_environment(self):
        reference, _ = self.fixture()
        self.archive(self.candidate, reference)
        with patch.dict("os.environ", {"LONGITUDINAL_REPLICATION_SCOPE": "court"}):
            result = self.compare(None)
        self.assertEqual(result["status"], "exact_replay")
        self.assertEqual(result["scope"]["name"], "full")
        self.assertTrue(result["full_campaign_certified"])

    def test_candidate_rows_are_never_filtered_even_if_file_hash_matches_full_reference(self):
        reference, _ = self.fixture()
        self.archive(self.candidate, reference)
        result = self.compare()
        self.assertFalse(result["semantic_tables_pass"])
        self.assertTrue(all("row_count_mismatch" in row["issues"] for row in result["table_results"]))

    def test_scoped_out_reference_files_are_still_hash_verified(self):
        reference, _ = self.fixture(renders=True)
        reference[OUTSIDE_DENSITY] = png("black")
        self.archive(self.reference, reference)
        result = self.compare()
        self.assertFalse(result["structure_pass"])
        self.assertIn(OUTSIDE_DENSITY, result["reference_contract_check"]["sha256_mismatches"])
        self.assertFalse(result["reference_contract_check"]["complete_reference_archive_sha256_matches"])

    def test_scoped_certification_requires_complete_reference_contract(self):
        self.fixture()
        with self.assertRaisesRegex(ValueError, "complete frozen reference contract"):
            c.compare_artifacts(self.reference, self.candidate, self.policy, None, scope=self.scope)

    def test_diagnostic_numeric_changes_remain_gating(self):
        _, candidate = self.fixture()
        changed = self.frame.iloc[:1].copy()
        changed.loc[0, "estimate"] += 0.01
        candidate[DIAGNOSTIC] = csv(changed)
        self.archive(self.candidate, candidate)
        result = self.compare()
        self.assertTrue(result["main_tables_pass"])
        self.assertFalse(result["diagnostic_tables_pass"])
        self.assertEqual(result["status"], "failed")

    def test_png_and_report_changes_use_same_blocking_policies(self):
        _, candidate = self.fixture(renders=True)
        candidate[DENSITY] = png("black")
        candidate["01_RAPPORT/RAPPORT_LONGITUDINAL.html"] = b"<html>999</html>"
        self.archive(self.candidate, candidate)
        result = self.compare()
        failures = {r["path"] for r in result["artifact_results"] if not r["pass"]}
        self.assertIn(DENSITY, failures)
        self.assertIn("01_RAPPORT/RAPPORT_LONGITUDINAL.html", failures)
        self.assertTrue(result["main_tables_pass"])
        self.assertFalse(result["scientific_equivalence_pass"])

    def test_identical_unprojected_renders_cannot_fake_valid_scoped_reference(self):
        self.fixture(renders=True)
        result = self.compare()
        self.assertTrue(result["semantic_tables_pass"])
        self.assertTrue(result["semantic_non_table_artifacts_pass"])
        self.assertFalse(result["reference_projection_complete"])
        self.assertEqual(len(result["reference_projection_gaps"]), 2)
        self.assertEqual(result["status"], "failed")

    def test_missing_global_report_is_not_removed_from_expected_inventory(self):
        _, candidate = self.fixture(renders=True)
        del candidate["01_RAPPORT/RAPPORT_LONGITUDINAL.html"]
        self.archive(self.candidate, candidate)
        result = self.compare()
        self.assertIn("01_RAPPORT/RAPPORT_LONGITUDINAL.html", result["missing_paths"])
        self.assertFalse(result["structure_pass"])

    def test_scope_projection_reads_reference_only_and_preserves_values(self):
        self.fixture()
        artifact = c.Artifact(self.reference)
        try:
            selected = c.project_reference_table(MAIN, self.frame, self.scope, artifact)
        finally:
            artifact.close()
        pd.testing.assert_frame_equal(selected, self.frame.iloc[:1])

    def test_valid_projection_uses_same_all_artifact_checks_and_never_claims_full(self):
        self.fixture(renders=True)
        projection = self.projection_fixture()
        result = self.compare(comparison_reference_path=projection)
        self.assertTrue(result["comparison_reference_check"]["pass"])
        self.assertEqual(result["comparison_reference_file_count"], 2)
        self.assertEqual(result["projected_render_hash_matches"], 2)
        self.assertEqual(result["status"], "scoped_scientific_equivalence")
        self.assertFalse(result["full_campaign_certified"])
        self.assertTrue(result["reference_projection_complete"])

    def test_historical_hash_match_does_not_skip_different_projected_reference(self):
        self.fixture(renders=True)
        projection = self.projection_fixture(entries={DENSITY: png("black"),
            "01_RAPPORT/RAPPORT_LONGITUDINAL.html": b"<html>999</html>"})
        result = self.compare(comparison_reference_path=projection)
        self.assertTrue(result["comparison_reference_check"]["pass"])
        self.assertFalse(result["semantic_non_table_artifacts_pass"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len([r for r in result["artifact_results"] if not r["pass"]]), 2)

    def test_projection_cannot_replace_a_scientific_table(self):
        self.fixture(renders=True)
        projection = self.projection_fixture(entries={DENSITY: png("white"),
            "01_RAPPORT/RAPPORT_LONGITUDINAL.html": b"<html>2</html>", MAIN: csv(self.frame.iloc[:1])})
        result = self.compare(comparison_reference_path=projection)
        self.assertFalse(result["comparison_reference_check"]["pass"])
        self.assertIn("comparison_reference_inventory_mismatch", result["comparison_reference_check"]["issues"])
        self.assertEqual(result["comparison_reference_file_count"], 0)

    def test_projection_provenance_claims_and_code_hashes_are_verified(self):
        self.fixture(renders=True)
        changes = {
            "source_archive_sha256": "0" * 64, "scope": get_scope("full").as_dict(),
            "comparison_only": False, "derived_from_fixed_reference": False,
            "candidate_outputs_used": True, "renderer_code_sha256": "0" * 64,
            "production_code_hashes": {},
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                projection = self.projection_fixture(change_receipt=lambda r: r.update({field: value}))
                result = self.compare(comparison_reference_path=projection)
                self.assertFalse(result["comparison_reference_check"]["pass"])
                self.assertEqual(result["status"], "failed")

    def test_projected_file_tampering_is_detected(self):
        self.fixture(renders=True)
        projection = self.projection_fixture(change_receipt=lambda r: r["files"][0].update({"sha256": "0" * 64}))
        result = self.compare(comparison_reference_path=projection)
        self.assertFalse(result["comparison_reference_check"]["pass"])
        self.assertTrue(any("size_or_hash_mismatch" in x for x in result["comparison_reference_check"]["issues"]))

    def test_valid_projection_does_not_hide_wrong_candidate_estimates(self):
        _, candidate = self.fixture(renders=True)
        changed = self.frame.iloc[:1].copy()
        changed.loc[0, "estimate"] = 0.9
        candidate[MAIN] = csv(changed)
        self.archive(self.candidate, candidate)
        projection = self.projection_fixture()
        result = self.compare(comparison_reference_path=projection)
        self.assertTrue(result["comparison_reference_check"]["pass"])
        self.assertFalse(result["main_tables_pass"])
        self.assertEqual(result["status"], "failed")

    def test_full_certification_rejects_any_projection(self):
        self.fixture(renders=True)
        with self.assertRaisesRegex(ValueError, "fixed whole reference"):
            self.compare(scope="full", comparison_reference_path=self.root / "unused.zip")

    def test_density_bandwidth_can_be_projected_but_source_counts_cannot_change(self):
        reference, candidate = self.fixture(renders=True)
        catalogue = self.frame.drop(columns="estimate").assign(
            method="krt_python", total_rows=2000, bandwidth_b1=0.03, bandwidth_b2=0.04,
        )
        path = c.PROJECTED_DENSITY_CATALOGUE
        reference[path] = csv(catalogue)
        scoped_catalogue = catalogue.iloc[:1].copy()
        scoped_catalogue["bandwidth_b1"] = 0.06
        candidate[path] = csv(scoped_catalogue)
        self.archive(self.reference, reference)
        self.archive(self.candidate, candidate)
        self.contract.write_text(json.dumps({
            "source_archive_sha256": c.file_sha256(self.reference),
            "files": [{"path": name, "sha256": hashlib.sha256(value).hexdigest()} for name, value in reference.items()],
        }), encoding="utf-8")
        projected = {DENSITY: png("white"), "01_RAPPORT/RAPPORT_LONGITUDINAL.html": b"<html>2</html>",
                     path: csv(scoped_catalogue)}
        projection = self.projection_fixture(entries=projected)
        result = self.compare(comparison_reference_path=projection)
        self.assertTrue(result["comparison_reference_check"]["catalogue_source_metadata_check"]["pass"])
        self.assertEqual(result["status"], "scoped_scientific_equivalence")
        scoped_catalogue["total_rows"] = 100
        projected[path] = csv(scoped_catalogue)
        projection = self.projection_fixture(entries=projected)
        result = self.compare(comparison_reference_path=projection)
        self.assertIn("comparison_reference_catalogue_source_metadata_mismatch",
                      result["comparison_reference_check"]["issues"])
        self.assertEqual(result["status"], "failed")

    def test_report_qa_requires_exact_full_or_scoped_contract_and_scope(self):
        _, candidate = self.fixture()
        candidate["01_RAPPORT/RAPPORT_LONGITUDINAL.html"] = b"<html>Report</html>"
        candidate["01_RAPPORT/RAPPORT_LONGITUDINAL.pdf"] = b"%PDF-1.4\n/Type /Page\n%%EOF"
        self.archive(self.candidate, candidate)
        reference_artifact, candidate_artifact = c.Artifact(self.reference), c.Artifact(self.candidate)
        try:
            for scope in (get_scope("full"), self.scope):
                with self.subTest(scope=scope.name):
                    receipt = {
                        "schema_version": "replication_report_qa_v2", "created_at_utc": c.utc_now(),
                        "pdf_origin": "rendered_from_newly_generated_html_not_copied_from_reference",
                        "visual_inspection_performed": False,
                        "numeric_equality_to_historical_results": "not_certified",
                        "reference_statistics_in_static_narrative": "historical_context_not_new_validation",
                        "coverage_contract": "expected_results_610.json" if scope.is_full
                        else "projection of expected_results_610.json for declared scope",
                    }
                    if not scope.is_full:
                        receipt["scope"] = scope.as_dict()

                    def validate(value):
                        return c.validate_generated_provenance(
                            "06_DOCUMENTATION/REPORT_QA.json", json.dumps(value).encode("utf-8"),
                            reference_artifact, candidate_artifact, None, scope,
                        )

                    self.assertTrue(validate(receipt)["pass"])
                    wrong_label = dict(receipt, coverage_contract=(
                        "projection of expected_results_610.json for declared scope" if scope.is_full
                        else "expected_results_610.json"))
                    self.assertIn("invalid_report_qa_claim:coverage_contract", validate(wrong_label)["issues"])
                    wrong_scope = dict(receipt, scope=(self.scope if scope.is_full else get_scope("full")).as_dict())
                    self.assertFalse(validate(wrong_scope)["pass"])
                    if not scope.is_full:
                        no_scope = dict(receipt)
                        del no_scope["scope"]
                        self.assertIn("missing_or_incorrect_run_receipt_scope", validate(no_scope)["issues"])
        finally:
            reference_artifact.close()
            candidate_artifact.close()


if __name__ == "__main__":
    unittest.main()
