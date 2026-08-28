from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .build_longitudinal_panel import PANEL_PATH, load_longitudinal_panel_manifest
from .paths import OUTPUT_DIR, ROOT, RUNS_DIR
from .release_scope import (
    ReleaseScope,
    caveat_severity,
    krt_parameterization_matches,
    load_release_scope,
)
from .spec_registry import SPEC_VERSION
from .utils import file_sha256, write_json


UNCERTAINTY_COLUMNS = (
    "b1_sd", "b1_q025", "b1_q50", "b1_q975",
    "b2_sd", "b2_q025", "b2_q50", "b2_q975",
)
CANONICAL_NLS_PATH = (
    ROOT
    / "work"
    / "longitudinal_2000_v1.0.2_H0A_H1_validated"
    / "01_resultats_python"
    / "longitudinal_nls.parquet"
)


def _production_dir(scope: ReleaseScope) -> Path:
    path = OUTPUT_DIR / SPEC_VERSION / "production" / scope.release_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _model_ready_path(election_id: str, scenario_id: str, panel_id: str) -> Path:
    path = OUTPUT_DIR / "model_ready" / f"{election_id}__{scenario_id}__{panel_id}__n2000.parquet"
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def audit_pilot_inputs(release_config_path: Path | str) -> dict[str, Any]:
    scope = load_release_scope(release_config_path)
    if not scope.pilot_pairs:
        raise ValueError("release scope does not define pilot_pairs")
    panel_manifest = load_longitudinal_panel_manifest()
    panel_id = str(panel_manifest["panel_id"])
    panel = pd.read_parquet(PANEL_PATH)
    if "included_primary_2000" not in panel:
        raise AssertionError("master panel does not identify the primary 2,000-commune sub-panel")
    primary = panel.loc[panel["included_primary_2000"].astype(bool)].copy()
    expected_ids = primary["unit_id"].astype("string")
    panel_checks = {
        "master_panel_rows": int(len(panel)),
        "primary_panel_rows": int(len(primary)),
        "primary_panel_unique_unit_ids": int(expected_ids.nunique()),
        "panel_sha256": file_sha256(PANEL_PATH),
        "expected_panel_sha256": scope.panel_sha256,
    }
    panel_checks["status"] = "pass" if (
        panel_checks["primary_panel_rows"] == scope.panel_size
        and panel_checks["primary_panel_unique_unit_ids"] == scope.panel_size
        and panel_checks["panel_sha256"] == scope.panel_sha256
    ) else "fail"

    rows: list[dict[str, Any]] = []
    expected_set = set(expected_ids.astype(str))
    for election_id, scenario_id in scope.pilot_pairs:
        path = _model_ready_path(election_id, scenario_id, panel_id)
        frame = pd.read_parquet(path)
        observed_set = set(frame["unit_id"].astype(str))
        social_gap = (
            frame["N__target_group"].astype(float)
            + frame["N__complement_group"].astype(float)
            - frame["N_g"].astype(float)
        ).abs()
        vote_gap = (
            frame["Y__gauche"].astype(float)
            + frame["Y__non_gauche"].astype(float)
            - frame["N_g"].astype(float)
        ).abs()
        row = {
            "election_id": election_id,
            "scenario_id": scenario_id,
            "model_ready_path": path.relative_to(ROOT).as_posix(),
            "model_ready_sha256": file_sha256(path),
            "n_rows": int(len(frame)),
            "n_unique_unit_ids": int(frame["unit_id"].astype("string").nunique()),
            "same_unit_id_set_as_panel": observed_set == expected_set,
            "max_abs_social_margin_gap": float(social_gap.max()),
            "max_abs_political_margin_gap": float(vote_gap.max()),
            "probability_inputs_in_bounds": bool(
                frame["N__target_group"].between(0, frame["N_g"]).all()
                and frame["Y__gauche"].between(0, frame["N_g"]).all()
            ),
        }
        row["status"] = "pass" if (
            row["n_rows"] == scope.panel_size
            and row["n_unique_unit_ids"] == scope.panel_size
            and row["same_unit_id_set_as_panel"]
            and row["max_abs_social_margin_gap"] == 0.0
            and row["max_abs_political_margin_gap"] == 0.0
            and row["probability_inputs_in_bounds"]
        ) else "fail"
        rows.append(row)
    output = _production_dir(scope)
    pd.DataFrame(rows).to_csv(output / "h23_pilot_input_audit.csv", index=False, encoding="utf-8-sig")
    result = {
        "release_id": scope.release_id,
        "panel_id": panel_id,
        "panel_checks": panel_checks,
        "pilot_pairs": len(rows),
        "input_status_counts": pd.Series([row["status"] for row in rows]).value_counts().to_dict(),
        "ready_for_pilot_fits": panel_checks["status"] == "pass" and all(row["status"] == "pass" for row in rows),
    }
    write_json(output / "h23_pilot_input_audit.json", result)
    return result


def _matching_run(scope: ReleaseScope, election_id: str, scenario_id: str, *, rerun: bool = False) -> tuple[Path, dict[str, Any]] | None:
    expected_seed = scope.run_seed(scenario_id, election_id, rerun=rerun)
    expected_tune = 2000 if rerun else scope.mcmc.warmup
    expected_draws = 2000 if rerun else scope.mcmc.draws
    candidates: list[tuple[str, Path, dict[str, Any]]] = []
    for manifest_path in RUNS_DIR.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        parameters = manifest.get("parameters", {})
        if manifest.get("status") != "success" or not isinstance(parameters, dict):
            continue
        if (
            parameters.get("release_id") != scope.release_id
            or parameters.get("election_id") != election_id
            or parameters.get("scenario_id") != scenario_id
            or parameters.get("model_key") != "krt_beta_binomial"
            or int(parameters.get("random_seed", -1)) != expected_seed
            or int(parameters.get("tune", -1)) != expected_tune
            or int(parameters.get("draws", -1)) != expected_draws
            or int(parameters.get("chains", -1)) != scope.mcmc.chains
            or float(parameters.get("king_lambda", -1)) != scope.krt_model.king_lambda
            or not krt_parameterization_matches(parameters, scope)
            or str(parameters.get("sampler_backend", "numpyro")) != scope.mcmc.sampler_backend
            or str(parameters.get("panel_sha256", "")) != scope.panel_sha256
        ):
            continue
        run_dir = manifest_path.parent
        required = (
            run_dir / "commune_latent_summaries.parquet",
            run_dir / "aggregate_comparison_v2.csv",
            run_dir / "mcmc_diagnostics_v2.json",
            run_dir / "identification_diagnostics.json",
        )
        if all(path.is_file() for path in required):
            candidates.append((str(manifest.get("finished_at_utc", "")), run_dir, manifest))
    if not candidates:
        return None
    _, run_dir, manifest = max(candidates, key=lambda item: item[0])
    return run_dir, manifest


def _latest_attempt(scope: ReleaseScope, election_id: str, scenario_id: str) -> dict[str, Any] | None:
    expected_seed = scope.run_seed(scenario_id, election_id)
    attempts: list[tuple[str, dict[str, Any]]] = []
    for manifest_path in RUNS_DIR.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        parameters = manifest.get("parameters", {})
        if not isinstance(parameters, dict):
            continue
        if (
            parameters.get("release_id") == scope.release_id
            and parameters.get("election_id") == election_id
            and parameters.get("scenario_id") == scenario_id
            and int(parameters.get("random_seed", -1)) == expected_seed
        ):
            timestamp = str(manifest.get("finished_at_utc", manifest.get("started_at_utc", "")))
            attempts.append((timestamp, manifest))
    return max(attempts, key=lambda item: item[0])[1] if attempts else None


def _nls_contrast(election_id: str, scenario_id: str) -> float:
    if not CANONICAL_NLS_PATH.is_file():
        raise FileNotFoundError(CANONICAL_NLS_PATH)
    frame = pd.read_parquet(CANONICAL_NLS_PATH)
    required = {"election_id", "scenario_id", "estimand_type", "vote_category", "estimate"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise AssertionError(f"canonical NLS table is missing columns: {missing}")
    subset = frame.loc[
        frame["election_id"].astype(str).eq(election_id)
        & frame["scenario_id"].astype(str).eq(scenario_id)
        & frame["estimand_type"].astype(str).eq("group_contrast")
    ]
    if len(subset) != 1:
        categories = sorted(subset["vote_category"].astype(str).unique().tolist())
        raise AssertionError(
            f"expected exactly one NLS group contrast for {election_id}/{scenario_id}; "
            f"found {len(subset)} with categories {categories}"
        )
    return float(subset["estimate"].iloc[0])


def intervals_compatible(initial: dict[str, Any], rerun: dict[str, Any]) -> dict[str, bool]:
    """Compare separately fitted 95% intervals without implying a joint posterior."""
    values = (
        initial.get("krt_q025"),
        initial.get("krt_q975"),
        rerun.get("krt_q025"),
        rerun.get("krt_q975"),
    )
    finite = all(value is not None and np.isfinite(float(value)) for value in values)
    if not finite:
        return {
            "intervals_available": False,
            "intervals_overlap": False,
            "sustained_sign_inversion": True,
            "compatible": False,
        }
    initial_q025, initial_q975, rerun_q025, rerun_q975 = (float(value) for value in values)
    overlap = max(initial_q025, rerun_q025) <= min(initial_q975, rerun_q975)
    sign_inversion = bool(
        (initial_q025 > 0 and rerun_q975 < 0)
        or (initial_q975 < 0 and rerun_q025 > 0)
    )
    return {
        "intervals_available": True,
        "intervals_overlap": bool(overlap),
        "sustained_sign_inversion": sign_inversion,
        "compatible": bool(overlap and not sign_inversion),
    }


def method_sensitivity_assessment(
    *, absolute_difference: float, sustained_sign_opposition: bool
) -> dict[str, Any]:
    """Classify KRT--NLS agreement independently from MCMC convergence."""
    checks = {
        "krt_nls_distance_le_0_15": (
            np.isfinite(absolute_difference) and absolute_difference <= 0.15
        ),
        "no_sustained_sign_opposition": not sustained_sign_opposition,
    }
    reasons = [name for name, passed in checks.items() if not passed]
    return {
        **checks,
        "method_sensitivity_status": "pass" if not reasons else "alert",
        "method_sensitivity_reasons": "|".join(reasons),
    }


def resolve_pilot_pair_for_gate(
    initial: dict[str, Any],
    rerun: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolve a pilot pair using the same pre-registered rule as the supervisor.

    The standalone gate used to inspect only the initial run.  That made a
    successfully selected strengthened rerun appear to be pending.  Keeping the
    resolution pure and local also makes the standalone audit independently
    testable without changing the scientific selection rule.
    """
    severity = str(initial.get("mcmc_substatus", "fail"))
    if severity in {"pass", "caveat_modere"}:
        row = dict(initial)
        selected = bool(initial.get("core_gate_pass", False))
        row.update({
            "gate_status": "pass" if selected else "hold",
            "pilot_pair_resolution": "initial_selected" if selected else "initial_hold",
            "pilot_pair_error": "" if selected else str(initial.get("gate_reasons", "initial_gate_failure")),
            "selected_run_id": str(initial.get("run_id", "")) if selected else "",
            "initial_run_id": str(initial.get("run_id", "")),
            "replaces_run_id": "",
        })
        return row

    if rerun is None:
        row = dict(initial)
        reasons = [value for value in str(row.get("gate_reasons", "")).split("|") if value]
        if "strengthened_rerun_required" not in reasons:
            reasons.append("strengthened_rerun_required")
        row.update({
            "gate_status": "hold",
            "gate_reasons": "|".join(reasons),
            "pilot_pair_resolution": "awaiting_strengthened_rerun",
            "pilot_pair_error": "strengthened_rerun_not_available",
            "selected_run_id": "",
            "initial_run_id": str(initial.get("run_id", "")),
            "replaces_run_id": "",
        })
        return row

    compatibility = intervals_compatible(initial, rerun)
    row = {**rerun, **compatibility}
    rerun_acceptable = (
        str(rerun.get("mcmc_status", "fail")) in {"pass", "caveat"}
        and bool(rerun.get("core_gate_pass", False))
        and compatibility["compatible"]
    )
    failure_reasons: list[str] = []
    if str(rerun.get("mcmc_status", "fail")) not in {"pass", "caveat"}:
        failure_reasons.append("strengthened_rerun_mcmc_fail")
    if not bool(rerun.get("core_gate_pass", False)):
        failure_reasons.extend(
            value for value in str(rerun.get("gate_reasons", "")).split("|") if value
        )
    if not compatibility["compatible"]:
        failure_reasons.append("initial_rerun_incompatible")
    row.update({
        "gate_status": "pass" if rerun_acceptable else "hold",
        "gate_reasons": "" if rerun_acceptable else "|".join(dict.fromkeys(failure_reasons)),
        "pilot_pair_resolution": (
            "strengthened_rerun_selected" if rerun_acceptable else "strengthened_rerun_unresolved"
        ),
        "pilot_pair_error": "" if rerun_acceptable else "strengthened_rerun_did_not_resolve_pair",
        "selected_run_id": str(rerun.get("run_id", "")) if rerun_acceptable else "",
        "initial_run_id": str(initial.get("run_id", "")),
        "replaces_run_id": str(initial.get("run_id", "")) if rerun_acceptable else "",
    })
    return row


def evaluate_krt_run(
    scope: ReleaseScope,
    election_id: str,
    scenario_id: str,
    *,
    rerun: bool = False,
) -> dict[str, Any] | None:
    """Apply the pre-registered numerical gate to one completed H2/H3 KRT run.

    Identification is reported but never used to request a longer MCMC run.
    A strengthened rerun is requested only for an initial severe MCMC caveat or
    official MCMC failure; semantic/input gate failures remain explicit holds.
    """
    match = _matching_run(scope, election_id, scenario_id, rerun=rerun)
    if match is None:
        return None
    run_dir, manifest = match
    diagnostic = json.loads((run_dir / "mcmc_diagnostics_v2.json").read_text(encoding="utf-8"))
    identification = json.loads((run_dir / "identification_diagnostics.json").read_text(encoding="utf-8"))
    latent = pd.read_parquet(run_dir / "commune_latent_summaries.parquet")
    aggregate = pd.read_csv(run_dir / "aggregate_comparison_v2.csv")
    corrected = aggregate.loc[aggregate["aggregation_method"].eq("group_specific_population_v2")].copy()
    corrected = corrected.set_index("beta_parameter")
    required_estimands = {"b_1", "b_2", "b_1_minus_b_2"}
    complete_aggregates = set(corrected.index) == required_estimands and len(corrected) == 3
    probability_bounds = True
    if complete_aggregates:
        probability_values = corrected.loc[
            ["b_1", "b_2"], ["mean", "q025", "q50", "q975"]
        ].to_numpy(float)
        contrast_values = corrected.loc[
            ["b_1_minus_b_2"], ["mean", "q025", "q50", "q975"]
        ].to_numpy(float)
        probability_bounds = bool(
            probability_values.min() >= 0
            and probability_values.max() <= 1
            and contrast_values.min() >= -1
            and contrast_values.max() <= 1
        )
    contrast = float(corrected.loc["b_1_minus_b_2", "mean"]) if complete_aggregates else np.nan
    q025 = float(corrected.loc["b_1_minus_b_2", "q025"]) if complete_aggregates else np.nan
    q975 = float(corrected.loc["b_1_minus_b_2", "q975"]) if complete_aggregates else np.nan
    nls = _nls_contrast(election_id, scenario_id)
    difference = abs(contrast - nls) if np.isfinite(contrast) else np.nan
    sustained_opposition = bool(
        (q025 > 0 and nls < 0) or (q975 < 0 and nls > 0)
    ) if np.isfinite(q025) and np.isfinite(q975) else True
    official = str(diagnostic.get("mcmc_status", "fail"))
    min_ess = None
    if diagnostic.get("min_ess_bulk") is not None and diagnostic.get("min_ess_tail") is not None:
        min_ess = min(
            float(diagnostic["min_ess_bulk"]),
            float(diagnostic["min_ess_tail"]),
        )
    severity = caveat_severity(
        official_status=official,
        max_rhat=diagnostic.get("max_rhat"),
        min_ess=min_ess,
        min_bfmi=diagnostic.get("min_bfmi"),
        divergences=diagnostic.get("divergences"),
        treedepth_saturated=diagnostic.get("max_treedepth_hits"),
    )
    available_mb = float(manifest.get("next_ladder_gate", {}).get("available_memory_mb", np.nan))
    peak_mb = float(manifest.get("peak_memory_mb", np.nan))
    memory_ok = bool(
        np.isfinite(available_mb)
        and np.isfinite(peak_mb)
        and peak_mb <= 0.8 * available_mb
    )
    elapsed = float(manifest.get("elapsed_seconds", np.nan))
    mcmc_and_output_checks = {
        "mcmc_not_fail": official != "fail",
        "zero_divergences": diagnostic.get("divergences") == 0,
        "zero_treedepth_hits": diagnostic.get("max_treedepth_hits") == 0,
        "latent_complete": len(latent) == scope.panel_size and all(column in latent for column in UNCERTAINTY_COLUMNS),
        "aggregate_complete": complete_aggregates,
        "probabilities_and_contrast_in_bounds": probability_bounds,
        "memory_under_80pct_available": memory_ok,
        "elapsed_under_12h": np.isfinite(elapsed) and elapsed <= 12 * 3600,
    }
    method_sensitivity = method_sensitivity_assessment(
        absolute_difference=difference,
        sustained_sign_opposition=sustained_opposition,
    )
    method_sensitivity_checks = {
        name: bool(method_sensitivity[name])
        for name in ("krt_nls_distance_le_0_15", "no_sustained_sign_opposition")
    }
    core_reasons = [name for name, passed in mcmc_and_output_checks.items() if not passed]
    method_reasons = [name for name, passed in method_sensitivity_checks.items() if not passed]
    rerun_required = not rerun and severity in {"caveat_severe", "fail"}
    reasons = [*core_reasons]
    if rerun_required:
        reasons.append("strengthened_rerun_required")
    return {
        "election_id": election_id,
        "scenario_id": scenario_id,
        "run_id": manifest["run_id"],
        "panel_id": manifest.get("parameters", {}).get("panel_id", manifest.get("panel_id", "")),
        "run_type": "strengthened_rerun" if rerun else "initial",
        "fit_available": True,
        "mcmc_status": official,
        "mcmc_substatus": severity,
        "identification_status": identification.get("identification_status", "unknown"),
        "elapsed_seconds": elapsed,
        "peak_memory_mb": peak_mb,
        "available_memory_mb": available_mb,
        "max_rhat": diagnostic.get("max_rhat"),
        "min_ess_bulk": diagnostic.get("min_ess_bulk"),
        "min_ess_tail": diagnostic.get("min_ess_tail"),
        "min_bfmi": diagnostic.get("min_bfmi"),
        "divergences": diagnostic.get("divergences"),
        "max_treedepth_hits": diagnostic.get("max_treedepth_hits"),
        "krt_contrast": contrast,
        "krt_q025": q025,
        "krt_q975": q975,
        "nls_contrast": nls,
        "absolute_krt_nls_difference": difference,
        "sustained_sign_opposition": sustained_opposition,
        **mcmc_and_output_checks,
        **method_sensitivity_checks,
        "mcmc_gate_status": "pass" if official != "fail" else "fail",
        "method_sensitivity_status": method_sensitivity["method_sensitivity_status"],
        "method_sensitivity_reasons": method_sensitivity["method_sensitivity_reasons"],
        "core_gate_pass": not core_reasons,
        "rerun_required": rerun_required,
        "gate_status": "pass" if not reasons else "hold",
        "gate_reasons": "|".join(reasons),
    }


def evaluate_pilot_gate(release_config_path: Path | str) -> dict[str, Any]:
    scope = load_release_scope(release_config_path)
    input_audit = audit_pilot_inputs(release_config_path)
    rows: list[dict[str, Any]] = []
    for election_id, scenario_id in scope.pilot_pairs:
        initial = evaluate_krt_run(scope, election_id, scenario_id, rerun=False)
        if initial is None:
            attempt = _latest_attempt(scope, election_id, scenario_id)
            attempt_status = str(attempt.get("status", "")) if attempt else ""
            attempt_error = str(attempt.get("error", "")) if attempt else ""
            rows.append({
                "election_id": election_id,
                "scenario_id": scenario_id,
                "run_id": str(attempt.get("run_id", "")) if attempt else "",
                "fit_available": False,
                "gate_status": "hold" if attempt_status == "failed" else "pending",
                "gate_reasons": attempt_error or "fit_not_available",
            })
            continue
        rerun = None
        if str(initial.get("mcmc_substatus", "fail")) in {"caveat_severe", "fail"}:
            rerun = evaluate_krt_run(scope, election_id, scenario_id, rerun=True)
        rows.append(resolve_pilot_pair_for_gate(initial, rerun))
    frame = pd.DataFrame(rows)
    output = _production_dir(scope)
    frame.to_csv(output / "h23_pilot_gate.csv", index=False, encoding="utf-8-sig")
    go = bool(
        input_audit["ready_for_pilot_fits"]
        and len(frame) == len(scope.pilot_pairs)
        and frame["gate_status"].eq("pass").all()
    )
    result = {
        "release_id": scope.release_id,
        "pilot_pairs_expected": len(scope.pilot_pairs),
        "pilot_pairs_available": int(frame.get("fit_available", pd.Series(dtype=bool)).fillna(False).sum()),
        "gate_status_counts": frame["gate_status"].value_counts(dropna=False).to_dict(),
        "go_for_remaining_runs": go,
        "remaining_runs": max(scope.expected_krt_pairs - len(scope.pilot_pairs), 0),
        "input_audit": input_audit,
    }
    write_json(output / "h23_pilot_gate.json", result)
    return result


__all__ = [
    "audit_pilot_inputs",
    "evaluate_krt_run",
    "evaluate_pilot_gate",
    "intervals_compatible",
    "method_sensitivity_assessment",
    "resolve_pilot_pair_for_gate",
]
