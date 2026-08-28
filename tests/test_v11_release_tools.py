from code_longitudinal.build_v11_audit_notebook import _code, _markdown, _validate_structure
from code_longitudinal.h23_supervisor import (
    POLL_SECONDS,
    _account_for_suspend,
    _all_h23_pairs,
    _pause_after_requested_pair,
    _semantic_or_resource_failures,
)
from code_longitudinal.package_v11_release import _production_module_closure
from code_longitudinal.paths import ROOT
from code_longitudinal.release_scope import load_release_scope


def test_v11_h23_pair_scope_is_derived_and_unique() -> None:
    scope = load_release_scope(ROOT / "config" / "releases" / "v1.1.json")
    pairs = _all_h23_pairs(scope)
    assert len(pairs) == 52
    assert len(set(pairs)) == 52
    assert {scenario_id for _, scenario_id in pairs} == {"H2", "H3"}


def test_legacy_gate_reason_parser_keeps_krt_nls_separate_from_retryable_mcmc() -> None:
    evaluation = {
        "gate_reasons": (
            "mcmc_not_fail|krt_nls_distance_le_0_15|strengthened_rerun_required"
        )
    }
    assert _semantic_or_resource_failures(evaluation) == ["krt_nls_distance_le_0_15"]
    assert _semantic_or_resource_failures(
        evaluation,
        defer_unstable_estimate_alerts=True,
    ) == []


def test_resource_failure_is_never_deferred_with_unstable_estimate() -> None:
    evaluation = {
        "gate_reasons": "memory_under_80pct_available|krt_nls_distance_le_0_15"
    }
    assert _semantic_or_resource_failures(
        evaluation,
        defer_unstable_estimate_alerts=True,
    ) == ["memory_under_80pct_available"]


def test_supervisor_active_clock_excludes_windows_suspend_gap() -> None:
    suspended, detected = _account_for_suspend(
        now=8 * 60 * 60 + POLL_SECONDS,
        last_poll=0.0,
        suspended_wall_seconds=0.0,
    )
    assert detected is True
    assert suspended == 8 * 60 * 60
    active_elapsed = 8 * 60 * 60 + POLL_SECONDS - suspended
    assert active_elapsed == POLL_SECONDS


def test_supervisor_active_clock_keeps_normal_poll_gap() -> None:
    suspended, detected = _account_for_suspend(
        now=POLL_SECONDS,
        last_poll=0.0,
        suspended_wall_seconds=12.5,
    )
    assert detected is False
    assert suspended == 12.5


def test_supervisor_requested_pair_pause_is_explicit(tmp_path) -> None:
    status_path = tmp_path / "status.json"
    state = {"status": "running"}
    assert _pause_after_requested_pair(
        requested=("leg_2022_r1", "H2"),
        completed=("leg_2022_r1", "H2"),
        status_path=status_path,
        state=state,
    )
    assert state["status"] == "paused_after_requested_pair"
    assert state["pause_reason"] == "user_requested_transfer_after_current_fit"


def test_v11_bundle_excludes_historical_entrypoints() -> None:
    modules = _production_module_closure()
    assert "v11_pipeline" in modules
    assert "h23_supervisor" in modules
    assert "deliver_v11_report_html" in modules
    assert "render_v11_report_pdf" in modules
    assert "benchmark_krt_backend_2000" in modules
    assert "audit_v11_candidate" in modules
    assert "render_scoped_report_pdf" not in modules
    assert "package_release_v101" not in modules
    assert "run_priority_production" not in modules


def test_compact_audit_notebook_uses_valid_v4_structure() -> None:
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [_markdown("# Audit"), _code("print('ok')")],
    }
    _validate_structure(notebook)
