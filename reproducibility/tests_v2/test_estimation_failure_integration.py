"""Failure plumbing tests: every scientific estimator is replaced by a stub."""
from __future__ import annotations

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from code_longitudinal import run_longitudinal_production as nls
from code_longitudinal import run_r_ei_all_2x2 as r_ei
from code_longitudinal import run_rxc_panel_extension_v11 as rxc
from code_longitudinal import run_fast_nls_covariate_specs as cov
from reproducibility.estimation_process import ResourceWaitTimeoutError
from reproducibility.estimation_recovery import BatchEstimationError


class FailureIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mock estimation recovery ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.dict(os.environ, {"LONGITUDINAL_RETRY_FAILED": "0"}))

    def mock(self, module, name, **kwargs):
        return self.stack.enter_context(patch.object(module, name, **kwargs))

    def value(self, module, name, value):
        return self.stack.enter_context(patch.object(module, name, value))

    def saved_nls(self, run_id):
        directory = self.root / "runs" / run_id
        directory.mkdir(parents=True, exist_ok=True)
        for name in nls.NLS_REQUIRED_OUTPUTS:
            (directory / name).write_text("value\n0.25\n", encoding="utf-8")

    def nls_setup(self):
        plan = pd.DataFrame([
            {"election_id": e, "scenario_id": "H0A", "preparation_status": "admissible"}
            for e in ("pre_2017_r1", "pre_2022_r1")
        ])
        self.value(nls, "ROOT", self.root)
        self.value(nls, "OUTPUT_DIR", self.root / "outputs")
        self.value(nls, "RUNS_DIR", self.root / "runs")
        self.mock(nls, "get_scope", return_value=SimpleNamespace(is_full=False))
        self.mock(nls, "_ensure_inputs", return_value=(plan, {"panel_id": "mock_panel"}))
        self.mock(nls, "_filtered_plan", return_value=plan)
        self.mock(nls, "_nls_success_index", return_value={})
        return self.mock(nls, "_save_progress")

    def test_nls_continues_independent_pairs_persists_failure_and_requires_explicit_retry(self):
        progress = self.nls_setup()
        calls = []
        fail = [True]

        def estimate(election, scenario, **kwargs):
            calls.append((election.election_id, kwargs))
            if election.election_id == "pre_2017_r1" and fail[0]:
                raise ValueError("mock deterministic data error")
            self.saved_nls(election.election_id)
            return {"status": "success", "run_id": election.election_id, "diagnostic_status": "fail"}

        self.mock(nls, "run_nls", side_effect=estimate)
        with self.assertRaises(BatchEstimationError) as caught:
            nls.run_nls_longitudinal()
        self.assertEqual([x[0] for x in calls], ["pre_2017_r1", "pre_2022_r1"])
        self.assertEqual(caught.exception.report["counts"]["success"], 1)
        self.assertEqual(caught.exception.report["errors"][0]["type"], "ValueError")
        self.assertIn("replication_court", str(caught.exception.report_path))
        calls.clear()
        with self.assertRaises(BatchEstimationError):
            nls.run_nls_longitudinal()
        self.assertEqual([x[0] for x in calls], ["pre_2022_r1"])
        fail[0] = False
        with patch.dict(os.environ, {"LONGITUDINAL_RETRY_FAILED": "1"}):
            result = nls.run_nls_longitudinal()
        self.assertEqual(result["success_or_resumed"], 2)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(len(progress.call_args.args[1]), 2)
        self.assertTrue(all(x[1] == {"sample_size": 2000, "panel_path": nls.PANEL_PATH, "force": False} for x in calls))

    def test_nls_transient_retry_preserves_exception_class_and_unique_progress_rows(self):
        progress = self.nls_setup()
        calls = []

        def estimate(election, scenario, **kwargs):
            calls.append(election.election_id)
            if len(calls) == 1:
                raise TimeoutError("mock transient")
            self.saved_nls(election.election_id)
            return {"status": "success", "run_id": election.election_id}

        self.mock(nls, "run_nls", side_effect=estimate)
        result = nls.run_nls_longitudinal()
        self.assertEqual(calls, ["pre_2017_r1", "pre_2017_r1", "pre_2022_r1"])
        self.assertEqual(result["planned"], 2)
        self.assertEqual(result["success_or_resumed"], 2)
        self.assertEqual(len(progress.call_args.args[1]), 2)

    def test_nls_success_without_files_is_not_counted(self):
        self.nls_setup()
        self.mock(nls, "run_nls", return_value={"status": "success", "run_id": "missing"})
        with self.assertRaises(BatchEstimationError) as caught:
            nls.run_nls_longitudinal()
        self.assertEqual(caught.exception.report["counts"]["success"], 0)
        self.assertEqual(len(caught.exception.report["errors"]), 2)

    def test_nls_failed_return_status_is_not_a_successful_callback(self):
        self.nls_setup()
        self.mock(nls, "run_nls", return_value={"status": "failed", "error": "mock failure"})
        with self.assertRaises(BatchEstimationError) as caught:
            nls.run_nls_longitudinal()
        self.assertEqual(len(caught.exception.report["errors"]), 2)

    def test_nls_systemic_error_preserves_type_and_stops_remaining_estimates(self):
        self.nls_setup()
        estimator = self.mock(nls, "run_nls", side_effect=MemoryError("mock exhausted memory"))
        with self.assertRaises(BatchEstimationError) as caught:
            nls.run_nls_longitudinal()
        self.assertEqual(estimator.call_count, 1)
        self.assertEqual(caught.exception.report["errors"][0]["type"], "MemoryError")
        self.assertEqual(caught.exception.report["abort_reason"], "MemoryError: mock exhausted memory")

    def test_r_failure_keeps_other_pair_and_resume_checks_saved_outputs(self):
        pairs = frozenset((e, "H0A") for e in ("pre_2017_r1", "pre_2022_r1"))
        scope = SimpleNamespace(is_full=False, pairs=pairs)
        self.value(r_ei, "ROOT", self.root)
        self.value(r_ei, "RUN_DIR", self.root / "r_runs")
        self.value(r_ei, "R_PROJECT_LIBRARY", self.root / "r_library")
        self.value(r_ei, "PROGRESS_PATH", self.root / "r_progress.parquet")
        self.value(r_ei, "STATUS_PATH", self.root / "r_status.json")
        self.mock(r_ei, "get_scope", return_value=scope)
        self.mock(r_ei, "_reference_seeds", return_value={p: 123 for p in pairs})
        self.mock(r_ei, "load_longitudinal_panel_manifest", return_value={"panel_id": "p", "panel_sha256": "panel_hash"})
        self.mock(r_ei, "_rscript_path", return_value=Path("MOCK_R_NOT_EXECUTED.exe"))
        self.mock(r_ei, "_wait_for_memory")
        self.mock(r_ei, "_memory_snapshot", return_value={"allowed": True})
        inputs = []
        for election, scenario in sorted(pairs):
            path = self.root / f"{election}__{scenario}__p__n2000.csv"
            path.write_text("value\n1\n", encoding="utf-8")
            inputs.append(path)
        self.mock(r_ei, "_model_ready_inputs", return_value=inputs)
        commands = []
        fail = [True]

        def external(command, **kwargs):
            commands.append(command)
            source, out = Path(command[3]), Path(command[4])
            election = source.name.split("__")[0]
            if election == "pre_2017_r1" and fail[0]:
                kwargs["stderr"].write("mock R failure")
                return SimpleNamespace(returncode=1)
            for name in ("commune_latent_summaries_r.csv", "aggregate_summaries_r.csv"):
                (out / name).write_text("value\n1\n", encoding="utf-8")
            (out / "manifest_r.json").write_text(json.dumps({"status": "success", "n_communes": 2000,
                "scenario_id": "H0A", "election_id": election, "seed": 123,
                "input_sha256": r_ei.file_sha256(source), "mathematical_identity_with_python_model": False}), encoding="utf-8")
            return SimpleNamespace(returncode=0)

        self.mock(r_ei.subprocess, "run", side_effect=external)
        with self.assertRaises(BatchEstimationError):
            r_ei.run(scenarios=("H0A",))
        self.assertEqual(len(commands), 2)
        self.assertEqual(json.loads(r_ei.STATUS_PATH.read_text())["status"], "failed")
        self.assertTrue(all(c[1] == "--vanilla" and c[-1] == "123" for c in commands))
        fail[0] = False
        with patch.dict(os.environ, {"LONGITUDINAL_RETRY_FAILED": "1"}):
            result = r_ei.run(scenarios=("H0A",))
        self.assertEqual(result["pairs_successful"], 2)
        self.assertEqual(len(commands), 3)  # successful second pair reused, not fitted again
        manifest = r_ei.RUN_DIR / "pre_2022_r1__H0A" / "manifest_r.json"
        (manifest.parent / "aggregate_summaries_r.csv").unlink()
        self.assertFalse(r_ei._manifest_is_reusable(manifest, inputs[1], "H0A"))

    def test_r_memory_wait_timeout_aborts_before_next_pair_and_ignores_stale_stderr(self):
        pairs = frozenset((e, "H0A") for e in ("pre_2017_r1", "pre_2022_r1"))
        scope = SimpleNamespace(is_full=False, pairs=pairs)
        self.value(r_ei, "ROOT", self.root)
        self.value(r_ei, "RUN_DIR", self.root / "r_runs")
        self.value(r_ei, "R_PROJECT_LIBRARY", self.root / "r_library")
        self.value(r_ei, "PROGRESS_PATH", self.root / "r_progress.parquet")
        self.value(r_ei, "STATUS_PATH", self.root / "r_status.json")
        self.mock(r_ei, "get_scope", return_value=scope)
        self.mock(r_ei, "_reference_seeds", return_value={p: 123 for p in pairs})
        self.mock(r_ei, "load_longitudinal_panel_manifest",
                  return_value={"panel_id": "p", "panel_sha256": "panel_hash"})
        self.mock(r_ei, "_rscript_path", return_value=Path("MOCK_R_NOT_EXECUTED.exe"))
        inputs = []
        for election, scenario in sorted(pairs):
            path = self.root / f"{election}__{scenario}__p__n2000.csv"
            path.write_text("value\n1\n", encoding="utf-8")
            inputs.append(path)
        self.mock(r_ei, "_model_ready_inputs", return_value=inputs)
        first_election = inputs[0].name.split("__", maxsplit=1)[0]
        stale_dir = r_ei.RUN_DIR / f"{first_election}__H0A"
        stale_dir.mkdir(parents=True)
        (stale_dir / "runner_stderr.log").write_text(
            "STALE FAILURE FROM AN EARLIER ATTEMPT", encoding="utf-8",
        )
        waits = []

        def no_memory(sequence, expected_pairs, election_id, scenario_id):
            waits.append((sequence, election_id, scenario_id))
            raise ResourceWaitTimeoutError(
                resource="memoire_R", key=f"{election_id}__{scenario_id}", timeout_seconds=7,
            )

        self.mock(r_ei, "_wait_for_memory", side_effect=no_memory)
        runner = self.mock(r_ei.subprocess, "run")
        with self.assertRaises(BatchEstimationError) as caught:
            r_ei.run(scenarios=("H0A",))
        self.assertEqual(len(waits), 1)
        runner.assert_not_called()
        self.assertEqual(caught.exception.report["errors"][0]["classification"], "systemic")
        progress = pd.read_parquet(r_ei.PROGRESS_PATH)
        self.assertEqual(len(progress), 1)
        self.assertEqual(progress.iloc[0]["status"], "resource_wait_timeout")
        self.assertTrue(progress.iloc[0]["error"].startswith("ResourceWaitTimeoutError:"))
        self.assertNotIn("STALE FAILURE", progress.iloc[0]["error"])
        status = json.loads(r_ei.STATUS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(status["pairs_failed"], 1)

    def test_rxc_exception_is_not_swallowed_and_other_pair_runs(self):
        self.value(rxc, "ROOT", self.root)
        self.value(nls, "RUNS_DIR", self.root / "runs")
        self.mock(rxc, "get_scope", return_value=SimpleNamespace(is_full=False, extension_nls_pairs={1}))
        self.mock(rxc, "file_sha256", return_value=rxc.EXPECTED_PANEL_SHA256)
        audit = self.root / "audit.csv"
        audit.write_text("value\n1\n", encoding="utf-8")
        self.mock(rxc, "eligible_deferred_pairs", return_value=[("pre_2017_r1", "RXC1"), ("pre_2017_r1", "RXC2")])
        self.mock(rxc, "validate_prepared_pair", return_value={"n_rows": 2000})
        calls = []

        def estimate(election, scenario, **kwargs):
            calls.append((scenario.scenario_id, kwargs))
            if scenario.scenario_id == "RXC1":
                raise ValueError("mock RxC failure")
            self.saved_nls("rxc2")
            return {"status": "success", "run_id": "rxc2"}

        self.mock(rxc, "run_nls", side_effect=estimate)
        out = self.root / "rxc_out"
        with self.assertRaises(BatchEstimationError) as caught:
            rxc.run_extension(audit_path=audit, panel_path=self.root / "panel.parquet", output_dir=out)
        self.assertEqual([x[0] for x in calls], ["RXC1", "RXC2"])
        self.assertEqual(caught.exception.report["counts"]["success"], 1)
        self.assertEqual(json.loads((out / "rxc_nls_panel_extension_status.json").read_text())["status"], "failed")
        self.assertTrue(all(x[1]["sample_size"] == 2000 and x[1]["force"] is False for x in calls))

    def test_covariate_failure_continues_but_blocks_consolidation_and_success_markers(self):
        self.value(cov, "ROOT", self.root)
        self.mock(cov, "get_scope", return_value=SimpleNamespace(is_full=False))
        rows = [{"election_id": e, "scenario_id": "H0A"} for e in ("pre_2017_r1", "pre_2022_r1")]
        self.mock(cov, "load_scope", return_value=rows)
        self.mock(cov, "build_covariate_lookup", return_value={r["election_id"]: object() for r in rows})
        consolidate = self.mock(cov, "consolidate", return_value={"successful_runs": 2})
        calls = []
        fail = [True]

        def estimate(row, spec, lookup, **kwargs):
            calls.append((row["election_id"], kwargs))
            if row["election_id"] == "pre_2017_r1" and fail[0]:
                raise ValueError("mock covariate failure")
            return pd.DataFrame({"estimate": [0.2]}), pd.DataFrame({"coefficient": [0.2]}), {
                "status": "success", **row, "spec_id": spec, "diagnostic_status": "fail"}

        self.mock(cov, "fit_pair_spec", side_effect=estimate)
        out = self.root / "covariates"
        spec = next(iter(cov.SPECS))
        self.stack.enter_context(patch("sys.argv", ["mock", "--output-root", str(out), "--spec", spec]))
        with self.assertRaises(BatchEstimationError):
            cov.main()
        self.assertEqual([x[0] for x in calls], ["pre_2017_r1", "pre_2022_r1"])
        consolidate.assert_not_called()
        self.assertEqual(json.loads((out / "status.json").read_text())["status"], "failed")
        fail[0] = False
        with patch.dict(os.environ, {"LONGITUDINAL_RETRY_FAILED": "1"}):
            cov.main()
        self.assertEqual(len(calls), 3)
        consolidate.assert_called_once_with(out, 2)
        self.assertEqual(json.loads((out / "status.json").read_text())["runs_completed"], 2)
        self.assertTrue(all(x[1] == {"n_starts": 4, "max_nfev": 1200} for x in calls))


if __name__ == "__main__":
    unittest.main()
