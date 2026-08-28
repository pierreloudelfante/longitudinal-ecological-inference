from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import psutil
from pandas.testing import assert_frame_equal

from .h23_pilot_gate import (
    audit_pilot_inputs,
    evaluate_krt_run,
    intervals_compatible,
)
from .paths import OUTPUT_DIR, ROOT, RUNS_DIR
from .release_scope import ReleaseScope, load_release_scope
from .run_registry import mark_run_interrupted
from .scoped_finalizer import finalize_scoped_release
from .spec_registry import ELECTIONS, SPEC_VERSION
from .utils import write_json


MAX_FIT_SECONDS = 12 * 60 * 60
MEMORY_SHARE_LIMIT = 0.80
MEMORY_FLOOR_MB = 1024.0
POLL_SECONDS = 15.0
SUSPEND_GAP_SECONDS = 4 * POLL_SECONDS
SOURCE_V102 = ROOT / "work" / "longitudinal_2000_v1.0.2_H0A_H1_validated"
SOURCE_V102_CONFIG = ROOT / "config" / "releases" / "v1.0.2.json"


class UnresolvedAfterRerunError(RuntimeError):
    """The single preregistered strengthened rerun did not validate a pair."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _account_for_suspend(
    *,
    now: float,
    last_poll: float,
    suspended_wall_seconds: float,
) -> tuple[float, bool]:
    """Exclude an operating-system suspension from the active fit clock."""
    gap = max(0.0, now - last_poll)
    if gap <= SUSPEND_GAP_SECONDS:
        return suspended_wall_seconds, False
    # Preserve one expected poll interval as active work and subtract only the
    # excess gap. This prevents Windows sleep from consuming the 12-hour fit
    # budget while keeping ordinary scheduler delays in the active duration.
    return suspended_wall_seconds + max(0.0, gap - POLL_SECONDS), True


def _production_dir(scope: ReleaseScope) -> Path:
    path = OUTPUT_DIR / SPEC_VERSION / "production" / scope.release_id
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def _keep_system_awake() -> object:
    if os.name != "nt":
        yield
        return
    es_continuous = 0x80000000
    es_system_required = 0x00000001
    previous = ctypes.windll.kernel32.SetThreadExecutionState(es_continuous | es_system_required)
    if previous == 0:
        raise OSError("SetThreadExecutionState failed")
    try:
        yield
    finally:
        ctypes.windll.kernel32.SetThreadExecutionState(es_continuous)


def _extension_scenarios(scope: ReleaseScope) -> tuple[str, ...]:
    source_scope = load_release_scope(SOURCE_V102_CONFIG)
    scenarios = tuple(
        scenario_id
        for scenario_id in scope.krt_scenarios
        if scenario_id not in source_scope.krt_scenarios
    )
    if not scenarios:
        raise ValueError("release configuration does not add any KRT scenario")
    return scenarios


def _all_h23_pairs(scope: ReleaseScope) -> tuple[tuple[str, str], ...]:
    extension_scenarios = _extension_scenarios(scope)
    return tuple(
        (election.election_id, scenario_id)
        for election in ELECTIONS
        for scenario_id in extension_scenarios
    )


def _running_manifests(scope: ReleaseScope, election_id: str, scenario_id: str, *, rerun: bool) -> list[Path]:
    expected_seed = scope.run_seed(scenario_id, election_id, rerun=rerun)
    paths: list[Path] = []
    for manifest_path in RUNS_DIR.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        parameters = manifest.get("parameters", {})
        if not isinstance(parameters, dict):
            continue
        if (
            manifest.get("status") == "running"
            and parameters.get("release_id") == scope.release_id
            and parameters.get("election_id") == election_id
            and parameters.get("scenario_id") == scenario_id
            and int(parameters.get("random_seed", -1)) == expected_seed
        ):
            paths.append(manifest_path)
    return paths


def _terminate_tree(process: subprocess.Popen[str]) -> None:
    try:
        parent = psutil.Process(process.pid)
    except psutil.Error:
        return
    children = parent.children(recursive=True)
    for child in children:
        try:
            child.terminate()
        except psutil.Error:
            pass
    try:
        parent.terminate()
    except psutil.Error:
        pass
    _, alive = psutil.wait_procs([*children, parent], timeout=10)
    for item in alive:
        try:
            item.kill()
        except psutil.Error:
            pass


def _close_stale_running(
    scope: ReleaseScope,
    election_id: str,
    scenario_id: str,
    *,
    rerun: bool,
    error: str,
) -> None:
    for manifest_path in _running_manifests(scope, election_id, scenario_id, rerun=rerun):
        mark_run_interrupted(manifest_path.parent, error=error)


def _memory_headroom_to_limit_mb(*, total_mb: float, available_mb: float) -> float:
    """Additional resident memory allowed before the global ceiling is hit."""
    return max(0.0, available_mb - (1.0 - MEMORY_SHARE_LIMIT) * total_mb)


def _wait_for_memory(
    status_path: Path,
    current: dict[str, Any],
    *,
    predicted_peak_memory_mb: float = MEMORY_FLOOR_MB,
) -> None:
    while True:
        memory = psutil.virtual_memory()
        available_mb = float(memory.available / (1024**2))
        total_mb = float(memory.total / (1024**2))
        # A new fit is admissible only when its predicted peak still leaves
        # at least (1 - MEMORY_SHARE_LIMIT) of total physical memory free.
        # Multiplying the currently available memory by the limit would not
        # enforce a global 80% ceiling when the workstation is already busy.
        headroom_mb = _memory_headroom_to_limit_mb(total_mb=total_mb, available_mb=available_mb)
        if predicted_peak_memory_mb <= headroom_mb:
            current.update({
                "memory_preflight": "pass",
                "available_memory_mb": available_mb,
                "total_memory_mb": total_mb,
                "predicted_peak_memory_mb": predicted_peak_memory_mb,
                "memory_headroom_to_limit_mb": headroom_mb,
            })
            write_json(status_path, current)
            return
        current.update({
            "memory_preflight": "waiting",
            "available_memory_mb": available_mb,
            "total_memory_mb": total_mb,
            "predicted_peak_memory_mb": predicted_peak_memory_mb,
            "memory_headroom_to_limit_mb": headroom_mb,
            "updated_at_utc": _utc_now(),
        })
        write_json(status_path, current)
        time.sleep(30)


def _execute_fit(
    scope: ReleaseScope,
    config_path: Path,
    election_id: str,
    scenario_id: str,
    *,
    rerun: bool,
    logs_dir: Path,
    status_path: Path,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    existing = evaluate_krt_run(scope, election_id, scenario_id, rerun=rerun)
    if existing is not None:
        return existing
    stale = _running_manifests(scope, election_id, scenario_id, rerun=rerun)
    if stale:
        for manifest_path in stale:
            mark_run_interrupted(
                manifest_path.parent,
                error="stale_running_manifest_found_before_supervised_retry",
            )
    _wait_for_memory(
        status_path,
        state,
        predicted_peak_memory_mb=MEMORY_FLOOR_MB * scope.mcmc.execution_cores,
    )
    suffix = "rerun" if rerun else "initial"
    stdout_path = logs_dir / f"{election_id}__{scenario_id}__{suffix}.stdout.log"
    stderr_path = logs_dir / f"{election_id}__{scenario_id}__{suffix}.stderr.log"
    command = [
        sys.executable,
        "-m",
        "code_longitudinal.v11_pipeline",
        "krt",
        "--release-config",
        str(config_path),
        "--election-id",
        election_id,
        "--scenario-id",
        scenario_id,
        "--cores",
        str(scope.mcmc.execution_cores),
    ]
    if rerun:
        command.append("--rerun")
    started = time.monotonic()
    last_poll = started
    suspended_wall_seconds = 0.0
    suspend_events = 0
    with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open("w", encoding="utf-8") as stderr_handle:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
        )
        peak_tree_mb = 0.0
        while process.poll() is None:
            now = time.monotonic()
            suspended_wall_seconds, suspended = _account_for_suspend(
                now=now,
                last_poll=last_poll,
                suspended_wall_seconds=suspended_wall_seconds,
            )
            if suspended:
                suspend_events += 1
            last_poll = now
            wall_elapsed = now - started
            active_elapsed = max(0.0, wall_elapsed - suspended_wall_seconds)
            try:
                root_process = psutil.Process(process.pid)
                members = [root_process, *root_process.children(recursive=True)]
                tree_mb = sum(
                    member.memory_info().rss
                    for member in members
                    if member.is_running()
                ) / (1024**2)
                peak_tree_mb = max(peak_tree_mb, tree_mb)
            except psutil.Error:
                pass
            state.update({
                "current_election_id": election_id,
                "current_scenario_id": scenario_id,
                "current_run_type": suffix,
                "child_pid": process.pid,
                "fit_elapsed_seconds": active_elapsed,
                "fit_active_elapsed_seconds": active_elapsed,
                "fit_wall_elapsed_seconds": wall_elapsed,
                "fit_suspended_wall_seconds": suspended_wall_seconds,
                "fit_suspend_events": suspend_events,
                "supervisor_observed_peak_tree_mb": peak_tree_mb,
                "updated_at_utc": _utc_now(),
            })
            write_json(status_path, state)
            if active_elapsed > MAX_FIT_SECONDS:
                _terminate_tree(process)
                _close_stale_running(
                    scope,
                    election_id,
                    scenario_id,
                    rerun=rerun,
                    error="supervisor_active_fit_timeout_12h",
                )
                return None
            time.sleep(POLL_SECONDS)
        return_code = process.returncode
    finished = time.monotonic()
    suspended_wall_seconds, suspended = _account_for_suspend(
        now=finished,
        last_poll=last_poll,
        suspended_wall_seconds=suspended_wall_seconds,
    )
    if suspended:
        suspend_events += 1
    wall_elapsed = finished - started
    active_elapsed = max(0.0, wall_elapsed - suspended_wall_seconds)
    state.update({
        "last_child_return_code": return_code,
        "last_fit_elapsed_seconds": active_elapsed,
        "last_fit_active_elapsed_seconds": active_elapsed,
        "last_fit_wall_elapsed_seconds": wall_elapsed,
        "last_fit_suspended_wall_seconds": suspended_wall_seconds,
        "last_fit_suspend_events": suspend_events,
        "last_supervisor_observed_peak_tree_mb": peak_tree_mb,
        "updated_at_utc": _utc_now(),
    })
    write_json(status_path, state)
    if return_code != 0:
        _close_stale_running(
            scope,
            election_id,
            scenario_id,
            rerun=rerun,
            error=f"supervised_child_exit_{return_code}",
        )
        return None
    return evaluate_krt_run(scope, election_id, scenario_id, rerun=rerun)


def _semantic_or_resource_failures(
    evaluation: dict[str, Any],
    *,
    defer_unstable_estimate_alerts: bool = False,
) -> list[str]:
    mcmc_retryable = {
        "mcmc_not_fail",
        "zero_divergences",
        "zero_treedepth_hits",
    }
    unstable_estimate_alerts = {
        "krt_nls_distance_le_0_15",
        "no_sustained_sign_opposition",
    }
    deferred = unstable_estimate_alerts if defer_unstable_estimate_alerts else set()
    reasons = [value for value in str(evaluation.get("gate_reasons", "")).split("|") if value]
    return [
        reason
        for reason in reasons
        if reason not in mcmc_retryable
        and reason not in deferred
        and reason != "strengthened_rerun_required"
    ]


def _write_estimate_alert_audit(
    status_path: Path,
    election_id: str,
    scenario_id: str,
    initial: dict[str, Any],
    *,
    rerun: dict[str, Any] | None = None,
) -> Path:
    path = status_path.parent / f"krt_nls_alert_audit__{election_id}__{scenario_id}.json"
    strengthened_rerun_expected = str(initial["mcmc_substatus"]) in {"caveat_severe", "fail"}
    payload: dict[str, Any] = {
        "audit_schema_version": "h23_krt_nls_alert_v1",
        "election_id": election_id,
        "scenario_id": scenario_id,
        "threshold_absolute_difference": 0.15,
        "initial_run_id": str(initial["run_id"]),
        "initial_mcmc_status": str(initial["mcmc_status"]),
        "initial_mcmc_substatus": str(initial["mcmc_substatus"]),
        "initial_krt_contrast": float(initial["krt_contrast"]),
        "canonical_nls_contrast": float(initial["nls_contrast"]),
        "initial_absolute_difference": float(initial["absolute_krt_nls_difference"]),
        "input_audit": "h23_pilot_input_audit.json",
        "input_margins_and_panel_status": "pass",
        "model_or_hyperparameter_adjustment": False,
        "decision": (
            "defer_substantive_alert_until_preregistered_strengthened_rerun"
            if strengthened_rerun_expected
            else "document_nonblocking_method_sensitivity_alert"
        ),
        "status": (
            "pending_strengthened_rerun"
            if strengthened_rerun_expected
            else "documented_nonblocking_alert"
        ),
        "created_at_utc": _utc_now(),
    }
    if rerun is not None:
        rerun_gate_pass = bool(rerun.get("core_gate_pass", False))
        payload.update({
            "rerun_run_id": str(rerun["run_id"]),
            "rerun_mcmc_status": str(rerun["mcmc_status"]),
            "rerun_mcmc_substatus": str(rerun["mcmc_substatus"]),
            "rerun_krt_contrast": float(rerun["krt_contrast"]),
            "rerun_absolute_difference": float(rerun["absolute_krt_nls_difference"]),
            "rerun_core_gate_pass": rerun_gate_pass,
            "rerun_gate_reasons": str(rerun.get("gate_reasons", "")),
            "status": "resolved_pass" if rerun_gate_pass else "resolved_fail",
            "resolved_at_utc": _utc_now(),
        })
    write_json(path, payload)
    return path


def _select_pair(
    scope: ReleaseScope,
    config_path: Path,
    election_id: str,
    scenario_id: str,
    *,
    logs_dir: Path,
    status_path: Path,
    state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    initial = _execute_fit(
        scope,
        config_path,
        election_id,
        scenario_id,
        rerun=False,
        logs_dir=logs_dir,
        status_path=status_path,
        state=state,
    )
    if initial is None:
        raise RuntimeError(f"initial fit unavailable after supervised execution: {election_id}/{scenario_id}")
    severity = str(initial["mcmc_substatus"])
    defer_estimate_alerts = severity in {"caveat_severe", "fail"}
    estimate_alert_present = str(initial.get("method_sensitivity_status", "pass")) == "alert"
    if estimate_alert_present:
        _write_estimate_alert_audit(status_path, election_id, scenario_id, initial)
    semantic_failures = _semantic_or_resource_failures(
        initial,
        defer_unstable_estimate_alerts=defer_estimate_alerts,
    )
    if semantic_failures:
        raise RuntimeError(
            f"non-MCMC pilot/production gate failure for {election_id}/{scenario_id}: "
            + "|".join(semantic_failures)
        )
    if severity in {"pass", "caveat_modere"}:
        if not initial["core_gate_pass"]:
            raise RuntimeError(f"initial gate failed unexpectedly: {election_id}/{scenario_id}")
        return initial, {
            "selection_reason": "initial_pass" if severity == "pass" else "initial_caveat_modere",
            "replaces_run_id": "",
            "compatibility": {},
        }

    rerun = _execute_fit(
        scope,
        config_path,
        election_id,
        scenario_id,
        rerun=True,
        logs_dir=logs_dir,
        status_path=status_path,
        state=state,
    )
    if rerun is None:
        raise RuntimeError(f"strengthened rerun unavailable: {election_id}/{scenario_id}")
    if estimate_alert_present:
        _write_estimate_alert_audit(status_path, election_id, scenario_id, initial, rerun=rerun)
    if str(rerun["mcmc_status"]) not in {"pass", "caveat"}:
        raise UnresolvedAfterRerunError(
            f"strengthened rerun remains fail: {election_id}/{scenario_id}"
        )
    if not rerun["core_gate_pass"]:
        raise UnresolvedAfterRerunError(
            f"strengthened rerun gate failure for {election_id}/{scenario_id}: {rerun['gate_reasons']}"
        )
    compatibility = intervals_compatible(initial, rerun)
    if not compatibility["compatible"]:
        raise UnresolvedAfterRerunError(
            f"initial/rerun estimates incompatible: {election_id}/{scenario_id}"
        )
    return rerun, {
        "selection_reason": "strengthened_rerun_after_" + severity,
        "replaces_run_id": initial["run_id"],
        "compatibility": compatibility,
    }


def _selection_row(evaluation: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "election_id": evaluation["election_id"],
        "scenario_id": evaluation["scenario_id"],
        "run_id": evaluation["run_id"],
        "panel_id": evaluation["panel_id"],
        "model_key": "krt_beta_binomial",
        "mcmc_status": evaluation["mcmc_status"],
        "mcmc_caveat_severity": evaluation["mcmc_substatus"],
        "identification_status": evaluation["identification_status"],
        "estimate_stability_status": "compatible" if decision["compatibility"] else "not_applicable_initial",
        "run_role": "canonical",
        "selected_reason": decision["selection_reason"],
        "replaces_run_id": decision["replaces_run_id"],
        "selection_rule_version": "h23_preregistered_selection_v1",
    }


def _write_partial(
    production_dir: Path,
    selections: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
) -> None:
    pd.DataFrame(selections).to_csv(
        production_dir / "h23_canonical_selection_partial.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(evaluations).to_csv(
        production_dir / "h23_run_evaluations.csv",
        index=False,
        encoding="utf-8-sig",
    )


def _pause_after_requested_pair(
    *,
    requested: tuple[str, str] | None,
    completed: tuple[str, str],
    status_path: Path,
    state: dict[str, Any],
) -> bool:
    if requested != completed:
        return False
    state.update({
        "status": "paused_after_requested_pair",
        "pause_reason": "user_requested_transfer_after_current_fit",
        "paused_after_election_id": completed[0],
        "paused_after_scenario_id": completed[1],
        "updated_at_utc": _utc_now(),
    })
    write_json(status_path, state)
    return True


def _write_pilot_gate(
    production_dir: Path,
    selections: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
    pilot_pairs: tuple[tuple[str, str], ...],
    *,
    allow_run_level_continuation: bool = False,
) -> dict[str, Any]:
    pilot_set = set(pilot_pairs)
    selected = [row for row in selections if (row["election_id"], row["scenario_id"]) in pilot_set]
    evaluated = [row for row in evaluations if (row["election_id"], row["scenario_id"]) in pilot_set]
    frame = pd.DataFrame(evaluated)
    frame.to_csv(production_dir / "h23_pilot_gate_supervised.csv", index=False, encoding="utf-8-sig")
    result = {
        "pilot_pairs_expected": len(pilot_pairs),
        "pilot_pairs_selected": len(selected),
        "go_for_remaining_runs": len(selected) == len(pilot_pairs),
        "run_level_continuation_authorized": bool(allow_run_level_continuation),
        "selection_run_ids": [row["run_id"] for row in selected],
        "created_at_utc": _utc_now(),
    }
    write_json(production_dir / "h23_pilot_gate_supervised.json", result)
    if not result["go_for_remaining_runs"] and not allow_run_level_continuation:
        raise RuntimeError("pilot gate did not authorize the remaining configured runs")
    return result


def _build_full_selection(
    production_dir: Path,
    h23_rows: list[dict[str, Any]],
    scope: ReleaseScope,
) -> Path:
    source_scope = load_release_scope(SOURCE_V102_CONFIG)
    source_path = SOURCE_V102 / "02_syntheses" / "canonical_run_selection.csv"
    source = pd.read_csv(source_path, dtype="string")
    source = source.loc[source["scenario_id"].isin(source_scope.krt_scenarios)].copy()
    h23 = pd.DataFrame(h23_rows)
    columns = list(dict.fromkeys([*source.columns, *h23.columns]))
    source = source.reindex(columns=columns)
    h23 = h23.reindex(columns=columns)
    selection = pd.concat([source, h23], ignore_index=True)
    selection = selection.sort_values(["scenario_id", "election_id"]).reset_index(drop=True)
    if len(selection) != scope.expected_krt_pairs:
        raise AssertionError(f"selection contains {len(selection)} rows; expected {scope.expected_krt_pairs}")
    if selection[["election_id", "scenario_id"]].duplicated().any():
        raise AssertionError("duplicate canonical election-scenario pair")
    path = production_dir / "canonical_run_selection.csv"
    selection.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _assert_exact_scientific_invariance(final_dir: Path, production_dir: Path) -> dict[str, Any]:
    source_scope = load_release_scope(SOURCE_V102_CONFIG)
    source_results = SOURCE_V102 / "01_resultats_python"
    files = (
        "longitudinal_krt_commune.parquet",
        "longitudinal_krt_aggregate.parquet",
        "longitudinal_nls.parquet",
    )
    keys = {
        "longitudinal_krt_commune.parquet": ["election_id", "scenario_id", "unit_id"],
        "longitudinal_krt_aggregate.parquet": ["election_id", "scenario_id", "estimand"],
        "longitudinal_nls.parquet": ["election_id", "scenario_id", "estimand_type", "social_group", "vote_category"],
    }
    results: dict[str, Any] = {}
    for filename in files:
        old = pd.read_parquet(source_results / filename)
        new = pd.read_parquet(final_dir / filename)
        if "scenario_id" in new:
            new = new.loc[new["scenario_id"].isin(source_scope.krt_scenarios)].copy()
        shared = [column for column in old.columns if column in new.columns]
        old_compare = old[shared].sort_values(keys[filename]).reset_index(drop=True)
        new_compare = new[shared].sort_values(keys[filename]).reset_index(drop=True)
        assert_frame_equal(old_compare, new_compare, check_exact=True, check_dtype=False)
        results[filename] = {
            "rows": len(old_compare),
            "shared_columns": len(shared),
            "exact": True,
        }
    payload = {
        "scope": "H0A-H1",
        "comparison": "v1.0.2_validated_to_v1.1",
        "exact": True,
        "tables": results,
        "created_at_utc": _utc_now(),
    }
    write_json(production_dir / "NUMERICAL_INVARIANCE_v1.0.2_to_v1.1.json", payload)
    return payload


def supervise(
    release_config_path: Path,
    *,
    stop_after_pair: tuple[str, str] | None = None,
    continue_after_failed_pilots: bool = False,
) -> dict[str, Any]:
    scope = load_release_scope(release_config_path)
    extension_scenarios = _extension_scenarios(scope)
    if len(extension_scenarios) != 2:
        raise ValueError("this supervised production requires exactly two configured extension scenarios")
    production_dir = _production_dir(scope)
    logs_dir = production_dir / "background" / "h23_supervisor"
    logs_dir.mkdir(parents=True, exist_ok=True)
    status_path = production_dir / "h23_supervisor_status.json"
    lock_path = production_dir / "h23_supervisor.lock.json"
    if lock_path.exists():
        previous = json.loads(lock_path.read_text(encoding="utf-8"))
        previous_pid = int(previous.get("pid", -1))
        if previous_pid > 0 and psutil.pid_exists(previous_pid):
            raise RuntimeError(f"another H2/H3 supervisor is running with PID {previous_pid}")
    write_json(lock_path, {"pid": os.getpid(), "started_at_utc": _utc_now()})
    all_pairs = _all_h23_pairs(scope)
    if stop_after_pair is not None and stop_after_pair not in set(all_pairs):
        raise ValueError(f"requested stop pair is outside the H2/H3 scope: {stop_after_pair}")
    pilot_pairs = list(scope.pilot_pairs)
    remaining_pairs = [pair for pair in all_pairs if pair not in set(scope.pilot_pairs)]
    state: dict[str, Any] = {
        "release_id": scope.release_id,
        "pid": os.getpid(),
        "status": "starting",
        "started_at_utc": _utc_now(),
        "pairs_expected": len(all_pairs),
        "pairs_selected": 0,
        "production_policy": (
            "explicit_user_authorized_run_level_continuation_20260825"
            if continue_after_failed_pilots
            else "preregistered_all_pilots_must_pass"
        ),
    }
    write_json(status_path, state)
    selections: list[dict[str, Any]] = []
    evaluations: list[dict[str, Any]] = []
    try:
        input_audit = audit_pilot_inputs(release_config_path)
        if not input_audit["ready_for_pilot_fits"]:
            raise RuntimeError("pilot input audit failed")
        with _keep_system_awake():
            for phase, pairs in (("pilots", pilot_pairs), ("production", remaining_pairs)):
                if phase == "production":
                    pilot_gate = _write_pilot_gate(
                        production_dir,
                        selections,
                        evaluations,
                        scope.pilot_pairs,
                        allow_run_level_continuation=continue_after_failed_pilots,
                    )
                    state["pilot_gate"] = pilot_gate
                state["phase"] = phase
                for election_id, scenario_id in pairs:
                    state.update({
                        "status": "running",
                        "current_election_id": election_id,
                        "current_scenario_id": scenario_id,
                        "updated_at_utc": _utc_now(),
                    })
                    write_json(status_path, state)
                    try:
                        evaluation, decision = _select_pair(
                            scope,
                            release_config_path,
                            election_id,
                            scenario_id,
                            logs_dir=logs_dir,
                            status_path=status_path,
                            state=state,
                        )
                    except (UnresolvedAfterRerunError, RuntimeError) as exc:
                        if phase != "pilots" and not continue_after_failed_pilots:
                            raise
                        failed = evaluate_krt_run(
                            scope,
                            election_id,
                            scenario_id,
                            rerun=True,
                        ) or evaluate_krt_run(scope, election_id, scenario_id, rerun=False)
                        if failed is None:
                            raise RuntimeError(
                                f"unresolved pair has no auditable completed attempt: {election_id}/{scenario_id}"
                            ) from exc
                        resolution = (
                            "unresolved_pilot_after_single_preregistered_rerun"
                            if phase == "pilots"
                            else "unresolved_production_pair_after_single_preregistered_rerun"
                        )
                        evaluations.append({
                            **failed,
                            "pilot_pair_resolution": resolution,
                            "pilot_pair_error": str(exc),
                        })
                        failure_key = "pilot_failures" if phase == "pilots" else "production_failures"
                        failures = list(state.get(failure_key, []))
                        failures.append({
                            "election_id": election_id,
                            "scenario_id": scenario_id,
                            "run_id": failed["run_id"],
                            "error": str(exc),
                        })
                        state.update({
                            failure_key: failures,
                            "pairs_selected": len(selections),
                            "pairs_evaluated": len(evaluations),
                            "updated_at_utc": _utc_now(),
                        })
                        _write_partial(production_dir, selections, evaluations)
                        write_json(status_path, state)
                        if _pause_after_requested_pair(
                            requested=stop_after_pair,
                            completed=(election_id, scenario_id),
                            status_path=status_path,
                            state=state,
                        ):
                            return state
                        continue
                    evaluations.append({**evaluation, **decision["compatibility"]})
                    selections.append(_selection_row(evaluation, decision))
                    state["pairs_selected"] = len(selections)
                    state["pairs_evaluated"] = len(evaluations)
                    _write_partial(production_dir, selections, evaluations)
                    write_json(status_path, state)
                    if _pause_after_requested_pair(
                        requested=stop_after_pair,
                        completed=(election_id, scenario_id),
                        status_path=status_path,
                        state=state,
                    ):
                        return state
        unresolved = [
            row
            for row in evaluations
            if str(row.get("pilot_pair_resolution", "")).startswith("unresolved_")
        ]
        if unresolved:
            state.update({
                "status": "production_completed_with_unresolved_pairs",
                "phase": "production_audited_not_finalized",
                "pairs_selected": len(selections),
                "pairs_evaluated": len(evaluations),
                "unresolved_pairs": len(unresolved),
                "release_ready": False,
                "finished_at_utc": _utc_now(),
                "updated_at_utc": _utc_now(),
            })
            _write_partial(production_dir, selections, evaluations)
            write_json(status_path, state)
            return state
        selection_path = _build_full_selection(production_dir, selections, scope)
        manifest = finalize_scoped_release(
            release_config_path=release_config_path,
            canonical_selection_path=selection_path,
        )
        final_dir = OUTPUT_DIR / scope.spec_version / "final" / scope.release_id
        invariance = _assert_exact_scientific_invariance(final_dir, production_dir)
        state.update({
            "status": "completed",
            "phase": "finalized",
            "pairs_selected": len(selections),
            "canonical_selection_path": selection_path.relative_to(ROOT).as_posix(),
            "final_dir": final_dir.relative_to(ROOT).as_posix(),
            "release_ready": manifest["ready"],
            "h0a_h1_exact_invariance": invariance["exact"],
            "finished_at_utc": _utc_now(),
            "updated_at_utc": _utc_now(),
        })
        write_json(status_path, state)
        return state
    except Exception as exc:
        state.update({
            "status": "blocked",
            "error": f"{type(exc).__name__}: {exc}",
            "updated_at_utc": _utc_now(),
        })
        write_json(status_path, state)
        raise
    finally:
        if lock_path.exists():
            lock_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sequential resumable H2/H3 KRT supervisor.")
    parser.add_argument("--release-config", type=Path, required=True)
    parser.add_argument("--stop-after-election-id")
    parser.add_argument("--stop-after-scenario-id")
    parser.add_argument(
        "--continue-after-failed-pilots",
        action="store_true",
        help="Calculate remaining pairs under explicit run-level caveats without declaring the release ready.",
    )
    args = parser.parse_args()
    stop_values = (args.stop_after_election_id, args.stop_after_scenario_id)
    if (stop_values[0] is None) != (stop_values[1] is None):
        parser.error("--stop-after-election-id and --stop-after-scenario-id must be supplied together")
    stop_after_pair = None if stop_values[0] is None else (str(stop_values[0]), str(stop_values[1]))
    result = supervise(
        args.release_config,
        stop_after_pair=stop_after_pair,
        continue_after_failed_pilots=bool(args.continue_after_failed_pilots),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
