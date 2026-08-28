from __future__ import annotations

from pathlib import Path
import inspect

import pytest

from code_longitudinal.run_priority_production_v2 import (
    CHAINS,
    CORES,
    DRAWS,
    ELECTIONS,
    MAX_TREEDEPTH,
    MODEL_KEY,
    PANEL_PATH,
    SAMPLE_SIZE,
    SCENARIOS,
    SKIP_PREFLIGHT_REASON,
    TARGET_ACCEPT,
    TUNE,
    _runner_kwargs,
    build_plan,
    estimate_remaining_seconds,
    new_progress,
    parse_args,
    pending_items,
    reconcile_progress,
    select_item_ids,
    validate_exact_panel,
)
from code_longitudinal.run_2x2_batch import run_2x2


def _metadata() -> dict[str, object]:
    return {
        "panel_path": str(PANEL_PATH.resolve()),
        "panel_sha256": "abc123",
        "sample_id": "panel_3000_common_1962_1986_2022_seed_20260802_v2",
        "n_communes": 3000,
    }


def test_parse_is_safe_and_production_parameters_are_not_overridable() -> None:
    args = parse_args(
        [
            "--dry-run",
            "--retry-failed",
            "--initial-hours-per-fit",
            "8.5",
            "--scenario",
            "H0A",
            "--scenario",
            "H1",
        ]
    )
    assert args.dry_run is True
    assert args.retry_failed is True
    assert args.initial_hours_per_fit == 8.5
    assert args.scenario == ["H0A", "H1"]
    with pytest.raises(SystemExit):
        parse_args(["--draws", "20"])


def test_exact_real_panel_contract() -> None:
    metadata = validate_exact_panel(PANEL_PATH)
    assert metadata["n_communes"] == 3000
    assert metadata["sample_id"] == "panel_3000_common_1962_1986_2022_seed_20260802_v2"
    assert len(metadata["panel_sha256"]) == 64


def test_plan_is_exactly_four_hypotheses_times_three_periods() -> None:
    plan = build_plan(_metadata())
    assert len(plan) == 12
    assert {item["scenario_id"] for item in plan} == set(SCENARIOS)
    assert {item["election_id"] for item in plan} == set(ELECTIONS)
    assert {item["model_key"] for item in plan} == {MODEL_KEY}
    for item in plan:
        assert item["sample_size"] == SAMPLE_SIZE
        assert item["chains"] == CHAINS == 4
        assert item["tune"] == TUNE == 1000
        assert item["draws"] == DRAWS == 1000
        assert item["cores"] == CORES == 1
        assert item["target_accept"] == TARGET_ACCEPT == 0.99
        assert item["max_treedepth"] == MAX_TREEDEPTH == 14
        assert item["skip_preflight"] is True
        assert item["skip_preflight_reason"] == SKIP_PREFLIGHT_REASON


def test_targeted_selection_keeps_the_full_plan_identity() -> None:
    plan = build_plan(_metadata())
    selected = select_item_ids(plan, scenarios=["H0A", "H1"])

    assert len(plan) == 12
    assert len(selected) == 6
    assert selected == [
        "leg_1962_r1__H0A__krt_beta_binomial",
        "leg_1986_r1__H0A__krt_beta_binomial",
        "leg_2022_r1__H0A__krt_beta_binomial",
        "leg_1962_r1__H1__krt_beta_binomial",
        "leg_1986_r1__H1__krt_beta_binomial",
        "leg_2022_r1__H1__krt_beta_binomial",
    ]


def test_runner_kwargs_require_exact_panel_and_explicit_preflight_reason() -> None:
    item = build_plan(_metadata())[0]
    kwargs = _runner_kwargs(item)
    assert kwargs["panel_path"] == Path(_metadata()["panel_path"])
    assert kwargs["skip_preflight"] is True
    assert "explicit_user_request_exact_common_panel_3000" in kwargs["preflight_override_reason"]
    assert kwargs["cores"] == 1
    assert set(kwargs).issubset(inspect.signature(run_2x2).parameters)


def test_resume_requeues_interrupted_fit_but_preserves_completed_and_failed() -> None:
    plan = build_plan(_metadata())
    progress = new_progress(plan, _metadata(), now="2026-08-04T10:00:00+00:00")
    progress["items"][plan[0]["item_id"]]["status"] = "success"
    progress["items"][plan[1]["item_id"]]["status"] = "running"
    progress["items"][plan[2]["item_id"]]["status"] = "failed"

    resumed = reconcile_progress(
        progress,
        plan,
        _metadata(),
        now="2026-08-04T11:00:00+00:00",
    )
    assert resumed["items"][plan[0]["item_id"]]["status"] == "success"
    assert resumed["items"][plan[1]["item_id"]]["status"] == "pending"
    assert "recovered_interrupted_runner" in resumed["items"][plan[1]["item_id"]]["error"]
    assert resumed["items"][plan[2]["item_id"]]["status"] == "failed"
    assert len(pending_items(resumed, plan)) == 10
    assert len(pending_items(resumed, plan, retry_failed=True)) == 11


def test_eta_uses_median_success_duration_and_counts_pending() -> None:
    plan = build_plan(_metadata())
    progress = new_progress(plan, _metadata())
    progress["items"][plan[0]["item_id"]].update(status="success", elapsed_seconds=3600)
    progress["items"][plan[1]["item_id"]].update(status="success", elapsed_seconds=7200)
    estimate = estimate_remaining_seconds(progress, plan)
    assert estimate["remaining_fits"] == 10
    assert estimate["seconds_per_fit"] == 5400
    assert estimate["estimated_remaining_hours"] == 15
    assert estimate["method"] == "median_completed_v2_fit"


def test_resume_rejects_different_panel_or_plan() -> None:
    plan = build_plan(_metadata())
    progress = new_progress(plan, _metadata())
    other_panel = {**_metadata(), "panel_sha256": "different"}
    with pytest.raises(ValueError, match="autre version du panel"):
        reconcile_progress(progress, plan, other_panel)

    shorter = plan[:-1]
    with pytest.raises(ValueError, match="autre plan"):
        reconcile_progress(progress, shorter, _metadata())
