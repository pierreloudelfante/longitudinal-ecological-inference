"""Runner de production V2 sur le panel commun exact de 3 000 communes.

Le runner est volontairement séparé des scripts historiques. Ses seuls états
propres sont écrits sous ``outputs/v2`` et chaque mise à jour de progression
est conservée dans un instantané versionné.

Ce fichier peut être importé et testé sans démarrer PyMC. Les estimations ne
sont lancées que par ``main()`` sans ``--dry-run``.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import pandas as pd

from .diagnostics_v2 import audit_trace, summary_row
from .paths import OUTPUT_DIR, PANEL_DIR, RUNS_DIR, ensure_runtime_dirs
from .run_2x2_batch import run_2x2
from .spec_registry import ELECTION_BY_ID, SCENARIO_BY_ID
from .utils import canonical_hash, file_sha256, write_json


RUNNER_SCHEMA_VERSION = "priority_production_v2.0"
PROGRESS_SCHEMA_VERSION = "priority_production_progress_v2.0"
PANEL_PATH = PANEL_DIR / "panel_3000_common_1962_1986_2022_v2.csv"
OUTPUT_V2_DIR = OUTPUT_DIR / "v2"
PROGRESS_LATEST_PATH = OUTPUT_V2_DIR / "priority_production_progress_v2.json"
PROGRESS_HISTORY_DIR = OUTPUT_V2_DIR / "progress_history"
AUDIT_DIR = OUTPUT_V2_DIR / "diagnostic_audits"
AUDIT_INDEX_PATH = OUTPUT_V2_DIR / "priority_production_diagnostics_v2.csv"

ELECTIONS = ("leg_1962_r1", "leg_1986_r1", "leg_2022_r1")
SCENARIOS = ("H0A", "H1", "H2", "H4")
MODEL_KEY = "krt_beta_binomial"
SAMPLE_SIZE = 3000
DRAWS = 1000
TUNE = 1000
CHAINS = 4
CORES = 1
TARGET_ACCEPT = 0.99
MAX_TREEDEPTH = 14
RANDOM_SEED = 20260802
DEFAULT_INITIAL_HOURS_PER_FIT = 9.0
SKIP_PREFLIGHT_REASON = (
    "explicit_user_request_exact_common_panel_3000_2026-08-04; "
    "sequential_chains_cores_1_limits_concurrent_memory; progress_and_resume_v2_enabled"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Production KRT V2: H0A/H1/H2/H4 x 1962/1986/2022, "
            "panel commun exact de 3 000 communes."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Valider le panel, le plan et la reprise sans lancer de fit.",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Réessayer aussi les fits déjà marqués failed dans la progression V2.",
    )
    parser.add_argument(
        "--initial-hours-per-fit",
        type=float,
        default=DEFAULT_INITIAL_HOURS_PER_FIT,
        help="Estimation initiale utilisée tant qu'aucun fit V2 n'est terminé.",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=SCENARIOS,
        help=(
            "Limiter cette reprise à un ou plusieurs scénarios. L'option peut être répétée; "
            "le plan et le fichier de progression complets restent inchangés."
        ),
    )
    parser.add_argument(
        "--election",
        action="append",
        choices=ELECTIONS,
        help=(
            "Limiter cette reprise à une ou plusieurs élections. L'option peut être répétée; "
            "les succès existants ne sont jamais recalculés."
        ),
    )
    args = parser.parse_args(argv)
    if args.initial_hours_per_fit <= 0:
        parser.error("--initial-hours-per-fit doit être strictement positif")
    return args


def validate_exact_panel(panel_path: Path = PANEL_PATH) -> dict[str, Any]:
    """Validate the immutable population contract used by every V2 fit."""

    if not panel_path.exists():
        raise FileNotFoundError(f"panel V2 introuvable: {panel_path}")
    frame = pd.read_csv(panel_path, dtype={"unit_id": "string", "sample_id": "string"})
    required = {"unit_id", "sample_id", "sample_rank", "included_panel_3000_common_v2"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"colonnes absentes du panel V2: {missing}")
    included = frame["included_panel_3000_common_v2"].astype(str).str.lower().isin({"true", "1"})
    selected = frame.loc[included].copy()
    if len(selected) != SAMPLE_SIZE:
        raise ValueError(f"le panel V2 doit contenir exactement {SAMPLE_SIZE} lignes incluses, observé={len(selected)}")
    if selected["unit_id"].isna().any() or selected["unit_id"].duplicated().any():
        raise ValueError("les unit_id inclus doivent être non nuls et uniques")
    ranks = pd.to_numeric(selected["sample_rank"], errors="coerce")
    if ranks.isna().any() or sorted(ranks.astype(int).tolist()) != list(range(1, SAMPLE_SIZE + 1)):
        raise ValueError("sample_rank doit être exactement la permutation 1..3000")
    sample_ids = selected["sample_id"].dropna().unique().tolist()
    if len(sample_ids) != 1:
        raise ValueError(f"un seul sample_id est requis, observé={sample_ids}")
    return {
        "panel_path": str(panel_path.resolve()),
        "panel_sha256": file_sha256(panel_path),
        "sample_id": str(sample_ids[0]),
        "n_communes": len(selected),
    }


def build_plan(panel_metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the deterministic 12-fit production plan."""

    if int(panel_metadata.get("n_communes", -1)) != SAMPLE_SIZE:
        raise ValueError("build_plan requires the validated exact 3000-commune panel")
    plan: list[dict[str, Any]] = []
    for scenario_id in SCENARIOS:
        for election_id in ELECTIONS:
            item_id = f"{election_id}__{scenario_id}__{MODEL_KEY}"
            plan.append(
                {
                    "item_id": item_id,
                    "election_id": election_id,
                    "scenario_id": scenario_id,
                    "model_key": MODEL_KEY,
                    "sample_size": SAMPLE_SIZE,
                    "draws": DRAWS,
                    "tune": TUNE,
                    "chains": CHAINS,
                    "cores": CORES,
                    "target_accept": TARGET_ACCEPT,
                    "max_treedepth": MAX_TREEDEPTH,
                    "random_seed": RANDOM_SEED,
                    "panel_path": str(panel_metadata["panel_path"]),
                    "panel_sha256": str(panel_metadata["panel_sha256"]),
                    "sample_id": str(panel_metadata["sample_id"]),
                    "skip_preflight": True,
                    "skip_preflight_reason": SKIP_PREFLIGHT_REASON,
                }
            )
    return plan


def plan_hash(plan: Sequence[Mapping[str, Any]]) -> str:
    return canonical_hash(list(plan))


def new_progress(
    plan: Sequence[Mapping[str, Any]],
    panel_metadata: Mapping[str, Any],
    *,
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = now or _utc_now()
    return {
        "progress_schema_version": PROGRESS_SCHEMA_VERSION,
        "runner_schema_version": RUNNER_SCHEMA_VERSION,
        "status": "planned",
        "created_at_utc": timestamp,
        "updated_at_utc": timestamp,
        "revision": 0,
        "plan_hash": plan_hash(plan),
        "panel": dict(panel_metadata),
        "configuration": {
            "elections": list(ELECTIONS),
            "scenarios": list(SCENARIOS),
            "model_key": MODEL_KEY,
            "sample_size": SAMPLE_SIZE,
            "draws": DRAWS,
            "tune": TUNE,
            "chains": CHAINS,
            "cores": CORES,
            "target_accept": TARGET_ACCEPT,
            "max_treedepth": MAX_TREEDEPTH,
            "random_seed": RANDOM_SEED,
            "skip_preflight": True,
            "skip_preflight_reason": SKIP_PREFLIGHT_REASON,
        },
        "items": {
            str(item["item_id"]): {
                **dict(item),
                "status": "pending",
                "attempts": 0,
                "elapsed_seconds": None,
                "run_id": None,
                "fit_status": None,
                "mcmc_status": None,
                "identification_status": "not_assessed",
                "selected_for_interpretation": False,
                "error": "",
            }
            for item in plan
        },
    }


def reconcile_progress(
    progress: Mapping[str, Any],
    plan: Sequence[Mapping[str, Any]],
    panel_metadata: Mapping[str, Any],
    *,
    now: str | None = None,
) -> dict[str, Any]:
    """Validate resume identity and recover any interrupted ``running`` item."""

    if progress.get("progress_schema_version") != PROGRESS_SCHEMA_VERSION:
        raise ValueError("version de progression V2 incompatible")
    if progress.get("plan_hash") != plan_hash(plan):
        raise ValueError("la progression V2 appartient à un autre plan")
    saved_panel = progress.get("panel", {})
    if not isinstance(saved_panel, Mapping) or saved_panel.get("panel_sha256") != panel_metadata.get("panel_sha256"):
        raise ValueError("la progression V2 appartient à une autre version du panel")
    resumed = json.loads(json.dumps(progress))
    expected_ids = {str(item["item_id"]) for item in plan}
    if set(resumed.get("items", {})) != expected_ids:
        raise ValueError("les items de progression ne correspondent pas au plan V2")
    timestamp = now or _utc_now()
    for item in resumed["items"].values():
        if item.get("status") == "running":
            item["status"] = "pending"
            item["recovered_interruption_at_utc"] = timestamp
            item["error"] = "recovered_interrupted_runner; retry_pending"
    resumed["status"] = "resumed"
    resumed["updated_at_utc"] = timestamp
    return resumed


def pending_items(
    progress: Mapping[str, Any],
    plan: Sequence[Mapping[str, Any]],
    *,
    retry_failed: bool = False,
    selected_item_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    states = progress.get("items", {})
    selected = set(selected_item_ids) if selected_item_ids is not None else None
    pending: list[dict[str, Any]] = []
    for item in plan:
        if selected is not None and str(item["item_id"]) not in selected:
            continue
        state = states[str(item["item_id"])]
        status = state.get("status")
        if status in {"pending", "running"} or (retry_failed and status == "failed"):
            pending.append(dict(item))
    return pending


def estimate_remaining_seconds(
    progress: Mapping[str, Any],
    plan: Sequence[Mapping[str, Any]],
    *,
    retry_failed: bool = False,
    initial_seconds_per_fit: float = DEFAULT_INITIAL_HOURS_PER_FIT * 3600,
    selected_item_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Estimate remaining wall time from the median completed V2 fit."""

    remaining = pending_items(
        progress,
        plan,
        retry_failed=retry_failed,
        selected_item_ids=selected_item_ids,
    )
    durations = [
        float(item["elapsed_seconds"])
        for item in progress.get("items", {}).values()
        if item.get("status") in {"success", "skipped_existing_success"}
        and item.get("elapsed_seconds") is not None
        and float(item["elapsed_seconds"]) > 0
    ]
    seconds_per_fit = statistics.median(durations) if durations else float(initial_seconds_per_fit)
    return {
        "remaining_fits": len(remaining),
        "seconds_per_fit": seconds_per_fit,
        "estimated_remaining_seconds": len(remaining) * seconds_per_fit,
        "estimated_remaining_hours": len(remaining) * seconds_per_fit / 3600,
        "method": "median_completed_v2_fit" if durations else "initial_user_visible_assumption",
    }


def progress_summary(
    progress: Mapping[str, Any],
    plan: Sequence[Mapping[str, Any]],
    *,
    retry_failed: bool = False,
    initial_seconds_per_fit: float = DEFAULT_INITIAL_HOURS_PER_FIT * 3600,
    selected_item_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in progress.get("items", {}).values():
        status = str(item.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return {
        "total_fits": len(plan),
        "status_counts": counts,
        **estimate_remaining_seconds(
            progress,
            plan,
            retry_failed=retry_failed,
            initial_seconds_per_fit=initial_seconds_per_fit,
            selected_item_ids=selected_item_ids,
        ),
    }


def select_item_ids(
    plan: Sequence[Mapping[str, Any]],
    *,
    scenarios: Iterable[str] | None = None,
    elections: Iterable[str] | None = None,
) -> list[str]:
    """Select a resumable subset without changing the immutable 12-fit plan."""

    scenario_filter = set(scenarios or SCENARIOS)
    election_filter = set(elections or ELECTIONS)
    selected = [
        str(item["item_id"])
        for item in plan
        if str(item["scenario_id"]) in scenario_filter
        and str(item["election_id"]) in election_filter
    ]
    if not selected:
        raise ValueError("la sélection ciblée ne contient aucun fit")
    return selected


def _save_progress(progress: dict[str, Any]) -> None:
    OUTPUT_V2_DIR.mkdir(parents=True, exist_ok=True)
    PROGRESS_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    revision = int(progress.get("revision", 0)) + 1
    progress["revision"] = revision
    progress["updated_at_utc"] = _utc_now()
    stamp = progress["updated_at_utc"].replace(":", "").replace("+00:00", "Z").replace(".", "_")
    write_json(PROGRESS_HISTORY_DIR / f"{revision:04d}__{stamp}.json", progress)
    write_json(PROGRESS_LATEST_PATH, progress)


def _load_or_create_progress(
    plan: Sequence[Mapping[str, Any]], panel_metadata: Mapping[str, Any]
) -> dict[str, Any]:
    if not PROGRESS_LATEST_PATH.exists():
        return new_progress(plan, panel_metadata)
    existing = json.loads(PROGRESS_LATEST_PATH.read_text(encoding="utf-8"))
    return reconcile_progress(existing, plan, panel_metadata)


def _runner_kwargs(item: Mapping[str, Any]) -> dict[str, Any]:
    """Map a plan item to the explicit, auditable ``run_2x2`` call contract."""

    return {
        "sample_size": int(item["sample_size"]),
        "draws": int(item["draws"]),
        "tune": int(item["tune"]),
        "chains": int(item["chains"]),
        "cores": int(item["cores"]),
        "target_accept": float(item["target_accept"]),
        "max_treedepth": int(item["max_treedepth"]),
        "random_seed": int(item["random_seed"]),
        "force": False,
        "progressbar": False,
        "panel_path": Path(str(item["panel_path"])),
        "skip_preflight": True,
        "preflight_override_reason": str(item["skip_preflight_reason"]),
    }


def _trace_path_from_result(result: Mapping[str, Any], item: Mapping[str, Any]) -> tuple[str, Path]:
    run_id = str(result.get("run_id", ""))
    if run_id:
        trace_path = RUNS_DIR / run_id / "trace.nc"
        if not trace_path.exists():
            raise FileNotFoundError(f"trace V2 introuvable: {trace_path}")
        return run_id, trace_path

    # ``run_2x2`` returns no run_id when its immutable registry skips an exact
    # prior success. Recover that run deterministically so an interruption
    # between fit completion and progress update remains resumable.
    expected = {
        "election_id": item["election_id"],
        "scenario_id": item["scenario_id"],
        "model_key": item["model_key"],
        "sample_size": int(item["sample_size"]),
        "draws": int(item["draws"]),
        "tune": int(item["tune"]),
        "chains": int(item["chains"]),
        "cores": int(item["cores"]),
        "target_accept": float(item["target_accept"]),
        "max_treedepth": int(item["max_treedepth"]),
        "random_seed": int(item["random_seed"]),
        "panel_path": str(Path(str(item["panel_path"])).resolve()),
        "preflight_override_reason": str(item["skip_preflight_reason"]),
    }
    matches: list[tuple[str, str, Path]] = []
    for manifest_path in RUNS_DIR.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        parameters = manifest.get("parameters", {})
        trace_path = manifest_path.parent / "trace.nc"
        if (
            manifest.get("status") == "success"
            and isinstance(parameters, Mapping)
            and all(parameters.get(key) == value for key, value in expected.items())
            and trace_path.exists()
        ):
            matches.append(
                (
                    str(manifest.get("finished_at_utc", "")),
                    str(manifest.get("run_id", manifest_path.parent.name)),
                    trace_path,
                )
            )
    if not matches:
        raise FileNotFoundError("succès exact V2 introuvable après skip du registre")
    _, recovered_run_id, recovered_trace = max(matches, key=lambda value: value[0])
    return recovered_run_id, recovered_trace


def _write_audit(item_id: str, audit: Mapping[str, Any]) -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    path = AUDIT_DIR / f"{item_id}.json"
    write_json(path, audit)
    return path


def _write_audit_index(progress: Mapping[str, Any]) -> None:
    rows = []
    for item_id, item in progress.get("items", {}).items():
        summary = item.get("audit_summary")
        if isinstance(summary, Mapping):
            rows.append(
                {
                    "item_id": item_id,
                    "election_id": item.get("election_id"),
                    "scenario_id": item.get("scenario_id"),
                    "model_key": item.get("model_key"),
                    "run_id": item.get("run_id"),
                    **dict(summary),
                }
            )
    if rows:
        OUTPUT_V2_DIR.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(AUDIT_INDEX_PATH, index=False, encoding="utf-8-sig")


def execute_plan(
    plan: Sequence[Mapping[str, Any]],
    progress: dict[str, Any],
    *,
    retry_failed: bool = False,
    initial_seconds_per_fit: float = DEFAULT_INITIAL_HOURS_PER_FIT * 3600,
    selected_item_ids: Iterable[str] | None = None,
    fit_runner: Callable[..., Mapping[str, Any]] = run_2x2,
    trace_auditor: Callable[..., Mapping[str, Any]] = audit_trace,
) -> dict[str, Any]:
    """Execute pending fits sequentially; record a failure and continue."""

    progress["status"] = "running"
    _save_progress(progress)
    selected_ids = list(selected_item_ids) if selected_item_ids is not None else None
    todo = pending_items(
        progress,
        plan,
        retry_failed=retry_failed,
        selected_item_ids=selected_ids,
    )
    for position, item in enumerate(todo, start=1):
        item_id = str(item["item_id"])
        state = progress["items"][item_id]
        state.update(
            {
                "status": "running",
                "started_at_utc": _utc_now(),
                "attempts": int(state.get("attempts", 0)) + 1,
                "error": "",
            }
        )
        _save_progress(progress)
        eta = estimate_remaining_seconds(
            progress,
            plan,
            retry_failed=retry_failed,
            initial_seconds_per_fit=initial_seconds_per_fit,
            selected_item_ids=selected_ids,
        )
        print(
            f"[{position}/{len(todo)}] {item['election_id']}/{item['scenario_id']}/{MODEL_KEY} "
            f"- reste estimé {eta['estimated_remaining_hours']:.1f} h",
            flush=True,
        )
        started = time.perf_counter()
        try:
            result = fit_runner(
                ELECTION_BY_ID[str(item["election_id"])],
                SCENARIO_BY_ID[str(item["scenario_id"])],
                str(item["model_key"]),
                **_runner_kwargs(item),
            )
            result_status = str(result.get("status", "success"))
            run_id, trace_path = _trace_path_from_result(result, item)
            audit = trace_auditor(
                trace_path,
                fit_status="success",
                identification_status="not_assessed",
                expected_chains=CHAINS,
                expected_draws_per_chain=DRAWS,
                max_treedepth=MAX_TREEDEPTH,
            )
            audit_path = _write_audit(item_id, audit)
            state.update(
                {
                    "status": "skipped_existing_success" if result_status == "skipped_existing_success" else "success",
                    "fit_status": "success",
                    "run_id": run_id,
                    "trace_path": str(trace_path),
                    "audit_path": str(audit_path),
                    "audit_summary": summary_row(audit),
                    "mcmc_status": audit["mcmc_status"],
                    "identification_status": audit["identification_status"],
                    "selected_for_interpretation": audit["selected_for_interpretation"],
                }
            )
        except Exception as exc:
            state.update(
                {
                    "status": "failed",
                    "fit_status": "failed",
                    "mcmc_status": "fail",
                    "selected_for_interpretation": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            print(f"ÉCHEC {item_id}: {exc} -- poursuite du lot", flush=True)
        finally:
            state["elapsed_seconds"] = time.perf_counter() - started
            state["finished_at_utc"] = _utc_now()
            _save_progress(progress)
            _write_audit_index(progress)

    if selected_ids is None:
        statuses = {str(item.get("status")) for item in progress["items"].values()}
        progress["status"] = "completed_with_failures" if "failed" in statuses else "completed"
    else:
        statuses = {str(progress["items"][item_id].get("status")) for item_id in selected_ids}
        progress["status"] = (
            "targeted_batch_completed_with_failures" if "failed" in statuses else "targeted_batch_completed"
        )
        progress["targeted_batch"] = {
            "item_ids": selected_ids,
            "status_counts": {
                status: sum(str(progress["items"][item_id].get("status")) == status for item_id in selected_ids)
                for status in sorted(statuses)
            },
            "finished_at_utc": _utc_now(),
        }
    progress["summary"] = progress_summary(
        progress,
        plan,
        retry_failed=retry_failed,
        initial_seconds_per_fit=initial_seconds_per_fit,
    )
    _save_progress(progress)
    return progress


def main(argv: Sequence[str] | None = None) -> None:
    ensure_runtime_dirs()
    args = parse_args(argv)
    panel_metadata = validate_exact_panel()
    plan = build_plan(panel_metadata)
    progress = _load_or_create_progress(plan, panel_metadata)
    selected_item_ids = (
        select_item_ids(plan, scenarios=args.scenario, elections=args.election)
        if args.scenario or args.election
        else None
    )
    initial_seconds = args.initial_hours_per_fit * 3600
    summary = progress_summary(
        progress,
        plan,
        retry_failed=args.retry_failed,
        initial_seconds_per_fit=initial_seconds,
        selected_item_ids=selected_item_ids,
    )
    print(
        json.dumps(
            {
                "panel": panel_metadata,
                "plan_hash": plan_hash(plan),
                "selected_item_ids": selected_item_ids,
                **summary,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.dry_run:
        return
    execute_plan(
        plan,
        progress,
        retry_failed=args.retry_failed,
        initial_seconds_per_fit=initial_seconds,
        selected_item_ids=selected_item_ids,
    )


if __name__ == "__main__":
    main()


__all__ = [
    "PANEL_PATH",
    "PROGRESS_LATEST_PATH",
    "RUNNER_SCHEMA_VERSION",
    "SKIP_PREFLIGHT_REASON",
    "build_plan",
    "estimate_remaining_seconds",
    "execute_plan",
    "new_progress",
    "parse_args",
    "pending_items",
    "plan_hash",
    "progress_summary",
    "reconcile_progress",
    "select_item_ids",
    "validate_exact_panel",
]
