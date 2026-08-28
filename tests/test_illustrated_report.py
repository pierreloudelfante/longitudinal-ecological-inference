from __future__ import annotations

import pandas as pd
import pytest

from code_longitudinal.build_illustrated_report import build_comparison_table


def _selection() -> pd.DataFrame:
    rows = []
    for model, run_id in (
        ("king_truncated_normal", "run_king"),
        ("krt_beta_binomial", "run_krt"),
    ):
        rows.append(
            {
                "election_id": "leg_1962_r1",
                "scenario_id": "H0A",
                "selection_scope": "largest_common_intersection",
                "model_key": model,
                "run_id": run_id,
                "comparison_key": "common",
                "n_communes_requested": 2,
                "n_communes_selected": 2,
                "draws": 20,
                "tune": 20,
                "chains": 1,
                "diagnostic_status": "fail",
            }
        )
    return pd.DataFrame(rows)


def _joint() -> pd.DataFrame:
    rows = []
    for run_id, shift in (("run_king", 0.0), ("run_krt", 0.1)):
        for unit_id, b1, b2, w1, w2 in (
            ("01001", 0.2, 0.5, 10.0, 5.0),
            ("01002", 0.4, 0.7, 30.0, 5.0),
        ):
            rows.append(
                {
                    "run_id": run_id,
                    "comparison_key": "common",
                    "comparison_scope": "common_intersection",
                    "unit_id": unit_id,
                    "b1_mean": b1 + shift,
                    "b2_mean": b2 + shift,
                    "b1_weight": w1,
                    "b2_weight": w2,
                }
            )
    return pd.DataFrame(rows)


def test_comparison_table_uses_exact_common_units_and_equal_commune_mean() -> None:
    result = build_comparison_table(_selection(), _joint())
    assert len(result) == 4
    king_b1 = result.loc[
        result["model_key"].eq("king_truncated_normal")
        & result["beta_parameter"].eq("b_1")
    ].iloc[0]
    assert king_b1["n_communes_selected"] == 2
    assert king_b1["mean_equal_commune"] == pytest.approx(0.3)
    assert king_b1["mean_social_weighted"] == pytest.approx(0.35)
    assert king_b1["estimate_basis"] == "mean_of_commune_posterior_means"


def test_comparison_table_rejects_non_exact_king_krt_intersection() -> None:
    joint = _joint()
    joint.loc[joint["run_id"].eq("run_krt") & joint["unit_id"].eq("01002"), "unit_id"] = "99999"
    try:
        build_comparison_table(_selection(), joint)
    except ValueError as error:
        assert "Intersection King/KRT non exacte" in str(error)
    else:
        raise AssertionError("A non-exact intersection must fail explicitly")


def test_comparison_table_accepts_the_eight_canonical_professor_scenarios() -> None:
    scenarios = ("H0A", "H0B", "H0C", "H1", "H2", "H3", "H4", "H5")
    selection_frames = []
    joint_frames = []
    for scenario_id in scenarios:
        scenario_selection = _selection().copy()
        scenario_selection["scenario_id"] = scenario_id
        scenario_selection["run_id"] = scenario_selection["run_id"].map(
            lambda run_id: f"{run_id}_{scenario_id}"
        )
        scenario_joint = _joint().copy()
        scenario_joint["run_id"] = scenario_joint["run_id"].map(
            lambda run_id: f"{run_id}_{scenario_id}"
        )
        selection_frames.append(scenario_selection)
        joint_frames.append(scenario_joint)

    result = build_comparison_table(
        pd.concat(selection_frames, ignore_index=True),
        pd.concat(joint_frames, ignore_index=True),
        scenario_order=scenarios,
    )

    assert len(result) == 32
    assert set(result["scenario_id"]) == set(scenarios)
    assert not result.duplicated(
        ["election_id", "scenario_id", "model_key", "beta_parameter"]
    ).any()
