from __future__ import annotations

import json
import ctypes
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from reproducibility.replication_scope import get_scope
from reproducibility.estimation_recovery import execute_estimation_batch
from reproducibility.estimation_process import run_supervised

from .audit_longitudinal import RUN_PLAN_PATH, build_longitudinal_audit
from .build_longitudinal_panel import PANEL_PATH, build_longitudinal_panel, load_longitudinal_panel_manifest
from .paths import CONFIG_DIR, OUTPUT_DIR, ROOT, RUNS_DIR
from .release_scope import (
    ReleaseScope,
    krt_parameterization_matches,
    load_release_scope,
    stable_run_seed,
)
from .run_2x2_batch import run_2x2
from .run_nls_batch import run_nls
from .spec_registry import ELECTION_BY_ID, SCENARIO_BY_ID, SPEC_VERSION
from .utils import write_json


DEFAULT_RELEASE_CONFIG = CONFIG_DIR / "releases" / "v1.0.2.json"


@contextmanager
def _keep_system_awake() -> object:
    """Prevent workstation sleep only while a fit is actively running."""
    if os.name != "nt":
        yield
        return
    es_continuous = 0x80000000
    es_system_required = 0x00000001
    kernel32 = ctypes.windll.kernel32
    previous = kernel32.SetThreadExecutionState(es_continuous | es_system_required)
    if previous == 0:
        raise OSError("SetThreadExecutionState failed")
    try:
        yield
    finally:
        kernel32.SetThreadExecutionState(es_continuous)


def _production_dir(scope: ReleaseScope) -> Path:
    return OUTPUT_DIR / SPEC_VERSION / "production" / scope.release_id


def _progress_path(scope: ReleaseScope, model: str) -> Path:
    return _production_dir(scope) / f"{model}_progress.parquet"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_inputs(scope: ReleaseScope | None = None) -> tuple[pd.DataFrame, dict[str, object]]:
    if not RUN_PLAN_PATH.exists():
        build_longitudinal_audit()
    if not PANEL_PATH.exists():
        build_longitudinal_panel()
    production_dir = _production_dir(scope) if scope is not None else OUTPUT_DIR / SPEC_VERSION / "production"
    production_dir.mkdir(parents=True, exist_ok=True)
    return pd.read_parquet(RUN_PLAN_PATH), load_longitudinal_panel_manifest()


def _filtered_plan(
    plan: pd.DataFrame,
    *,
    election_id: str | None = None,
    scenario_ids: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    selected = get_scope().filter_frame(plan).copy()
    if election_id:
        selected = selected.loc[selected["election_id"].eq(election_id)]
    if scenario_ids:
        selected = selected.loc[selected["scenario_id"].isin(scenario_ids)]
    anchors = {"leg_1962_r1": 0, "leg_1986_r1": 1, "leg_2022_r1": 2}
    priorities = {"H0A": 0, "H1": 1, "H2": 2, "H4": 3}
    selected = selected.assign(
        _anchor=selected["election_id"].map(anchors).fillna(100),
        _scenario=selected["scenario_id"].map(priorities).fillna(100),
    )
    return selected.sort_values(["_scenario", "_anchor", "year", "election_type", "election_id", "scenario_id"]).drop(
        columns=["_anchor", "_scenario"]
    )


def _save_progress(path: Path, rows: list[dict[str, object]], *, scope: ReleaseScope | None = None) -> None:
    frame = pd.DataFrame(rows)
    frame.to_parquet(path, index=False)
    write_json(
        path.with_suffix(".json"),
        {
            "spec_version": SPEC_VERSION,
            "release_id": scope.release_id if scope is not None else "",
            "updated_at_utc": _utc_now(),
            "rows": len(frame),
            "status_counts": frame["status"].value_counts(dropna=False).to_dict() if "status" in frame else {},
            "progress_path": path.relative_to(OUTPUT_DIR.parent).as_posix(),
        },
    )


def _recorded_path(value: object) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else ROOT / path


def _successful_runs(panel_id: str) -> list[tuple[Path, dict[str, object]]]:
    runs: list[tuple[Path, dict[str, object]]] = []
    for manifest_path in RUNS_DIR.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        parameters = manifest.get("parameters", {})
        if manifest.get("status") != "success" or not isinstance(parameters, dict):
            continue
        if str(parameters.get("panel_id", manifest.get("panel_id", ""))) != panel_id:
            continue
        preparation = manifest.get("preparation_manifest", {})
        preparation_output = preparation.get("output") if isinstance(preparation, dict) else None
        if not preparation_output or not _recorded_path(preparation_output).exists():
            continue
        runs.append((manifest_path.parent, manifest))
    return runs


def _nls_success_index(panel_id: str) -> dict[tuple[str, str], dict[str, object]]:
    selected: dict[tuple[str, str], dict[str, object]] = {}
    for run_dir, manifest in _successful_runs(panel_id):
        parameters = manifest["parameters"]
        model_key = str(parameters.get("model_key", manifest.get("model_key", "")))
        if not model_key.startswith("rosen_nls"):
            continue
        if not all((run_dir / name).is_file() and (run_dir / name).stat().st_size > 0
                   for name in NLS_REQUIRED_OUTPUTS):
            continue
        key = (str(parameters.get("election_id")), str(parameters.get("scenario_id")))
        current = selected.get(key)
        if current is None or str(manifest.get("finished_at_utc", "")) > str(current.get("finished_at_utc", "")):
            selected[key] = manifest
    return selected


NLS_REQUIRED_OUTPUTS = (
    "longitudinal_estimates.csv", "model_diagnostics.csv",
    "nls_coefficients.csv", "nls_start_diagnostics.csv",
)


def _require_nls_saved_outputs(run_id: str) -> None:
    if not run_id or Path(run_id).name != run_id:
        raise RuntimeError("NLS success has no valid saved run identifier")
    missing = [name for name in NLS_REQUIRED_OUTPUTS
               if not (RUNS_DIR / run_id / name).is_file() or (RUNS_DIR / run_id / name).stat().st_size == 0]
    if missing:
        raise RuntimeError(f"NLS success is missing saved outputs for {run_id}: {missing}")


def _krt_success_index(
    panel_id: str,
    *,
    scope: ReleaseScope,
    draws: int,
    tune: int,
    chains: int,
    target_accept: float,
    max_treedepth: int,
    random_seed_by_pair: dict[tuple[str, str], int],
) -> dict[tuple[str, str], dict[str, object]]:
    king_lambda = float(scope.krt_model.king_lambda)
    selected: dict[tuple[str, str], dict[str, object]] = {}
    for run_dir, manifest in _successful_runs(panel_id):
        parameters = manifest["parameters"]
        if str(parameters.get("model_key", manifest.get("model_key", ""))) != "krt_beta_binomial":
            continue
        contract = (
            int(parameters.get("draws", -1)) == draws
            and int(parameters.get("tune", -1)) == tune
            and int(parameters.get("chains", -1)) == chains
            and float(parameters.get("target_accept", -1)) == target_accept
            and int(parameters.get("max_treedepth", -1)) == max_treedepth
            and float(parameters.get("king_lambda", -1)) == king_lambda
            and krt_parameterization_matches(parameters, scope)
            and str(parameters.get("sampler_backend", "numpyro")) == scope.mcmc.sampler_backend
            and str(parameters.get("release_id", "")) == scope.release_id
            and str(parameters.get("seed_derivation_version", "")) == scope.mcmc.seed_derivation_version
        )
        required = (
            run_dir / "commune_latent_summaries.parquet",
            run_dir / "aggregate_comparison_v2.csv",
            run_dir / "model_diagnostics.csv",
        )
        key = (str(parameters.get("election_id")), str(parameters.get("scenario_id")))
        expected_seed = random_seed_by_pair.get(key)
        if expected_seed is None or int(parameters.get("random_seed", -1)) != expected_seed:
            continue
        if not contract or not all(path.exists() for path in required):
            continue
        current = selected.get(key)
        if current is None or str(manifest.get("finished_at_utc", "")) > str(current.get("finished_at_utc", "")):
            selected[key] = manifest
    return selected


def run_nls_longitudinal(
    *,
    election_id: str | None = None,
    scenario_id: str | None = None,
    force: bool = False,
    supervise: bool = False,
) -> dict[str, object]:
    plan, panel_manifest = _ensure_inputs()
    progress_path = OUTPUT_DIR / SPEC_VERSION / "production" / "nls_progress.parquet"
    selected = _filtered_plan(
        plan,
        election_id=election_id,
        scenario_ids=(scenario_id,) if scenario_id else None,
    )
    successful = _nls_success_index(str(panel_manifest["panel_id"])) if not force else {}
    rows_by_pair: dict[tuple[str, str], dict[str, object]] = {}

    def record(item, row):
        rows_by_pair[(str(item["election_id"]), str(item["scenario_id"]))] = row
        _save_progress(progress_path, list(rows_by_pair.values()))

    def run_one(item):
        base = {
            "election_id": item["election_id"],
            "scenario_id": item["scenario_id"],
            "panel_id": panel_manifest["panel_id"],
            "started_at_utc": _utc_now(),
        }
        if item["preparation_status"] != "admissible":
            record(item,
                {
                    **base,
                    "status": "skipped_ineligible",
                    "reason": item["preparation_reason"],
                    "finished_at_utc": _utc_now(),
                }
            )
            return rows_by_pair[(str(item["election_id"]), str(item["scenario_id"]))]
        existing = successful.get((str(item["election_id"]), str(item["scenario_id"])))
        if existing is not None:
            _require_nls_saved_outputs(str(existing.get("run_id", "")))
            record(item,
                {
                    **base,
                    "status": "skipped_existing_success",
                    "run_id": existing.get("run_id", ""),
                    "reason": "validated_success_manifest",
                    "finished_at_utc": _utc_now(),
                }
            )
            return rows_by_pair[(str(item["election_id"]), str(item["scenario_id"]))]
        try:
            election_key = str(item["election_id"])
            scenario_key = str(item["scenario_id"])
            if supervise:
                key = election_key + "__" + scenario_key
                safe = re.sub(r"[^A-Za-z0-9_.-]", "_", key)
                state = ROOT / ".runtime" / ("replication_v2" if get_scope().is_full else "replication_court")
                log = state / "estimation_processes" / "nls" / f"{safe}.log"
                run_supervised(
                    [sys.executable, "-m", "reproducibility.replication_complete", "estimation-worker",
                     "--scope", get_scope().name, "--estimation-family", "nls", "--estimation-key", key],
                    family="nls", key=key, cwd=ROOT, stdout_path=log,
                    environment=os.environ.copy(),
                )
                resumed = _nls_success_index(str(panel_manifest["panel_id"])).get(
                    (election_key, scenario_key), {})
                result = {"status": "success", "run_id": resumed.get("run_id", "")}
            else:
                result = run_nls(
                    ELECTION_BY_ID[election_key], SCENARIO_BY_ID[scenario_key],
                    sample_size=2000, panel_path=PANEL_PATH, force=force,
                )
                if result.get("status") not in {"success", "skipped_existing_success"}:
                    raise RuntimeError(f"NLS estimation returned unsuccessful status: {result}")
                if not result.get("run_id"):
                    resumed = _nls_success_index(str(panel_manifest["panel_id"])).get(
                        (election_key, scenario_key), {})
                    result = {**result, "run_id": resumed.get("run_id", "")}
            _require_nls_saved_outputs(str(result.get("run_id", "")))
            record(item, {**base, **result, "reason": "", "finished_at_utc": _utc_now()})
        except Exception as exc:
            record(item,
                {
                    **base,
                    "status": "failed",
                    "reason": str(exc),
                    "finished_at_utc": _utc_now(),
                }
            )
            raise
        return rows_by_pair[(str(item["election_id"]), str(item["scenario_id"]))]

    scope = get_scope()
    rows = execute_estimation_batch(
        selected.to_dict("records"), batch_name="nls_base",
        key_fn=lambda item: str(item["election_id"]) + "__" + str(item["scenario_id"]), run=run_one,
        state_dir=ROOT / ".runtime" / ("replication_v2" if scope.is_full else "replication_court") / "estimation_failures",
        retry_failed=os.environ.get("LONGITUDINAL_RETRY_FAILED") == "1",
    )
    frame = pd.DataFrame(rows)
    return {
        "panel_id": panel_manifest["panel_id"],
        "planned": int(len(selected)),
        "success_or_resumed": int(frame["status"].isin(["success", "skipped_existing_success"]).sum()) if not frame.empty else 0,
        "skipped_ineligible": int(frame["status"].eq("skipped_ineligible").sum()) if not frame.empty else 0,
        "failed": int(frame["status"].eq("failed").sum()) if not frame.empty else 0,
        "progress_path": progress_path.relative_to(OUTPUT_DIR.parent).as_posix(),
    }


def run_krt_longitudinal(
    *,
    release_config_path: Path | None = None,
    election_id: str | None = None,
    scenario_ids: tuple[str, ...] | None = None,
    draws: int | None = None,
    tune: int | None = None,
    chains: int | None = None,
    cores: int = 1,
    target_accept: float | None = None,
    max_treedepth: int | None = None,
    base_seed: int | None = None,
    rerun: bool = False,
    force: bool = False,
    progressbar: bool = False,
) -> dict[str, object]:
    scope = load_release_scope(release_config_path or DEFAULT_RELEASE_CONFIG)
    scenario_ids = scenario_ids or scope.krt_scenarios
    invalid = sorted(set(scenario_ids).difference(scope.krt_scenarios))
    if invalid:
        raise ValueError(f"scenarios outside configured release scope: {invalid}")
    draws = int(draws if draws is not None else (2000 if rerun else scope.mcmc.draws))
    tune = int(tune if tune is not None else (2000 if rerun else scope.mcmc.warmup))
    chains = int(chains if chains is not None else scope.mcmc.chains)
    target_accept = float(target_accept if target_accept is not None else scope.mcmc.target_accept)
    max_treedepth = int(max_treedepth if max_treedepth is not None else scope.mcmc.max_treedepth)
    configured_base_seed = scope.mcmc.rerun_base_seed if rerun else scope.mcmc.initial_base_seed
    effective_base_seed = int(base_seed if base_seed is not None else configured_base_seed)
    plan, panel_manifest = _ensure_inputs(scope)
    if str(panel_manifest.get("panel_sha256", "")) != scope.panel_sha256:
        raise AssertionError("runtime panel hash differs from release configuration")
    selected = _filtered_plan(plan, election_id=election_id, scenario_ids=scenario_ids)
    random_seed_by_pair = {
        (str(item.election_id), str(item.scenario_id)): stable_run_seed(
            base_seed=effective_base_seed,
            spec_version=scope.spec_version,
            scenario_id=str(item.scenario_id),
            election_id=str(item.election_id),
            derivation_version=scope.mcmc.seed_derivation_version,
        )
        for item in selected.itertuples(index=False)
    }
    successful = _krt_success_index(
        str(panel_manifest["panel_id"]),
        scope=scope,
        draws=draws,
        tune=tune,
        chains=chains,
        target_accept=target_accept,
        max_treedepth=max_treedepth,
        random_seed_by_pair=random_seed_by_pair,
    ) if not force else {}
    progress_path = _progress_path(scope, "krt_rerun" if rerun else "krt")
    rows: list[dict[str, object]] = []
    for item in selected.to_dict("records"):
        base = {
            "election_id": item["election_id"],
            "scenario_id": item["scenario_id"],
            "model_key": "krt_beta_binomial",
            "panel_id": panel_manifest["panel_id"],
            "release_id": scope.release_id,
            "run_role": "targeted_rerun" if rerun else "canonical",
            "run_seed": random_seed_by_pair[(str(item["election_id"]), str(item["scenario_id"]))],
            "started_at_utc": _utc_now(),
        }
        if item["preparation_status"] != "admissible":
            rows.append(
                {
                    **base,
                    "status": "skipped_ineligible",
                    "reason": item["preparation_reason"],
                    "finished_at_utc": _utc_now(),
                }
            )
            _save_progress(progress_path, rows, scope=scope)
            continue
        existing = successful.get((str(item["election_id"]), str(item["scenario_id"])))
        if existing is not None:
            rows.append(
                {
                    **base,
                    "status": "skipped_existing_success",
                    "run_id": existing.get("run_id", ""),
                    "reason": "validated_success_manifest",
                    "finished_at_utc": _utc_now(),
                }
            )
            _save_progress(progress_path, rows, scope=scope)
            continue
        try:
            with _keep_system_awake():
                result = run_2x2(
                    ELECTION_BY_ID[str(item["election_id"])],
                    SCENARIO_BY_ID[str(item["scenario_id"])],
                    "krt_beta_binomial",
                    sample_size=scope.panel_size,
                    draws=draws,
                    tune=tune,
                    chains=chains,
                    cores=cores,
                    target_accept=target_accept,
                    max_treedepth=max_treedepth,
                    sampler_backend=scope.mcmc.sampler_backend,
                    king_lambda=scope.krt_model.king_lambda,
                    krt_parameterization_version=scope.krt_model.parameterization_version,
                    random_seed=random_seed_by_pair[(str(item["election_id"]), str(item["scenario_id"]))],
                    panel_path=PANEL_PATH,
                    skip_preflight=True,
                    preflight_override_reason="longitudinal_2000_v1_fixed_production_contract",
                    force=force,
                    progressbar=progressbar,
                    run_metadata={
                        "release_id": scope.release_id,
                        "ready_scope": scope.ready_scope,
                        "public_schema_version": scope.public_schema_version,
                        "run_role": "targeted_rerun" if rerun else "canonical",
                        "base_seed": effective_base_seed,
                        "seed_derivation_version": scope.mcmc.seed_derivation_version,
                        "krt_model_spec": {
                            "model_key": scope.krt_model.model_key,
                            "likelihood": scope.krt_model.likelihood,
                            "hyperpriors": scope.krt_model.hyperpriors,
                            "commune_priors": scope.krt_model.commune_priors,
                            "aggregate_estimand_version": scope.krt_model.aggregate_estimand_version,
                            "observed_count_roundtrip_version": scope.krt_model.observed_count_roundtrip_version,
                        },
                        "sleep_prevention": "windows_execution_state_system_required",
                    },
                )
            rows.append({**base, **result, "reason": "", "finished_at_utc": _utc_now()})
        except Exception as exc:
            rows.append(
                {
                    **base,
                    "status": "failed",
                    "reason": str(exc),
                    "finished_at_utc": _utc_now(),
                }
            )
        _save_progress(progress_path, rows, scope=scope)
    frame = pd.DataFrame(rows)
    return {
        "panel_id": panel_manifest["panel_id"],
        "release_id": scope.release_id,
        "ready_scope": scope.ready_scope,
        "planned": int(len(selected)),
        "success_or_resumed": int(frame["status"].isin(["success", "skipped_existing_success"]).sum()) if not frame.empty else 0,
        "skipped_ineligible": int(frame["status"].eq("skipped_ineligible").sum()) if not frame.empty else 0,
        "failed": int(frame["status"].eq("failed").sum()) if not frame.empty else 0,
        "progress_path": progress_path.relative_to(OUTPUT_DIR.parent).as_posix(),
    }


__all__ = [
    "DEFAULT_RELEASE_CONFIG",
    "run_krt_longitudinal",
    "run_nls_longitudinal",
]
