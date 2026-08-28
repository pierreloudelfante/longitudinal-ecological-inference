from __future__ import annotations

import json

import numpy as np
import pandas as pd

from code_longitudinal import compare_python_r_krt_exact_all_2x2 as comparison
from code_longitudinal import consolidate_r_krt_exact_all_2x2 as consolidation
from code_longitudinal.run_r_krt_exact_all_2x2 import MAX_FIT_SECONDS, R_SCRIPT
from code_longitudinal.utils import file_sha256


def test_nimble_runner_preserves_bom_unit_id_and_named_diagnostics():
    assert MAX_FIT_SECONDS == 43_200
    script = R_SCRIPT.read_text(encoding="utf-8")
    assert 'fileEncoding = "UTF-8-BOM"' in script
    assert "rhat = posterior::rhat" in script
    assert "ess_bulk = posterior::ess_bulk" in script
    assert "ess_tail = posterior::ess_tail" in script
    stan_reference = R_SCRIPT.with_name("run_krt_replication.R").read_text(
        encoding="utf-8"
    )
    assert 'fileEncoding = "UTF-8-BOM"' in stan_reference


def test_nimble_non_nuts_diagnostic_thresholds():
    classify = consolidation._rhat_ess_status
    assert classify(1.01, 400, 400) == ("pass", "pass")
    assert classify(1.02, 250, 250) == ("caveat", "caveat_modere")
    assert classify(1.04, 150, 150) == ("caveat", "caveat_severe")
    assert classify(1.051, 500, 500) == ("fail", "fail")
    assert classify(1.0, 99, 500) == ("fail", "fail")
    assert classify(np.nan, 500, 500) == ("fail", "fail")


def test_exact_r_consolidation_and_python_comparison(monkeypatch, tmp_path):
    run_root = tmp_path / "runs"
    run_dir = run_root / "leg_1962_r1__H0A"
    run_dir.mkdir(parents=True)
    unit_ids = pd.Series([f"{index:05d}" for index in range(2000)], dtype="string")
    model_ready = pd.DataFrame(
        {
            "unit_id": unit_ids,
            "panel_id": "panel_test_2000",
            "year": 1962,
            "round": 1,
            "sample_rank": np.arange(1, 2001),
            "N_g": 100,
            "N__target_group": 40,
            "N__complement_group": 60,
        }
    )
    input_csv = tmp_path / "model_ready.csv"
    model_ready.to_csv(input_csv, index=False)

    commune_parts = []
    for parameter, mean in (("b_1", 0.4), ("b_2", 0.3)):
        commune_parts.append(
            pd.DataFrame(
                {
                    "panel_id": "panel_test_2000",
                    "election_id": "leg_1962_r1",
                    "scenario_id": "H0A",
                    "model_key": "krt_beta_binomial_nimble_r_exact",
                    "unit_id": unit_ids,
                    "sample_rank": np.arange(1, 2001),
                    "parameter": parameter,
                    "mean": mean,
                    "sd": 0.05,
                    "q025": mean - 0.1,
                    "q50": mean,
                    "q975": mean + 0.1,
                }
            )
        )
    pd.concat(commune_parts, ignore_index=True).to_csv(
        run_dir / "commune_latent_summaries_r.csv", index=False
    )
    pd.DataFrame(
        {
            "panel_id": "panel_test_2000",
            "election_id": "leg_1962_r1",
            "scenario_id": "H0A",
            "model_key": "krt_beta_binomial_nimble_r_exact",
            "estimand": ["beta1_aggregate", "beta2_aggregate", "contrast_aggregate"],
            "mean": [0.4, 0.3, 0.1],
            "sd": [0.01, 0.01, 0.02],
            "q025": [0.38, 0.28, 0.06],
            "q50": [0.4, 0.3, 0.1],
            "q975": [0.42, 0.32, 0.14],
            "n_posterior_draws": 4000,
        }
    ).to_csv(run_dir / "aggregate_summaries_r.csv", index=False)
    pd.DataFrame(
        {
            "variable": ["c_1", "b_1[1]"],
            "rhat": [1.0, 1.01],
            "ess_bulk": [900.0, 800.0],
            "ess_tail": [850.0, 750.0],
        }
    ).to_csv(run_dir / "parameter_diagnostics_r.csv", index=False)
    manifest = {
        "status": "success",
        "model": "exact_reimplementation_of_pyei_ei_beta_binom_model",
        "panel_id": "panel_test_2000",
        "election_id": "leg_1962_r1",
        "scenario_id": "H0A",
        "n_communes": 2000,
        "chains": 4,
        "warmup": 1000,
        "draws_per_chain": 1000,
        "seed": 123,
        "king_lambda": 0.5,
        "compile_seconds": 1.0,
        "sample_seconds": 2.0,
        "sampler": "test_sampler",
        "input_csv": str(input_csv),
        "input_sha256": file_sha256(input_csv),
        "runner_script_sha256": file_sha256(R_SCRIPT),
    }
    (run_dir / "manifest_r.json").write_text(json.dumps(manifest), encoding="utf-8")

    r_commune_path = tmp_path / "r_commune.parquet"
    r_aggregate_path = tmp_path / "r_aggregate.parquet"
    r_diagnostics_path = tmp_path / "r_diagnostics.csv"
    r_manifest_path = tmp_path / "r_consolidation.json"
    monkeypatch.setattr(consolidation, "RUN_DIR", run_root)
    monkeypatch.setattr(consolidation, "REPLICATION_DIR", tmp_path)
    monkeypatch.setattr(consolidation, "COMMUNE_PATH", r_commune_path)
    monkeypatch.setattr(consolidation, "AGGREGATE_PATH", r_aggregate_path)
    monkeypatch.setattr(consolidation, "DIAGNOSTICS_PATH", r_diagnostics_path)
    monkeypatch.setattr(consolidation, "MANIFEST_PATH", r_manifest_path)
    monkeypatch.setattr(consolidation, "EXPECTED_PAIRS", 1)
    monkeypatch.setattr(consolidation, "EXPECTED_ELECTIONS", {"H0A": 1})
    consolidated = consolidation.consolidate()
    assert consolidated["ready"] is True
    assert consolidated["commune_rows"] == 2000
    assert consolidated["aggregate_rows"] == 3

    python_commune_path = tmp_path / "python_commune.parquet"
    python_aggregate_path = tmp_path / "python_aggregate.parquet"
    python_commune = pd.DataFrame(
        {
            "election_id": "leg_1962_r1",
            "scenario_id": "H0A",
            "unit_id": unit_ids,
            "b1_mean": 0.4,
            "b2_mean": 0.3,
        }
    )
    python_commune.to_parquet(python_commune_path, index=False)
    pd.DataFrame(
        {
            "election_id": "leg_1962_r1",
            "scenario_id": "H0A",
            "estimand": ["b_1", "b_2", "b_1_minus_b_2"],
            "mean": [0.4, 0.3, 0.1],
            "median": [0.4, 0.3, 0.1],
            "q025": [0.38, 0.28, 0.06],
            "q975": [0.42, 0.32, 0.14],
            "run_id": "python_test_run",
        }
    ).to_parquet(python_aggregate_path, index=False)

    aggregate_comparison_path = tmp_path / "aggregate_comparison.csv"
    commune_comparison_path = tmp_path / "commune_comparison.csv"
    comparison_manifest_path = tmp_path / "comparison.json"
    monkeypatch.setattr(comparison, "PYTHON_COMMUNE_PATH", python_commune_path)
    monkeypatch.setattr(comparison, "PYTHON_AGGREGATE_PATH", python_aggregate_path)
    monkeypatch.setattr(comparison, "R_COMMUNE_PATH", r_commune_path)
    monkeypatch.setattr(comparison, "R_AGGREGATE_PATH", r_aggregate_path)
    monkeypatch.setattr(comparison, "R_CONSOLIDATION_MANIFEST_PATH", r_manifest_path)
    monkeypatch.setattr(comparison, "AGGREGATE_COMPARISON_PATH", aggregate_comparison_path)
    monkeypatch.setattr(comparison, "COMMUNE_COMPARISON_PATH", commune_comparison_path)
    monkeypatch.setattr(comparison, "MANIFEST_PATH", comparison_manifest_path)
    monkeypatch.setattr(comparison, "EXPECTED_PAIRS", 1)
    compared = comparison.compare()
    assert compared["ready"] is True
    assert compared["matched_aggregate_pairs"] == 1
    assert compared["matched_commune_pairs"] == 1
    assert compared["maximum_aggregate_absolute_difference"] < 1e-12
    assert compared["aggregate_interval_overlap_rate"] == 1.0
