from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

from code_longitudinal.output_schema import LATENT_COLUMNS, LONGITUDINAL_COLUMNS, empty_frame
from code_longitudinal.paths import OUTPUT_DIR
from code_longitudinal.extract_latent_densities import (
    _select_largest_plot_views,
    _with_scopes,
)
from code_longitudinal.plot_election_2022 import _fit_quality
from code_longitudinal.run_2x2_batch import extract_latent_summaries, next_ladder_gate
from code_longitudinal.run_pilot_ladder import EXTENSION_SCENARIOS, PILOT_SCENARIOS
from code_longitudinal import run_registry
from code_longitudinal.spec_registry import ELECTIONS, SCENARIO_BY_ID, planned_run_rows


def test_registry_has_26_elections_and_declared_runs() -> None:
    assert len(ELECTIONS) == 26
    rows = planned_run_rows()
    assert rows
    assert any(row["scenario_id"] == "H0A" for row in rows)
    assert not any(row["scenario_id"] == "H6" and int(row["year"]) < 1986 for row in rows)


def test_extended_pilot_declares_every_missing_hypothesis_for_three_elections() -> None:
    expected_extension = {"H0B", "H0C", "H2", "H3", "H4"}
    assert set(EXTENSION_SCENARIOS) == {"leg_1962_r1", "leg_1986_r1", "leg_2022_r1"}
    assert all(set(values) == expected_extension for values in EXTENSION_SCENARIOS.values())
    assert sum(len(values) for values in PILOT_SCENARIOS.values()) == 28


def test_main_output_schema_is_stable() -> None:
    frame = empty_frame(LONGITUDINAL_COLUMNS)
    assert frame.columns.tolist() == LONGITUDINAL_COLUMNS


def test_latent_extraction_uses_precinct_posterior() -> None:
    xr = __import__("xarray")
    scenario = SCENARIO_BY_ID["H0A"]
    posterior = xr.Dataset(
        {
            "b_1": (("precinct", "chain", "draw"), np.array([[[0.2, 0.4]], [[0.5, 0.7]]])),
            "b_2": (("precinct", "chain", "draw"), np.array([[[0.6, 0.8]], [[0.1, 0.3]]])),
        }
    )
    trace = type("Trace", (), {"posterior": posterior})()
    frame = pd.DataFrame(
        {
            "sample_id": ["p", "p"],
            "election_id": ["e", "e"],
            "scenario_id": ["H0A", "H0A"],
            "unit_id": ["01001", "01002"],
            "sample_rank": [1, 2],
            "N__target_group": [40, 60],
            "N__complement_group": [60, 40],
        }
    )
    result = extract_latent_summaries(trace, frame, scenario, run_id="r", run_key="k", model_key="m")
    assert result.columns.tolist() == LATENT_COLUMNS
    assert np.allclose(result["b1_mean"], [0.3, 0.6])
    assert np.allclose(result["b2_q50"], [0.7, 0.2])
    assert result[["b1_mean", "b2_mean"]].ge(0).all().all()
    assert result[["b1_mean", "b2_mean"]].le(1).all().all()


def test_king_krt_common_scope_is_the_exact_intersection() -> None:
    rows = []
    for model, units in (("king_truncated_normal", ["a", "b", "c"]), ("krt_beta_binomial", ["b", "c", "d"])):
        for rank, unit_id in enumerate(units):
            rows.append(
                {
                    "sample_id": "panel",
                    "election_id": "leg_2022_r1",
                    "scenario_id": "H6",
                    "model_key": model,
                    "unit_id": unit_id,
                    "sample_rank": rank,
                }
            )
    scoped = _with_scopes(pd.DataFrame(rows))
    common = scoped.loc[scoped["comparison_scope"].eq("common_intersection")]
    for _, part in common.groupby("model_key"):
        assert set(part["unit_id"]) == {"b", "c"}


def test_density_selection_prefers_the_largest_exact_common_rung() -> None:
    joint_rows = []
    marginal_rows = []
    for n, comparison in ((25, "small"), (3000, "large")):
        for model in ("king_truncated_normal", "krt_beta_binomial"):
            run_id = f"{model}-{n}"
            for unit_id in ("a", "b"):
                joint_rows.append(
                    {
                        "run_id": run_id,
                        "sample_id": "panel",
                        "election_id": "leg_2022_r1",
                        "scenario_id": "H6",
                        "model_key": model,
                        "comparison_key": comparison,
                        "n_communes_requested": n,
                        "draws": 20,
                        "tune": 20,
                        "chains": 1,
                        "comparison_scope": "common_intersection",
                        "unit_id": unit_id,
                    }
                )
            marginal_rows.append(
                {
                    "run_id": run_id,
                    "comparison_scope": "common_intersection",
                    "marker": n,
                }
            )
    marginal, joint, selection = _select_largest_plot_views(
        pd.DataFrame(marginal_rows), pd.DataFrame(joint_rows)
    )
    assert set(joint["comparison_key"]) == {"large"}
    assert set(marginal["marker"]) == {3000}
    assert selection["n_communes_requested"].eq(3000).all()


def test_successful_run_is_resumed_without_overwrite(monkeypatch) -> None:
    output_dir = Path(__file__).parent / "runtime_registry" / "outputs"
    runs_dir = output_dir / "runs"
    output_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(run_registry, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(run_registry, "RUNS_DIR", runs_dir)
    parameters = {"case": uuid4().hex}
    handle = run_registry.begin_run(stage="test", parameters=parameters)
    assert handle is not None
    run_registry.finish_run(handle, status="success", metadata={"diagnostic_status": "pass"})
    manifest_before = (handle.run_dir / "manifest.json").read_bytes()

    resumed = run_registry.begin_run(stage="test", parameters=parameters)

    assert resumed is None
    assert (handle.run_dir / "manifest.json").read_bytes() == manifest_before
    assert len(run_registry.read_registry().loc[lambda frame: frame["run_key"].eq(handle.run_key)]) == 1
    (handle.run_dir / "manifest.json").unlink()
    handle.run_dir.rmdir()
    (output_dir / "run_registry_executed.csv").unlink()
    runs_dir.rmdir()
    output_dir.rmdir()


def test_ladder_gate_requires_both_time_and_memory_budget() -> None:
    settings = {
        "mcmc": {
            "ladder": [25, 100],
            "max_estimated_hours_per_fit": 12,
            "max_memory_fraction": 0.8,
        }
    }
    allowed = next_ladder_gate(25, 10, settings, peak_memory_mb=100, available_memory_mb=2000)
    assert allowed["allowed"] is True
    assert allowed["predicted_seconds"] == 40
    assert allowed["predicted_peak_memory_mb"] == 400

    blocked = next_ladder_gate(25, 10, settings, peak_memory_mb=500, available_memory_mb=2000)
    assert blocked["allowed"] is False
    assert blocked["reason"] == "predicted_memory_exceeds_budget"


def test_2022_fit_quality_uses_x_times_probability_matrix() -> None:
    data = pd.DataFrame(
        {
            "N_g": [100, 100],
            "X__g1": [1.0, 0.25],
            "X__g2": [0.0, 0.75],
            "Y__v1": [80, 35],
            "Y__v2": [20, 65],
        }
    )
    matrix = pd.DataFrame([[0.8, 0.2], [0.2, 0.8]], index=["g1", "g2"], columns=["v1", "v2"])

    metrics, observed, predicted = _fit_quality(data, matrix, "synthetic")

    assert np.allclose(predicted, [[0.8, 0.2], [0.35, 0.65]])
    assert np.allclose(predicted, observed)
    assert np.allclose(metrics[["rmse", "mae", "max_absolute_error"]], 0)


def test_consolidated_beta_estimates_keep_one_row_per_commune_parameter() -> None:
    beta = pd.read_parquet(OUTPUT_DIR / "commune_beta_estimates.parquet")
    assert not beta.empty
    assert not beta.duplicated(["run_id", "unit_id", "beta_parameter"]).any()
    assert set(beta["beta_parameter"]) == {"b_1", "b_2"}
    assert beta["estimate_basis"].eq("commune_posterior_mean").all()
    assert beta[["estimate", "q025", "q50", "q975"]].apply(pd.to_numeric).apply(lambda column: column.between(0, 1).all()).all()
