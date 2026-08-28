from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from code_longitudinal import finalize_priority_results_3000 as finalizer
from code_longitudinal.prepare_inputs import x_columns, y_columns
from code_longitudinal.spec_registry import SCENARIO_BY_ID


def _parameters(election_id: str, scenario_id: str, panel_path: Path | None = None) -> dict[str, object]:
    return {
        "election_id": election_id,
        "scenario_id": scenario_id,
        **finalizer.FIXED_PARAMETERS,
        "cores": 1,
        "random_seed": 20260802,
        **({"panel_path": str(panel_path)} if panel_path is not None else {}),
    }


def _write_manifest(
    run_dir: Path,
    election_id: str,
    scenario_id: str,
    input_path: Path | None = None,
    *,
    panel_path: Path | None = None,
    panel_sha256: str | None = None,
) -> None:
    manifest = {
        "status": "success",
        "election_id": election_id,
        "scenario_id": scenario_id,
        "n_communes_used": 3000,
        "parameters": _parameters(election_id, scenario_id, panel_path),
        "preparation_manifest": {"panel_source_sha256": panel_sha256} if panel_sha256 else {},
        "input_sha256": {} if input_path is None else {str(input_path): "synthetic"},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _progress(runs_dir: Path, *, failed_item: str | None = None) -> Path:
    panel_path = runs_dir.parent / "panel.csv"
    pd.DataFrame({"unit_id": np.arange(3000).astype(str)}).to_csv(panel_path, index=False)
    panel_sha256 = finalizer.file_sha256(panel_path)
    items: dict[str, dict[str, object]] = {}
    for idx, item_id in enumerate(finalizer.required_item_ids()):
        election_id, scenario_id, _ = item_id.split("__")
        run_id = f"run_{idx}"
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True)
        _write_manifest(
            run_dir,
            election_id,
            scenario_id,
            panel_path=panel_path,
            panel_sha256=panel_sha256,
        )
        items[item_id] = {
            "status": "pending" if item_id == failed_item else "success",
            "run_id": run_id,
            "panel_sha256": panel_sha256,
            **_parameters(election_id, scenario_id, panel_path),
        }
    payload = {
        "configuration": {**finalizer.FIXED_PARAMETERS},
        "panel": {
            "n_communes": 3000,
            "panel_path": str(panel_path),
            "panel_sha256": panel_sha256,
        },
        "items": items,
    }
    path = runs_dir.parent / "progress.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_completion_gate_requires_all_six_successes_and_fixed_contract(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    progress = _progress(runs_dir)

    fits = finalizer.load_completed_required_fits(progress, runs_dir)

    assert len(fits) == 6
    assert {fit.scenario_id for fit in fits} == {"H0A", "H1"}
    assert {fit.year for fit in fits} == {1962, 1986, 2022}

    blocked = _progress(tmp_path / "blocked_runs", failed_item=finalizer.required_item_ids()[2])
    with pytest.raises(RuntimeError, match="finalisation refusée"):
        finalizer.load_completed_required_fits(blocked, tmp_path / "blocked_runs")


def test_compute_artifacts_is_drawwise_uses_canonical_diag_and_builds_18k_latents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fits: list[finalizer.CompletedFit] = []
    for index, item_id in enumerate(finalizer.required_item_ids()):
        election_id, scenario_id, _ = item_id.split("__")
        run_dir = tmp_path / f"run_{index}"
        run_dir.mkdir()
        scenario = SCENARIO_BY_ID[scenario_id]
        unit_id = np.arange(3000).astype(str)
        input_frame = pd.DataFrame({
            "unit_id": unit_id,
            "N_g": np.full(3000, 100.0),
            x_columns(scenario)[0]: np.linspace(.1, .9, 3000),
            y_columns(scenario)[0]: np.full(3000, 35.0),
        })
        input_path = run_dir / "input.parquet"
        input_frame.to_parquet(input_path, index=False)
        _write_manifest(run_dir, election_id, scenario_id, input_path)
        latent = pd.DataFrame({
            "unit_id": unit_id,
            "sample_rank": np.arange(1, 3001),
            "b1_weight": np.full(3000, 30.0),
            "b2_weight": np.full(3000, 70.0),
            "b1_mean": np.linspace(.2, .4, 3000),
            "b2_mean": np.linspace(.5, .3, 3000),
        })
        latent.to_parquet(run_dir / "commune_latent_summaries.parquet", index=False)
        diagnostic = {
            "diagnostic_schema_version": "mcmc_diagnostics_v2.0", "fit_status": "success", "mcmc_status": "pass",
            "saved_chains": 4, "saved_draws_per_chain": 1000, "max_rhat": 1.04, "min_ess_bulk": 150,
            "min_ess_tail": 200, "min_bfmi": .8, "divergences": 0, "divergence_fraction": 0.0,
            "max_treedepth_hits": 0, "max_treedepth_hit_fraction": 0.0,
            "thresholds": {
                "rhat_pass": 1.01, "rhat_fail": 1.05,
                "ess_bulk_pass": 400.0, "ess_bulk_fail": 100.0,
                "ess_tail_pass": 400.0, "ess_tail_fail": 100.0,
                "bfmi_pass": 0.3, "bfmi_fail": 0.2,
                "divergence_fraction_fail": 0.001, "treedepth_fraction_fail": 0.01,
            },
            "variable_metrics": [
                {"variable": "b_1", "block": "latent_preferences", "n_parameters": 3000,
                 "max_rhat": 1.005, "min_ess_bulk": 850.0, "min_ess_tail": 760.0},
                {"variable": "b_2", "block": "latent_preferences", "n_parameters": 3000,
                 "max_rhat": 1.006, "min_ess_bulk": 800.0, "min_ess_tail": 700.0},
                {"variable": "c_1", "block": "hyperparameters", "n_parameters": 1,
                 "max_rhat": 1.04, "min_ess_bulk": 150.0, "min_ess_tail": 200.0},
            ],
            "block_metrics": [
                {"block": "latent_preferences", "variables": ["b_1", "b_2"], "n_parameters": 6000,
                 "max_rhat": 1.006, "min_ess_bulk": 800.0, "min_ess_tail": 700.0},
                {"block": "hyperparameters", "variables": ["c_1", "c_2", "d_1", "d_2"], "n_parameters": 4,
                 "max_rhat": 1.04, "min_ess_bulk": 150.0, "min_ess_tail": 200.0},
            ],
        }
        (run_dir / "mcmc_diagnostics_v2.json").write_text(json.dumps(diagnostic), encoding="utf-8")
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        fits.append(finalizer.CompletedFit(item_id, election_id, scenario_id, finalizer._year(election_id), f"run_{index}", run_dir, {}, manifest))

    def fake_draws(*_args: object, **_kwargs: object) -> xr.Dataset:
        # Values deliberately vary by draw: a mean-of-means implementation would
        # not produce the q025/q975 values asserted below.
        b1 = np.tile(np.array([[[.20], [.40], [.60], [.80]]]), (4, 250, 1))
        b2 = np.tile(np.array([[[.70], [.50], [.30], [.10]]]), (4, 250, 1))
        return xr.Dataset({
            "b_1_group_weighted": (("chain", "draw"), b1[:, :, 0]),
            "b_2_group_weighted": (("chain", "draw"), b2[:, :, 0]),
        })

    monkeypatch.setattr(finalizer, "aggregate_krt_trace_files_v2", fake_draws)
    artifacts = finalizer.compute_artifacts(fits, verify_run_exports=False)

    assert len(artifacts["aggregates"]) == 12  # six runs x two corrected group aggregates
    assert set(artifacts["aggregates"]["aggregation_method"]) == {"group_specific_population_v2"}
    assert len(artifacts["contrasts"]) == 6
    assert len(artifacts["changes"]) == 6
    assert len(artifacts["estimands"]) == 18
    assert set(artifacts["estimands"]["estimand"]) == {
        "beta_1_aggregate", "beta_2_aggregate", "beta_1_minus_beta_2"
    }
    assert set(artifacts["estimands"]["estimand_mcmc_status"]) == {"pass"}
    assert np.isfinite(
        artifacts["estimands"][["rhat", "ess_bulk", "ess_tail", "mcse_mean"]].to_numpy(float)
    ).all()
    assert (artifacts["changes"]["resamples"] == 50_000).all()
    assert (artifacts["changes"]["random_seed"] == finalizer.CHANGE_SEED).all()
    assert len(artifacts["joint_latent"]) == 18_000
    assert artifacts["joint_latent"].duplicated(["scenario_id", "year", "unit_id"]).sum() == 0
    assert set(artifacts["diagnostics"]["beta_diagnostic_status"]) == {"pass"}
    assert set(artifacts["diagnostics"]["non_beta_parameter_status"]) == {"caveat"}
    assert set(artifacts["diagnostics"]["mcmc_status"]) == {"caveat"}
    assert set(artifacts["diagnostics"]["mcmc_assessment_label"]) == {"satisfaisant avec réserve"}
    assert "selected_for_interpretation" not in artifacts["diagnostics"]
    assert artifacts["diagnostics"]["retained_for_descriptive_reporting"].all()
    assert set(artifacts["diagnostics"]["reporting_status"]).issubset({"retained", "retained_with_caveats"})
    assert set(artifacts["identification"]["identification_schema_version"]) == {"ecological_identification_v2.0"}


def test_beta_scope_diagnostic_keeps_beta_metrics_and_adds_non_beta_reserve() -> None:
    source = {
        "diagnostic_schema_version": "mcmc_diagnostics_v2.0",
        "fit_status": "success",
        "mcmc_status": "caveat",
        "saved_chains": 4,
        "saved_draws_per_chain": 1000,
        "max_rhat": 1.04,
        "min_ess_bulk": 150.0,
        "min_ess_tail": 200.0,
        "min_bfmi": 0.8,
        "divergences": 0,
        "divergence_fraction": 0.0,
        "max_treedepth_hits": 0,
        "max_treedepth_hit_fraction": 0.0,
        "variable_metrics": [
            {"variable": "b_1", "block": "latent_preferences", "n_parameters": 3000,
             "max_rhat": 1.005, "min_ess_bulk": 850.0, "min_ess_tail": 760.0},
            {"variable": "b_2", "block": "latent_preferences", "n_parameters": 3000,
             "max_rhat": 1.006, "min_ess_bulk": 800.0, "min_ess_tail": 700.0},
            {"variable": "c_1", "block": "hyperparameters", "n_parameters": 1,
             "max_rhat": 1.04, "min_ess_bulk": 150.0, "min_ess_tail": 200.0},
        ],
        "block_metrics": [
            {"block": "latent_preferences", "variables": ["b_1", "b_2"], "n_parameters": 6000,
             "max_rhat": 1.006, "min_ess_bulk": 800.0, "min_ess_tail": 700.0},
            {"block": "hyperparameters", "variables": ["c_1", "c_2", "d_1", "d_2"], "n_parameters": 4,
             "max_rhat": 1.04, "min_ess_bulk": 150.0, "min_ess_tail": 200.0},
        ],
    }

    published = finalizer.beta_scope_diagnostic(source)

    assert published["beta_diagnostic_status"] == "pass"
    assert published["non_beta_parameter_status"] == "caveat"
    assert published["mcmc_status"] == "caveat"
    assert published["mcmc_assessment"] == "satisfactory_with_reserve"
    assert published["mcmc_assessment_label"] == "satisfaisant avec réserve"
    assert published["max_rhat"] == 1.006
    assert published["min_ess_bulk"] == 800.0
    assert published["min_ess_tail"] == 700.0
    assert published["posterior_variables"] == ["b_1", "b_2"]
    assert published["beta_parameter_count"] == 6000
    assert {row["variable"] for row in published["beta_variable_metrics"]} == {"b_1", "b_2"}


def test_canonical_diagnostic_rejects_wrong_saved_draws(tmp_path: Path) -> None:
    path = tmp_path / "mcmc_diagnostics_v2.json"
    path.write_text(json.dumps({
        "diagnostic_schema_version": "mcmc_diagnostics_v2.0", "fit_status": "success", "mcmc_status": "pass",
        "saved_chains": 4, "saved_draws_per_chain": 999,
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="1 000 draws"):
        finalizer.canonical_diagnostic(tmp_path)
