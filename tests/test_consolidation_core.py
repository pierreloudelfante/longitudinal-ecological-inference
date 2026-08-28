from __future__ import annotations

import pandas as pd

from code_longitudinal.consolidation_core import build_krt_aggregate


def test_build_krt_aggregate_uses_stored_contrast_without_trace(tmp_path) -> None:
    run_dir = tmp_path / "run_without_trace"
    run_dir.mkdir()
    pd.DataFrame(
        {
            "b1_weight": [40.0, 50.0],
            "b2_weight": [60.0, 70.0],
        }
    ).to_parquet(run_dir / "commune_latent_summaries.parquet", index=False)
    pd.DataFrame(
        [
            {
                "beta_parameter": "b_1",
                "aggregation_method": "group_specific_population_v2",
                "weight_basis": "N1",
                "mean": 0.40,
                "q025": 0.30,
                "q50": 0.40,
                "q975": 0.50,
                "n_posterior_draws": 4000,
            },
            {
                "beta_parameter": "b_2",
                "aggregation_method": "group_specific_population_v2",
                "weight_basis": "N2",
                "mean": 0.25,
                "q025": 0.20,
                "q50": 0.25,
                "q975": 0.30,
                "n_posterior_draws": 4000,
            },
            {
                "beta_parameter": "b_1_minus_b_2",
                "aggregation_method": "group_specific_population_v2",
                "weight_basis": "group_specific_population_v2",
                "mean": 0.15,
                "q025": 0.04,
                "q50": 0.14,
                "q975": 0.26,
                "n_posterior_draws": 4000,
            },
        ]
    ).to_csv(run_dir / "aggregate_comparison_v2.csv", index=False)
    manifest = {
        "run_id": "stored-contrast-run",
        "status": "success",
        "election_id": "leg_1962_r1",
        "scenario_id": "H0A",
        "model_key": "krt_beta_binomial",
        "panel_id": "panel-2000",
        "diagnostic_status": "pass",
        "draws": 1000,
        "tune": 1000,
        "chains": 4,
        "target_accept": 0.99,
        "max_treedepth": 14,
        "king_lambda": 0.5,
        "identification_diagnostic": {"identification_status": "caveat"},
    }

    assert not (run_dir / "trace.nc").exists()
    result = build_krt_aggregate([(run_dir, manifest)])

    assert set(result["estimand"]) == {"b_1", "b_2", "b_1_minus_b_2"}
    contrast = result.loc[result["estimand"].eq("b_1_minus_b_2")].iloc[0]
    assert contrast["mean"] == 0.15
    assert contrast["median"] == 0.14
    assert contrast["q025"] == 0.04
    assert contrast["q975"] == 0.26
    assert contrast["n_posterior_draws"] == 4000
    assert contrast["weight_total"] == 220.0
