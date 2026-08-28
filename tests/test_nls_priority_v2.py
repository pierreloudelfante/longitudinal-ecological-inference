from __future__ import annotations

from pathlib import Path

from code_longitudinal.run_nls_priority_v2 import (
    MODEL_KEY,
    PRIORITY_ELECTIONS,
    PRIORITY_SCENARIOS,
    build_plan,
    full_series_scope,
    priority_scope,
    resume_decision,
)
from code_longitudinal.spec_registry import ELECTION_BY_ID, SCENARIO_BY_ID, scenario_is_allowed


TEST_SETTINGS = {
    "n_starts": 4,
    "start_scale": 0.5,
    "n_start_strata": 5,
    "max_nfev": 100,
    "tolerance": 1e-9,
    "random_seed": 11,
}


def test_priority_scope_is_exact_four_by_three_cross_product() -> None:
    scope = priority_scope()
    assert len(scope) == 12
    assert set(scope) == {
        (election_id, scenario_id)
        for election_id in PRIORITY_ELECTIONS
        for scenario_id in PRIORITY_SCENARIOS
    }


def test_priority_plan_requires_exact_common_3000_and_is_deterministic() -> None:
    kwargs = {
        "panel_path": Path("panel/common-v2.csv"),
        "panel_sha256": "a" * 64,
        "settings": TEST_SETTINGS,
    }
    first = build_plan(**kwargs)
    second = build_plan(**kwargs)
    assert len(first) == 12
    assert first["require_exact_3000"].all()
    assert first["sample_size"].eq(3000).all()
    assert first["model_key"].eq(MODEL_KEY).all()
    assert first["run_key"].tolist() == second["run_key"].tolist()
    assert not first.duplicated(["election_id", "scenario_id"]).any()


def test_full_series_scope_contains_only_authorised_2x2_pairs() -> None:
    scope = full_series_scope()
    assert len(scope) > 12
    assert len(scope) == len(set(scope))
    for election_id, scenario_id in scope:
        scenario = SCENARIO_BY_ID[scenario_id]
        election = ELECTION_BY_ID[election_id]
        assert scenario.model_family == "2x2"
        assert scenario_is_allowed(scenario, election)
    full_plan = build_plan(
        full_series=True,
        panel_path=Path("panel/common-v2.csv"),
        panel_sha256="b" * 64,
        settings=TEST_SETTINGS,
    )
    assert len(full_plan) == len(scope)
    assert not full_plan["require_exact_3000"].any()


def test_resume_skips_only_verified_success_or_active_running() -> None:
    manifest = Path(__file__)
    assert resume_decision(None) == "run"
    assert resume_decision({"status": "failed"}) == "run"
    assert resume_decision({"status": "success", "attempt_manifest": str(manifest)}) == "skip_success"
    assert resume_decision({"status": "success", "attempt_manifest": str(manifest.with_name("missing-attempt.json"))}) == "run"
    assert resume_decision({"status": "running"}) == "skip_running"
    assert resume_decision({"status": "running"}, retry_running=True) == "run"
