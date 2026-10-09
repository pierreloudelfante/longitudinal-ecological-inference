from __future__ import annotations

import io
import hashlib
import base64
import gzip
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import warnings

import pandas as pd
from PIL import Image

from reproducibility import certify_reproduction as c
from reproducibility import replication_complete as r


class CertificationPolicy(unittest.TestCase):
    def policy(self) -> dict:
        return json.loads((r.CONTRACT / "certification_policy_v1.json").read_text(encoding="utf-8"))

    def parquet_bytes(self, frame: pd.DataFrame) -> bytes:
        payload = io.BytesIO()
        frame.to_parquet(payload, index=False)
        return payload.getvalue()

    def test_deterministic_nls_change_is_rejected(self):
        path = "02_TABLES_PRINCIPALES/longitudinal_nls.parquet"
        base = pd.DataFrame({
            "election_id": ["leg_2022_r1"], "scenario_id": ["H0A"],
            "model_key": ["nls"], "estimand_type": ["group_contrast"],
            "run_id": ["20260810T090000Z__b2de0cecfcfd"],
            "social_group": ["group_1"], "vote_category": ["vote"],
            "estimate": [0.2],
        })
        changed = base.copy(); changed.loc[0, "estimate"] += 1e-4
        result = c.compare_table(path, self.parquet_bytes(base), self.parquet_bytes(changed), self.policy())
        self.assertFalse(result["pass"])

    def test_small_mcmc_change_passes_scientific_policy_but_not_exact_hash(self):
        path = "02_TABLES_PRINCIPALES/longitudinal_krt_aggregate.parquet"
        base = pd.DataFrame({
            "election_id": ["leg_2022_r1"], "scenario_id": ["H0A"],
            "model_key": ["krt"], "estimand": ["contrast"], "run_id": ["20260810T105531Z__73ea044afa93"],
            "mean": [0.2], "median": [0.2], "q025": [0.1], "q975": [0.3],
            "legacy_mean": [0.2], "mean_difference_from_legacy": [0.0],
        })
        changed = base.copy(); changed.loc[0, ["mean", "median"]] += 0.001
        result = c.compare_table(path, self.parquet_bytes(base), self.parquet_bytes(changed), self.policy())
        self.assertTrue(result["pass"])
        self.assertNotEqual(self.parquet_bytes(base), self.parquet_bytes(changed))

    def test_sign_change_is_rejected(self):
        path = "02_TABLES_PRINCIPALES/longitudinal_krt_aggregate.parquet"
        base = pd.DataFrame({
            "election_id": ["leg_2022_r1"], "scenario_id": ["H0A"],
            "model_key": ["krt"], "estimand": ["contrast"], "run_id": ["20260810T105531Z__73ea044afa93"],
            "mean": [0.2], "median": [0.2], "q025": [0.1], "q975": [0.3],
            "legacy_mean": [0.2], "mean_difference_from_legacy": [0.0],
        })
        changed = base.copy(); changed.loc[0, ["mean", "median"]] = -0.2
        result = c.compare_table(path, self.parquet_bytes(base), self.parquet_bytes(changed), self.policy())
        self.assertFalse(result["pass"])

    def test_interval_classification_change_is_rejected(self):
        path = "02_TABLES_PRINCIPALES/longitudinal_krt_aggregate.parquet"
        base = pd.DataFrame({
            "election_id": ["leg_2022_r1"], "scenario_id": ["H0A"],
            "model_key": ["krt"], "estimand": ["contrast"], "run_id": ["20260810T105531Z__73ea044afa93"],
            "mean": [0.05], "median": [0.05], "q025": [0.01], "q975": [0.09],
            "legacy_mean": [0.05], "mean_difference_from_legacy": [0.0],
        })
        changed = base.copy(); changed.loc[0, "q025"] = -0.001
        result = c.compare_table(path, self.parquet_bytes(base), self.parquet_bytes(changed), self.policy())
        self.assertFalse(result["pass"])
        self.assertEqual(result["interval_classification_results"][0]["classification_mismatch_count"], 1)

    def test_visually_different_png_is_rejected(self):
        def payload(colour):
            image = Image.new("RGB", (32, 32), colour)
            stream = io.BytesIO(); image.save(stream, format="PNG")
            return stream.getvalue()
        result = c.compare_non_table("figure.png", payload("white"), payload("black"), self.policy())
        self.assertFalse(result["pass"])

    def test_nonvolatile_json_change_is_rejected_but_timestamp_is_ignored(self):
        reference = json.dumps({"status": "pass", "created_at_utc": "2026-01-01T00:00:00Z"}).encode()
        timestamp_only = json.dumps({"status": "pass", "created_at_utc": "2026-02-01T00:00:00Z"}).encode()
        changed = json.dumps({"status": "failed", "created_at_utc": "2026-02-01T00:00:00Z"}).encode()
        self.assertTrue(c.compare_non_table("report.json", reference, timestamp_only, self.policy())["pass"])
        self.assertFalse(c.compare_non_table("report.json", reference, changed, self.policy())["pass"])


class ReferenceArchive(unittest.TestCase):
    def test_wrong_reference_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "wrong.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("wrong.txt", "wrong")
            with self.assertRaises(r.ReplicationError):
                r.validate_reference_archive(path)


class NullAndRunProvenance(unittest.TestCase):
    def test_text_series_comparison_is_positional_after_declared_key_alignment(self):
        left = pd.Series(["H0A", "H1"], index=[7, 11])
        right = pd.Series(["H0A", "H1"], index=[0, 1])
        self.assertEqual(c.series_equal(left, right).tolist(), [True, True])

    def test_matching_nulls_and_signed_infinities_pass(self):
        values = pd.DataFrame({"x": [float("nan"), float("inf"), -float("inf"), 0.25]})
        result = c.numeric_comparison(values, values.copy(), "x", {"atol": 0.0, "rtol": 0.0})
        self.assertTrue(result["pass"])
        self.assertEqual(result["matching_null_count"], 1)
        self.assertEqual(result["matching_infinity_count"], 2)

    def test_changed_nulls_infinities_and_nonnumeric_values_fail(self):
        for left, right in ((float("nan"), 1.0), (1.0, float("nan")),
                            (float("inf"), -float("inf")), (float("inf"), 1.0),
                            (1.0, float("inf")), (float("nan"), "corrupt")):
            with self.subTest(left=left, right=right):
                result = c.numeric_comparison(pd.DataFrame({"x": [left]}), pd.DataFrame({"x": [right]}),
                                              "x", {"atol": 0.01, "rtol": 0.1})
                self.assertFalse(result["pass"])

    def frames(self):
        reference = pd.DataFrame({
            "election_id": ["pre_2022_r1"] * 3, "scenario_id": ["H0A", "H0A", "H1"],
            "model_key": ["nls"] * 3, "estimand_type": ["cell_probability"] * 3,
            "social_group": ["a", "b", "a"], "vote_category": ["vote"] * 3,
            "estimate": [0.25, 0.75, 0.3],
            "run_id": ["20260810T090000Z__" + "a" * 12] * 2 + ["20260810T090001Z__" + "b" * 12],
        })
        candidate = reference.copy()
        candidate["run_id"] = ["20261005T090000Z__" + "c" * 12] * 2 + ["20261005T090001Z__" + "d" * 12]
        return reference, candidate

    def compare(self, reference, candidate):
        def encoded(frame):
            stream = io.BytesIO(); frame.to_parquet(stream, index=False); return stream.getvalue()
        policy = json.loads((r.CONTRACT / "certification_policy_v1.json").read_text(encoding="utf-8"))
        return c.compare_table("02_TABLES_PRINCIPALES/longitudinal_nls.parquet", encoded(reference), encoded(candidate), policy)

    def test_valid_new_run_ids_pass_without_relaxing_estimates(self):
        reference, candidate = self.frames()
        result = self.compare(reference, candidate)
        self.assertTrue(result["pass"])
        self.assertEqual(result["run_provenance"]["candidate"]["pair_count"], 2)
        candidate.loc[0, "estimate"] += 1e-4
        self.assertFalse(self.compare(reference, candidate)["pass"])

    def test_bad_ids_multiple_runs_or_reused_runs_fail(self):
        for change in ("bad_format", "bad_timestamp", "multiple_runs", "reused_run"):
            with self.subTest(change=change):
                reference, candidate = self.frames()
                if change == "bad_format": candidate.loc[0, "run_id"] = "fake"
                if change == "bad_timestamp": candidate.loc[:1, "run_id"] = "20269999T999999Z__" + "c" * 12
                if change == "multiple_runs": candidate.loc[0, "run_id"] = "20261005T090002Z__" + "e" * 12
                if change == "reused_run": candidate.loc[2, "run_id"] = candidate.loc[0, "run_id"]
                self.assertFalse(self.compare(reference, candidate)["pass"])

    def test_run_key_must_match_own_run_id_prefix(self):
        _, candidate = self.frames()
        candidate["run_key"] = ["c" * 64] * 2 + [None]
        config = {"family": "krt", "pair_keys": ["election_id", "scenario_id"], "run_key_column": "run_key"}
        self.assertTrue(c.validate_run_provenance(candidate, config)["pass"])
        candidate.loc[0, "run_key"] = "b" * 64
        self.assertFalse(c.validate_run_provenance(candidate, config)["pass"])

    def test_cross_table_pair_run_consistency(self):
        _, candidate = self.frames()
        config = {"family": "krt", "pair_keys": ["election_id", "scenario_id"]}
        first = c.validate_run_provenance(candidate, config)
        candidate.loc[:1, "run_id"] = "20261005T090002Z__" + "e" * 12
        second = c.validate_run_provenance(candidate, config)
        result = c.compare_cross_table_provenance([
            {"path": "aggregate.parquet", "run_provenance": {"candidate": first}},
            {"path": "commune.parquet", "run_provenance": {"candidate": second}},
        ])
        self.assertFalse(result["pass"])


class ScopedIdentifierAliases(unittest.TestCase):
    aggregate_path = "02_TABLES_PRINCIPALES/longitudinal_krt_aggregate.parquet"
    proof_path = "04_PANEL_ET_HARMONISATION/panel_2000.csv"
    legacy_id = "v101_targeted_rerun_current_primary_2000"
    canonical_id = "longitudinal_2000_v1__strict_nested_3000__seed_20260803"

    def policy(self):
        return json.loads((r.CONTRACT / "certification_policy_v1.json").read_text(encoding="utf-8"))

    @staticmethod
    def encoded(frame):
        stream = io.BytesIO()
        frame.to_parquet(stream, index=False)
        return stream.getvalue()

    def frames(self, election_id="leg_2022_r1", scenario_id="H1"):
        reference = pd.DataFrame({
            "election_id": [election_id], "scenario_id": [scenario_id],
            "model_key": ["krt"], "estimand": ["contrast"],
            "run_id": ["20260810T105531Z__73ea044afa93"],
            "panel_id": [self.canonical_id], "source_panel_id": [self.legacy_id],
            "mean": [0.2], "median": [0.2], "q025": [0.1], "q975": [0.3],
            "legacy_mean": [0.2], "mean_difference_from_legacy": [0.0],
        })
        candidate = reference.copy()
        candidate["source_panel_id"] = self.canonical_id
        return reference, candidate

    def compare(self, reference, candidate):
        return c.compare_table(
            self.aggregate_path, self.encoded(reference), self.encoded(candidate), self.policy(),
        )

    def test_exact_legacy_alias_is_accepted_only_for_preregistered_pair(self):
        reference, candidate = self.frames()
        result = self.compare(reference, candidate)
        self.assertTrue(result["pass"])
        self.assertEqual(len(result["identifier_aliases"]), 1)
        self.assertEqual(result["identifier_aliases"][0]["normalized_rows"], 1)

        for pair in (("pre_2022_r1", "H1"), ("leg_2022_r1", "H0A")):
            with self.subTest(pair=pair):
                wrong_reference, wrong_candidate = self.frames(*pair)
                self.assertFalse(self.compare(wrong_reference, wrong_candidate)["pass"])

    def test_unknown_alias_or_changed_scientific_value_is_rejected(self):
        reference, candidate = self.frames()
        unknown = candidate.copy()
        unknown["source_panel_id"] = "unregistered_panel"
        self.assertFalse(self.compare(reference, unknown)["pass"])

        changed = candidate.copy()
        changed["mean"] = 1.2
        self.assertFalse(self.compare(reference, changed)["pass"])

    def test_alias_requires_a_successful_canonical_panel_comparison(self):
        reference, candidate = self.frames()
        compared = self.compare(reference, candidate)
        passed = c.validate_identifier_alias_requirements([
            compared, {"path": self.proof_path, "pass": True, "identifier_aliases": []},
        ])
        self.assertTrue(passed["pass"])
        self.assertEqual(passed["normalized_rows"], 1)

        for proof in (None, {"path": self.proof_path, "pass": False, "identifier_aliases": []}):
            with self.subTest(proof=proof):
                tables = [compared] + ([] if proof is None else [proof])
                self.assertFalse(c.validate_identifier_alias_requirements(tables)["pass"])


class AuxiliaryTableAlignment(unittest.TestCase):
    expected_keys = {
        "04_PANEL_ET_HARMONISATION/coverage_by_election.csv": ["election_id"],
        "05_DIAGNOSTICS/diagnostics_NLS_resume.csv": ["election_id", "scenario_id"],
        "05_DIAGNOSTICS/identification_resume.csv": ["election_id", "scenario_id"],
        "05_DIAGNOSTICS/matrice_couverture_modeles.csv": ["election_id"],
        "06_DOCUMENTATION/COUVERTURE_BETA_PAR_COUPLE.csv": ["method", "election_id", "scenario_id"],
    }

    def policy(self):
        return json.loads((r.CONTRACT / "certification_policy_v1.json").read_text(encoding="utf-8"))

    @staticmethod
    def csv_bytes(frame):
        return frame.to_csv(index=False).encode("utf-8")

    def frame(self, keys):
        values = {
            "method": ["KRT", "R_EI"],
            "election_id": ["pre_2022_r1", "leg_2022_r1"],
            "scenario_id": ["H0A", "H1"],
        }
        return pd.DataFrame({**{key: values[key] for key in keys}, "value": [1.0, 2.0]}, index=[7, 11])

    def test_all_auxiliary_tables_have_explicit_scientific_keys_and_align_by_them(self):
        policy = self.policy()
        for path, keys in self.expected_keys.items():
            with self.subTest(path=path):
                self.assertEqual(policy["tables"][path]["keys"], keys)
                reference = self.frame(keys)
                candidate = reference.iloc[::-1].reset_index(drop=True)
                result = c.compare_table(
                    path, b"unused", self.csv_bytes(candidate), policy, reference_frame=reference,
                )
                self.assertTrue(result["pass"])

    def test_duplicate_auxiliary_keys_are_rejected(self):
        path = "05_DIAGNOSTICS/diagnostics_NLS_resume.csv"
        reference = self.frame(self.expected_keys[path])
        candidate = reference.copy()
        candidate.loc[11, ["election_id", "scenario_id"]] = candidate.loc[7, ["election_id", "scenario_id"]].to_numpy()
        result = c.compare_table(
            path, b"unused", self.csv_bytes(candidate), self.policy(), reference_frame=reference,
        )
        self.assertFalse(result["pass"])
        self.assertIn("duplicate_table_keys", result["issues"])


class GeneratedProvenance(unittest.TestCase):
    manifest_path = "06_DOCUMENTATION/DELIVERY_MANIFEST.json"
    qa_path = "06_DOCUMENTATION/REPORT_QA.json"

    def fixture(self, directory: Path, change=None, duplicate=False):
        base = {
            "data.csv": b"estimate\n0.25\n",
            "01_RAPPORT/RAPPORT_LONGITUDINAL.html": b"<html><body>Result 0.25</body></html>",
            "01_RAPPORT/RAPPORT_LONGITUDINAL.pdf": b"%PDF-1.4\n/Type /Page\n%%EOF",
            self.qa_path: json.dumps({"schema_version": "professor_report_qa_v1", "visual_inspection_complete": True}).encode(),
            self.manifest_path: json.dumps({"schema_version": "delivery_manifest_v2"}).encode(),
        }
        reference = directory / "reference.zip"
        with zipfile.ZipFile(reference, "w") as archive:
            for path, content in base.items():
                archive.writestr(path, content)
        candidate_data = dict(base)
        qa = {
            "schema_version": "replication_report_qa_v2", "created_at_utc": "2026-10-05T00:00:00Z",
            "pdf_origin": "rendered_from_newly_generated_html_not_copied_from_reference",
            "visual_inspection_performed": False,
            "numeric_equality_to_historical_results": "not_certified",
            "reference_statistics_in_static_narrative": "historical_context_not_new_validation",
            "coverage_contract": "expected_results_610.json",
        }
        if change == "false_visual_claim":
            qa["visual_inspection_performed"] = True
        candidate_data[self.qa_path] = json.dumps(qa).encode()
        if change == "changed_scientific_data":
            candidate_data["data.csv"] = b"estimate\n0.50\n"
        records = [{"path": path, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
                   for path, content in candidate_data.items() if path != self.manifest_path]
        if change == "bad_hash":
            records[0]["sha256"] = "0" * 64
        if change == "missing_record":
            records.pop()
        if change == "duplicate_record":
            records.append(dict(records[0]))
        manifest = {
            "schema_version": "longitudinal_results_recalculated_v2",
            "created_at_utc": "2026-10-05T00:00:00Z", "files": records,
            "verification": {"status": "complete_structure_not_numerical_equality",
                             "expected_files": len(base), "pending_generated_manifest": True},
            "source_reference_sha256": c.file_sha256(reference),
            "not_a_claim_of_bitwise_or_monte_carlo_equality": True,
        }
        if change == "wrong_reference":
            manifest["source_reference_sha256"] = "0" * 64
        candidate_data[self.manifest_path] = json.dumps(manifest).encode()
        candidate = directory / "candidate.zip"
        with zipfile.ZipFile(candidate, "w") as archive:
            for path, content in candidate_data.items():
                archive.writestr(path, content)
            if duplicate:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    archive.writestr("data.csv", candidate_data["data.csv"])
        policy = directory / "policy.json"
        policy.write_text("{}", encoding="utf-8")
        return c.compare_artifacts(reference, candidate, policy, None)

    def test_truthful_new_receipts_pass_without_claiming_visual_inspection(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.fixture(Path(temp))
        self.assertTrue(result["scientific_equivalence_pass"])
        self.assertFalse(result["exact_replay_pass"])
        manifest = next(item for item in result["artifact_results"] if item["path"] == self.manifest_path)
        qa = next(item for item in result["artifact_results"] if item["path"] == self.qa_path)
        self.assertEqual(manifest["verified_file_hashes"], 4)
        self.assertFalse(qa["visual_inspection_verified"])
        self.assertTrue(qa["rendering_origin_is_self_reported"])

    def test_corrupt_or_incomplete_receipts_fail(self):
        for change in ("bad_hash", "missing_record", "duplicate_record", "wrong_reference", "false_visual_claim"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                result = self.fixture(Path(temp), change=change)
                self.assertFalse(result["scientific_equivalence_pass"])

    def test_self_consistent_manifest_does_not_allow_changed_scientific_data(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.fixture(Path(temp), change="changed_scientific_data")
        manifest = next(item for item in result["artifact_results"] if item["path"] == self.manifest_path)
        self.assertTrue(manifest["pass"])
        self.assertFalse(result["scientific_equivalence_pass"])
        self.assertFalse(next(item for item in result["table_results"] if item["path"] == "data.csv")["pass"])

    def test_duplicate_zip_paths_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.fixture(Path(temp), duplicate=True)
        self.assertFalse(result["structure_pass"])
        self.assertEqual(result["candidate_duplicate_path_count"], 1)


class PortableReportPayload(unittest.TestCase):
    payload_id = "data-analytics-portable-artifact-payload-source"

    def html(self, *, generated="2026-08-31T01:57:54+00:00", mtime=0,
             estimate=0.25, scenario="H0A", data_year=2022,
             executed_at="2026-08-31T01:58:12+00:00", scientific_date="2022-04-10",
             dataset_executed_at="2022-04-10T20:00:00+00:00",
             corrupt=False, duplicate=False):
        artifact = {
            "manifest": {"generatedAt": generated, "title": "Scientific report"},
            "snapshot": {"generatedAt": generated, "datasets": {
                "estimates": [{"estimate": estimate, "scenario": scenario, "year": data_year}],
                "scientific_timing": {
                    "executed_at": dataset_executed_at, "scientific_date": scientific_date,
                },
            }},
            "sources": [{"query": {"executed_at": executed_at}}],
        }
        encoded = base64.b64encode(gzip.compress(json.dumps(artifact).encode(), mtime=mtime)).decode()
        if corrupt:
            encoded = "not valid gzip/base64!"
        template = f'<template id="{self.payload_id}" data-encoding="gzip-base64">{encoded}</template>'
        return (f'<html><body><div class="portable-page-meta"><time datetime="{generated}">{generated}</time></div>'
                + template * (2 if duplicate else 1) + '</body></html>').encode()

    def compare(self, candidate):
        policy = json.loads((r.CONTRACT / "certification_policy_v1.json").read_text(encoding="utf-8"))
        return c.compare_non_table("report.html", self.html(), candidate, policy)

    def test_gzip_header_change_does_not_change_scientific_report(self):
        self.assertTrue(self.compare(self.html(mtime=1000))["pass"])

    def test_regenerated_report_date_is_not_scientific_data(self):
        self.assertTrue(self.compare(self.html(generated="2026-10-05"))["pass"])

    def test_query_execution_timestamp_is_ignored_but_reported(self):
        result = self.compare(self.html(executed_at="2026-10-05T23:59:59+00:00"))
        self.assertTrue(result["pass"])
        self.assertEqual(
            result["portable_query_execution_timestamps_ignored"],
            {"reference": 1, "candidate": 1},
        )

    def test_invalid_execution_timestamp_and_changed_scientific_date_are_rejected(self):
        self.assertFalse(self.compare(self.html(executed_at="not-a-timestamp"))["pass"])
        self.assertFalse(self.compare(self.html(scientific_date="2021-04-10"))["pass"])
        self.assertFalse(self.compare(self.html(dataset_executed_at="2021-04-10T20:00:00+00:00"))["pass"])

    def test_decoded_estimates_use_existing_html_numeric_policy(self):
        self.assertTrue(self.compare(self.html(estimate=0.251))["pass"])
        self.assertFalse(self.compare(self.html(estimate=0.75))["pass"])

    def test_decoded_identifiers_and_integer_years_remain_exact(self):
        self.assertFalse(self.compare(self.html(scenario="H1"))["pass"])
        self.assertFalse(self.compare(self.html(data_year=2021))["pass"])

    def test_corrupt_or_duplicated_payload_is_rejected(self):
        self.assertFalse(self.compare(self.html(corrupt=True))["pass"])
        self.assertFalse(self.compare(self.html(duplicate=True))["pass"])

    def test_overflowing_numeric_text_requires_exact_tokens(self):
        base = b'<html><script>const x = "1e999";</script></html>'
        altered = b'<html><script>const x = "2e999";</script></html>'
        self.assertTrue(c.compare_non_table("report.html", base, base, {})["pass"])
        self.assertFalse(c.compare_non_table("report.html", base, altered, {})["pass"])


if __name__ == "__main__":
    unittest.main()
