"""Cheap integration guards for the supervised production boundaries.

All scientific estimators and subprocesses are replaced by stubs.  The tests
prove that process isolation changes orchestration only: the frozen row,
pair, panel, tuning arguments and historical seeds reach the same estimator,
and a supervisor exit cannot be accepted without validated saved outputs.
"""
from __future__ import annotations

from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from code_longitudinal import build_longitudinal_panel as panel_module
from code_longitudinal import run_2x2_batch as krt_module
from code_longitudinal import run_fast_nls_covariate_specs as cov
from code_longitudinal import run_longitudinal_production as nls
from code_longitudinal import run_nls_batch as nls_module
from code_longitudinal import run_r_ei_all_2x2 as king_r
from code_longitudinal import run_rxc_panel_extension_v11 as rxc
from reproducibility import replication_complete as pipeline
from reproducibility.estimation_recovery import BatchEstimationError


def _scope(*, base=(), extension=(), pairs=()):
    return SimpleNamespace(
        name="court", is_full=False, base_nls_pairs=frozenset(base),
        extension_nls_pairs=frozenset(extension), pairs=frozenset(pairs),
    )


def test_krt_supervisor_and_child_preserve_frozen_row_kwargs_and_seed(tmp_path, monkeypatch):
    row = pipeline.read_json(pipeline.CONTRACT / "krt_replay_240.json")["entries"][0]
    monkeypatch.setattr(pipeline, "STATE_DIR", tmp_path / ".runtime")
    monkeypatch.setattr(pipeline, "get_scope", lambda: _scope(pairs={(row["election_id"], row["scenario_id"])}))
    monkeypatch.setattr(nls, "_keep_system_awake", lambda: nullcontext())
    validations = []

    def validate(candidate, required=False):
        assert candidate == row
        validations.append(required)
        return (tmp_path / "saved", {"run_id": "saved-krt"}) if required else None

    supervised = []
    monkeypatch.setattr(pipeline, "_validated_krt_run", validate)
    monkeypatch.setattr(pipeline, "run_supervised", lambda command, **kwargs: supervised.append((command, kwargs)))
    result = pipeline.execute_krt_contract_rows([row], supervise=True)
    assert result[0]["result"]["run_id"] == "saved-krt"
    command, kwargs = supervised[0]
    assert command == [
        sys.executable, "-m", "reproducibility.replication_complete", "estimation-worker",
        "--scope", "court", "--estimation-family", "krt",
        "--estimation-key", row["reference_run_id"],
    ]
    assert kwargs["family"] == "krt" and kwargs["key"] == row["reference_run_id"]
    assert validations == [False, True]

    scientific = []

    def run_2x2(election, scenario, model, **settings):
        scientific.append((election.election_id, scenario.scenario_id, model, settings))
        return {"status": "success", "run_id": "saved-krt"}

    monkeypatch.setattr(krt_module, "run_2x2", run_2x2)
    pipeline._run_krt_contract_row(row)
    election, scenario, model, settings = scientific[0]
    assert (election, scenario, model) == (row["election_id"], row["scenario_id"], "krt_beta_binomial")
    assert settings["sample_size"] == 2000
    assert settings["panel_path"] == panel_module.PANEL_PATH
    assert settings["skip_preflight"] is True and settings["progressbar"] is False
    assert settings["run_metadata"]["reference_run_id"] == row["reference_run_id"]
    assert {name: settings[name] for name in row["arguments"]} == row["arguments"]
    assert settings["random_seed"] == row["arguments"]["random_seed"]


def test_krt_parent_rejects_supervisor_without_saved_outputs(tmp_path, monkeypatch):
    row = pipeline.read_json(pipeline.CONTRACT / "krt_replay_240.json")["entries"][0]
    monkeypatch.setattr(pipeline, "STATE_DIR", tmp_path / ".runtime")
    monkeypatch.setattr(pipeline, "get_scope", lambda: _scope())
    monkeypatch.setattr(nls, "_keep_system_awake", lambda: nullcontext())
    monkeypatch.setattr(pipeline, "run_supervised", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        pipeline, "_validated_krt_run",
        lambda candidate, required=False: (_ for _ in ()).throw(
            pipeline.ReplicationError("missing KRT outputs")
        ) if required else None,
    )
    with pytest.raises(BatchEstimationError, match="estimation"):
        pipeline.execute_krt_contract_rows([row], supervise=True)


def test_nls_and_rxc_supervisors_preserve_pair_and_common_child_contract(tmp_path, monkeypatch):
    base_pair = ("pre_2017_r1", "H0A")
    extension_pair = ("pre_2017_r1", "RXC1")
    scope = _scope(base={base_pair}, extension={extension_pair})
    monkeypatch.setattr(nls, "ROOT", tmp_path)
    monkeypatch.setattr(nls, "OUTPUT_DIR", tmp_path / "outputs")
    monkeypatch.setattr(nls, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(nls, "get_scope", lambda: scope)
    plan = pd.DataFrame([{
        "election_id": base_pair[0], "scenario_id": base_pair[1],
        "preparation_status": "admissible", "preparation_reason": "",
    }])
    monkeypatch.setattr(nls, "_ensure_inputs", lambda: (plan, {"panel_id": "panel-fixture"}))
    monkeypatch.setattr(nls, "_filtered_plan", lambda *args, **kwargs: plan)
    index_calls = []

    def success_index(panel_id):
        index_calls.append(panel_id)
        return {} if len(index_calls) == 1 else {base_pair: {"run_id": "base-run"}}

    monkeypatch.setattr(nls, "_nls_success_index", success_index)
    checked = []
    monkeypatch.setattr(nls, "_require_nls_saved_outputs", checked.append)
    monkeypatch.setattr(nls, "_save_progress", lambda *args: None)
    parent_calls = []
    monkeypatch.setattr(nls, "run_supervised", lambda command, **kwargs: parent_calls.append((command, kwargs)))
    result = nls.run_nls_longitudinal(supervise=True)
    assert result["success_or_resumed"] == 1 and checked == ["base-run"]
    command, kwargs = parent_calls[0]
    assert command[-6:] == ["--scope", "court", "--estimation-family", "nls", "--estimation-key", "pre_2017_r1__H0A"]
    assert kwargs["family"] == "nls" and kwargs["key"] == "pre_2017_r1__H0A"

    # RxC uses the same internal NLS worker, changing only the audited pair and
    # family label used by the watchdog.
    audit = tmp_path / "audit.csv"
    audit.write_text("fixture\n1\n", encoding="utf-8")
    monkeypatch.setattr(rxc, "ROOT", tmp_path)
    monkeypatch.setattr(rxc, "get_scope", lambda: scope)
    monkeypatch.setattr(rxc, "file_sha256", lambda path: rxc.EXPECTED_PANEL_SHA256)
    monkeypatch.setattr(rxc, "eligible_deferred_pairs", lambda frame: [extension_pair])
    monkeypatch.setattr(rxc, "_write_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(rxc, "_existing_success_run_id", lambda *args: "rxc-run")
    monkeypatch.setattr(rxc, "validate_prepared_pair", lambda *args, **kwargs: {"n_rows": 2000})
    monkeypatch.setattr(rxc, "_require_nls_saved_outputs", checked.append)
    monkeypatch.setattr(rxc, "run_supervised", lambda command, **kwargs: parent_calls.append((command, kwargs)))
    rows = rxc.run_extension(
        audit_path=audit, panel_path=tmp_path / "panel.parquet",
        output_dir=tmp_path / "rxc", supervise=True,
    )
    assert rows[0]["run_id"] == "rxc-run" and checked[-1] == "rxc-run"
    command, kwargs = parent_calls[-1]
    assert command[-6:] == ["--scope", "court", "--estimation-family", "nls_rxc", "--estimation-key", "pre_2017_r1__RXC1"]
    assert kwargs["family"] == "nls_rxc" and kwargs["key"] == "pre_2017_r1__RXC1"

    # Exercise the shared child entrypoint and assert the original estimator
    # receives exactly the historical pair/panel/sample-size/force contract.
    child_calls = []

    def scientific(election, scenario, **settings):
        child_calls.append((election.election_id, scenario.scenario_id, settings))
        return {"status": "success", "run_id": "child-run"}

    monkeypatch.setenv("LONGITUDINAL_RAW_ARCHIVES", "fixture")
    monkeypatch.setattr(pipeline, "activate_runtime_panel_hash", lambda: None)
    monkeypatch.setattr(pipeline, "get_scope", lambda: scope)
    monkeypatch.setattr(nls_module, "run_nls", scientific)
    monkeypatch.setattr(panel_module, "load_longitudinal_panel_manifest", lambda: {"panel_id": "panel-fixture"})
    monkeypatch.setattr(nls, "_nls_success_index", lambda panel_id: {
        base_pair: {"run_id": "child-run"}, extension_pair: {"run_id": "child-run"},
    })
    monkeypatch.setattr(nls, "_require_nls_saved_outputs", checked.append)
    pipeline.estimation_worker("nls", "pre_2017_r1__H0A")
    pipeline.estimation_worker("nls_rxc", "pre_2017_r1__RXC1")
    assert [(a, b) for a, b, _ in child_calls] == [base_pair, extension_pair]
    assert all(settings == {
        "sample_size": 2000, "panel_path": panel_module.PANEL_PATH, "force": False,
    } for _, _, settings in child_calls)


def test_nls_and_rxc_parent_validators_reject_missing_outputs(tmp_path, monkeypatch):
    pair = ("pre_2017_r1", "H0A")
    scope = _scope(base={pair}, extension={pair})
    monkeypatch.setattr(nls, "ROOT", tmp_path)
    monkeypatch.setattr(nls, "OUTPUT_DIR", tmp_path / "outputs")
    monkeypatch.setattr(nls, "get_scope", lambda: scope)
    plan = pd.DataFrame([{"election_id": pair[0], "scenario_id": pair[1],
                         "preparation_status": "admissible", "preparation_reason": ""}])
    monkeypatch.setattr(nls, "_ensure_inputs", lambda: (plan, {"panel_id": "panel"}))
    monkeypatch.setattr(nls, "_filtered_plan", lambda *args, **kwargs: plan)
    sequence = iter(({}, {pair: {"run_id": "missing"}}))
    monkeypatch.setattr(nls, "_nls_success_index", lambda panel_id: next(sequence))
    monkeypatch.setattr(nls, "run_supervised", lambda *args, **kwargs: None)
    monkeypatch.setattr(nls, "_save_progress", lambda *args: None)
    monkeypatch.setattr(nls, "_require_nls_saved_outputs",
                        lambda run_id: (_ for _ in ()).throw(RuntimeError("missing NLS outputs")))
    with pytest.raises(BatchEstimationError):
        nls.run_nls_longitudinal(supervise=True)

    audit = tmp_path / "audit.csv"
    audit.write_text("fixture\n1\n", encoding="utf-8")
    monkeypatch.setattr(rxc, "ROOT", tmp_path)
    monkeypatch.setattr(rxc, "get_scope", lambda: scope)
    monkeypatch.setattr(rxc, "file_sha256", lambda path: rxc.EXPECTED_PANEL_SHA256)
    monkeypatch.setattr(rxc, "eligible_deferred_pairs", lambda frame: [pair])
    monkeypatch.setattr(rxc, "_write_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(rxc, "_existing_success_run_id", lambda *args: "missing")
    monkeypatch.setattr(rxc, "validate_prepared_pair", lambda *args, **kwargs: {"n_rows": 2000})
    monkeypatch.setattr(rxc, "run_supervised", lambda *args, **kwargs: None)
    monkeypatch.setattr(rxc, "_require_nls_saved_outputs",
                        lambda run_id: (_ for _ in ()).throw(RuntimeError("missing RxC outputs")))
    with pytest.raises(BatchEstimationError):
        rxc.run_extension(audit_path=audit, panel_path=tmp_path / "panel.parquet",
                          output_dir=tmp_path / "rxc", supervise=True)


def test_covariate_supervisor_preserves_row_spec_optimizer_settings_and_validates_outputs(
    tmp_path, monkeypatch,
):
    row = {"election_id": "pre_2017_r1", "scenario_id": "H0A",
           "input_csv": str(tmp_path / "input.csv"), "source_manifest": "manifest.json"}
    spec = "demographic_foreign_share"
    output = tmp_path / "covariates"
    monkeypatch.setattr(cov, "ROOT", tmp_path)
    monkeypatch.setattr(cov, "load_scope", lambda expected_pairs=None: [row])
    monkeypatch.setattr(cov, "build_covariate_lookup", lambda scope: {row["election_id"]: object()})
    monkeypatch.setattr(cov, "get_scope", lambda: _scope(pairs={(row["election_id"], row["scenario_id"])}))
    monkeypatch.setattr(cov, "consolidate", lambda root, count: {"successful_runs": count})
    calls = []

    def supervise(command, **kwargs):
        calls.append((command, kwargs))
        run = output / "runs" / f"{row['election_id']}__{row['scenario_id']}__{spec}"
        run.mkdir(parents=True, exist_ok=True)
        (run / "estimates.csv").write_text("estimate\n0.5\n", encoding="utf-8")
        (run / "coefficients.csv").write_text("estimate\n0.1\n", encoding="utf-8")
        (run / "manifest.json").write_text(json.dumps({
            "status": "success", "election_id": row["election_id"],
            "scenario_id": row["scenario_id"], "spec_id": spec,
            "random_seed": cov.stable_seed(row["election_id"], row["scenario_id"], spec),
        }), encoding="utf-8")

    monkeypatch.setattr(cov, "run_supervised", supervise)
    monkeypatch.setattr(sys, "argv", [
        "cov", "--output-root", str(output), "--spec", spec, "--supervise",
        "--n-starts", "7", "--max-nfev", "345",
    ])
    cov.main()
    command, kwargs = calls[0]
    assert command[command.index("--internal-election-id") + 1] == row["election_id"]
    assert command[command.index("--internal-scenario-id") + 1] == row["scenario_id"]
    assert command[command.index("--internal-spec-id") + 1] == spec
    assert command[command.index("--n-starts") + 1] == "7"
    assert command[command.index("--max-nfev") + 1] == "345"
    assert kwargs["family"] == "covariate"
    manifest = json.loads((output / "runs" / f"{row['election_id']}__{row['scenario_id']}__{spec}" /
                           "manifest.json").read_text(encoding="utf-8"))
    assert manifest["random_seed"] == cov.stable_seed(row["election_id"], row["scenario_id"], spec)

    # A success manifest is insufficient: deleting one saved table must make
    # the parent reject the run before it can be consolidated or certified.
    (output / "runs" / f"{row['election_id']}__{row['scenario_id']}__{spec}" /
     "estimates.csv").unlink()
    with pytest.raises(BatchEstimationError):
        cov.main()


def test_king_r_supervisor_preserves_command_seed_isolated_environment_and_validates_outputs(
    tmp_path, monkeypatch,
):
    pair = ("pre_2017_r1", "H0A")
    scope = _scope(pairs={pair})
    source = tmp_path / "pre_2017_r1__H0A__panel__n2000.csv"
    source.write_text("value\n1\n", encoding="utf-8")
    monkeypatch.setattr(king_r, "ROOT", tmp_path)
    monkeypatch.setattr(king_r, "RUN_DIR", tmp_path / "r_runs")
    monkeypatch.setattr(king_r, "R_PROJECT_LIBRARY", tmp_path / "r_library")
    monkeypatch.setattr(king_r, "PROGRESS_PATH", tmp_path / "progress.parquet")
    monkeypatch.setattr(king_r, "STATUS_PATH", tmp_path / "status.json")
    monkeypatch.setattr(king_r, "get_scope", lambda: scope)
    monkeypatch.setattr(king_r, "_reference_seeds", lambda: {pair: 987654})
    monkeypatch.setattr(king_r, "load_longitudinal_panel_manifest",
                        lambda: {"panel_id": "panel", "panel_sha256": "panel-hash"})
    monkeypatch.setattr(king_r, "_rscript_path", lambda: Path("Rscript-fixture.exe"))
    monkeypatch.setattr(king_r, "_model_ready_inputs", lambda panel, scenarios: [source])
    monkeypatch.setattr(king_r, "_wait_for_memory", lambda *args: None)
    monkeypatch.setattr(king_r, "_memory_snapshot", lambda: {"allowed": True})
    calls = []

    def supervise(command, **kwargs):
        calls.append((command, kwargs))
        out = Path(command[4])
        out.mkdir(parents=True, exist_ok=True)
        for name in ("commune_latent_summaries_r.csv", "aggregate_summaries_r.csv"):
            (out / name).write_text("value\n1\n", encoding="utf-8")
        (out / "manifest_r.json").write_text(json.dumps({
            "status": "success", "n_communes": 2000,
            "scenario_id": pair[1], "election_id": pair[0], "seed": 987654,
            "input_sha256": king_r.file_sha256(source),
            "mathematical_identity_with_python_model": False,
        }), encoding="utf-8")

    monkeypatch.setattr(king_r, "run_supervised", supervise)
    result = king_r.run(scenarios=("H0A",), supervise=True)
    assert result["pairs_successful"] == 1
    command, kwargs = calls[0]
    assert command == [
        "Rscript-fixture.exe", "--vanilla", str(king_r.R_SCRIPT), str(source),
        str(king_r.RUN_DIR / "pre_2017_r1__H0A"), "987654",
    ]
    assert kwargs["family"] == "king_r" and kwargs["key"] == "pre_2017_r1__H0A"
    environment = kwargs["environment"]
    assert environment["R_LIBS_USER"] == str(king_r.R_PROJECT_LIBRARY.resolve())
    assert environment["R_LIBS"] == environment["R_LIBS_SITE"] == ""

    # A zero/successful child without the required saved table is not reusable.
    (king_r.RUN_DIR / "pre_2017_r1__H0A" / "aggregate_summaries_r.csv").unlink()
    monkeypatch.setattr(king_r, "run_supervised", lambda *args, **kwargs: None)
    with pytest.raises(BatchEstimationError):
        king_r.run(scenarios=("H0A",), supervise=True)
