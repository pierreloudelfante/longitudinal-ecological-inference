"""Saved-output guards with mocked samplers; no scientific estimation is run."""
from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reproducibility import replication_complete as pipeline


class SavedKrtOutputs(unittest.TestCase):
    def setUp(self):
        self.rows = pipeline.read_json(pipeline.CONTRACT / "krt_replay_240.json")["entries"][:2]
        self.temp = tempfile.TemporaryDirectory(prefix="mock KRT saved outputs ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.object(pipeline, "ROOT", self.root))
        self.stack.enter_context(patch.object(pipeline, "STATE_DIR", self.root / ".runtime/replication_v2"))
        self.stack.enter_context(patch.dict(os.environ, {"LONGITUDINAL_RETRY_FAILED": "0"}))

    def save(self, row, *, missing=None, empty=None):
        run_id = "fixture_" + row["reference_run_id"]
        folder = self.root / "outputs/runs" / run_id
        folder.mkdir(parents=True, exist_ok=True)
        parameters = {**row["arguments"], "election_id": row["election_id"],
                      "scenario_id": row["scenario_id"], "model_key": "krt_beta_binomial",
                      "sample_size": 2000, "reference_run_id": row["reference_run_id"],
                      "run_role": "canonical", "public_schema_version": "longitudinal_public_schema_v1.0.2"}
        (folder / "manifest.json").write_text(json.dumps({"run_id": run_id, "status": "success",
              "parameters": parameters, "diagnostic_status": "fail"}), encoding="utf-8")
        for name in pipeline.KRT_REQUIRED_OUTPUTS:
            if name != missing:
                (folder / name).write_bytes(b"" if name == empty else b"mock saved output\n")
        return folder

    def test_missing_trace_fails_independent_item_and_blocks_normal_and_explicit_dispatch(self):
        first = self.save(self.rows[0], missing="trace.nc")
        second = self.save(self.rows[1])
        first_manifest = (first / "manifest.json").read_bytes()
        with patch("code_longitudinal.run_2x2_batch.run_2x2",
                   return_value={"status": "skipped_existing_success"}) as sampler:
            with self.assertRaises(pipeline.BatchEstimationError) as failure:
                pipeline.execute_krt_contract_rows(self.rows)
            self.assertEqual(sampler.call_count, 1)  # only the independent intact run
            self.assertEqual(failure.exception.report["counts"]["success"], 1)
            self.assertEqual(len(failure.exception.report["errors"]), 1)
            self.assertIn("trace.nc", failure.exception.report["errors"][0]["message"])
            sampler.reset_mock()
            with self.assertRaises(pipeline.BatchEstimationError):
                pipeline.execute_krt_contract_rows(self.rows)
            self.assertEqual(sampler.call_count, 1)
            self.assertEqual(sampler.call_args.kwargs["run_metadata"]["reference_run_id"], self.rows[1]["reference_run_id"])
            sampler.reset_mock()
            with patch.dict(os.environ, {"LONGITUDINAL_RETRY_FAILED": "1"}):
                with self.assertRaises(pipeline.BatchEstimationError):
                    pipeline.execute_krt_contract_rows(self.rows)
            self.assertEqual(sampler.call_count, 1)
            self.assertEqual((first / "manifest.json").read_bytes(), first_manifest)
            self.assertTrue((second / "trace.nc").is_file())
            self.save(self.rows[0])  # fixture file recovery, not a model refit
            with patch.dict(os.environ, {"LONGITUDINAL_RETRY_FAILED": "1"}):
                results = pipeline.execute_krt_contract_rows(self.rows)
            self.assertEqual(len(results), 2)

    def test_empty_output_is_never_success_and_diagnostic_fail_remains_valid_execution(self):
        folder = self.save(self.rows[0], empty="model_diagnostics.csv")
        with self.assertRaisesRegex(pipeline.ReplicationError, "model_diagnostics.csv"):
            pipeline._validated_krt_run(self.rows[0], required=True)
        self.save(self.rows[0])
        actual, manifest = pipeline._validated_krt_run(self.rows[0], required=True)
        self.assertEqual(actual, folder)
        self.assertEqual(manifest["diagnostic_status"], "fail")
        manifest["parameters"]["random_seed"] += 1
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(pipeline.ReplicationError, "random_seed"):
            pipeline._validated_krt_run(self.rows[0], required=True)

    def test_new_success_without_manifest_is_failed_and_not_reexecuted_on_normal_resume(self):
        with patch("code_longitudinal.run_2x2_batch.run_2x2", return_value={"status": "success"}) as sampler:
            with self.assertRaises(pipeline.BatchEstimationError):
                pipeline.execute_krt_contract_rows(self.rows[:1])
            sampler.assert_called_once()
            sampler.reset_mock()
            with self.assertRaises(pipeline.BatchEstimationError):
                pipeline.execute_krt_contract_rows(self.rows[:1])
            sampler.assert_not_called()


if __name__ == "__main__":
    unittest.main()
