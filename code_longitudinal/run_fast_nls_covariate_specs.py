from __future__ import annotations

"""Fast, resumable covariate sensitivity fits for the 240 canonical 2x2 pairs.

The model keeps the public unweighted Rosen NLS objective and lets the two
group-specific probabilities vary on a logit scale with documented commune
covariates.  These fits are descriptive ecological sensitivity checks; they
are not individual-level or causal regressions.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from reproducibility.replication_scope import get_scope
from reproducibility.estimation_recovery import BatchEstimationError, execute_estimation_batch
from reproducibility.estimation_process import run_supervised

from .nls import NLSData, aggregate_probabilities, fit_nls, probabilities, unpack_params


ROOT = Path(__file__).resolve().parents[1]
R_RUNS = ROOT / "outputs" / "longitudinal_2000_v1" / "r_replication" / "king_ei_runs"
DEFAULT_OUTPUT = ROOT / "outputs" / "longitudinal_2000_v1" / "nls_covariates_fast"
PANEL_ID = "longitudinal_2000_v1__strict_nested_3000__seed_20260803"
MODEL_KEY = "rosen_nls_2x2_covariate_sensitivity"
SCHEMA_VERSION = "nls_covariate_sensitivity_v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def stable_seed(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "little") & 0x7FFFFFFF


def standardize(values: pd.Series, *, winsorize: bool = True) -> tuple[np.ndarray, dict[str, float]]:
    x = pd.to_numeric(values, errors="coerce").astype(float)
    if winsorize:
        lower = float(x.quantile(0.01))
        upper = float(x.quantile(0.99))
        x = x.clip(lower, upper)
    else:
        lower = float(x.min())
        upper = float(x.max())
    mean = float(x.mean())
    scale = float(x.std(ddof=0))
    if not np.isfinite(scale) or scale <= 0:
        scale = 1.0
    return ((x.to_numpy(dtype=float) - mean) / scale), {
        "mean": mean,
        "scale": scale,
        "winsor_lower": lower,
        "winsor_upper": upper,
    }


def territorial_vbbm(frame: pd.DataFrame) -> tuple[np.ndarray, list[str], dict[str, object]]:
    numeric = pd.to_numeric(frame["vbbm"], errors="coerce")
    levels = [2.0, 3.0, 4.0]
    z = np.column_stack([(numeric.to_numpy(dtype=float) == level).astype(float) for level in levels])
    return z, ["vbbm_2", "vbbm_3", "vbbm_4"], {"reference_level": 1, "coding": "three_dummies"}


def socioeconomic(frame: pd.DataFrame) -> tuple[np.ndarray, list[str], dict[str, object]]:
    revenue, revenue_meta = standardize(frame["revenue"])
    capital, capital_meta = standardize(frame["capital"])
    return (
        np.column_stack([revenue, capital]),
        ["revenue_z", "capital_z"],
        {"revenue": revenue_meta, "capital": capital_meta},
    )


def demographic(frame: pd.DataFrame) -> tuple[np.ndarray, list[str], dict[str, object]]:
    foreign, foreign_meta = standardize(frame["foreign_share"])
    return foreign[:, None], ["foreign_share_z"], {"foreign_share": foreign_meta}


def joint_parsimonious(frame: pd.DataFrame) -> tuple[np.ndarray, list[str], dict[str, object]]:
    vbbm, vbbm_meta = standardize(frame["vbbm"], winsorize=False)
    revenue, revenue_meta = standardize(frame["revenue"])
    capital, capital_meta = standardize(frame["capital"])
    foreign, foreign_meta = standardize(frame["foreign_share"])
    return (
        np.column_stack([vbbm, revenue, capital, foreign]),
        ["vbbm_z", "revenue_z", "capital_z", "foreign_share_z"],
        {
            "vbbm": vbbm_meta,
            "revenue": revenue_meta,
            "capital": capital_meta,
            "foreign_share": foreign_meta,
        },
    )


SpecBuilder = Callable[[pd.DataFrame], tuple[np.ndarray, list[str], dict[str, object]]]
SPECS: dict[str, tuple[str, SpecBuilder]] = {
    "territorial_vbbm": ("Territoriale : VBBM catégoriel", territorial_vbbm),
    "socioeconomic_revenue_capital": ("Socio-économique : revenu + capital", socioeconomic),
    "demographic_foreign_share": ("Démographique : part d'étrangers", demographic),
    "joint_parsimonious": ("Jointe parcimonieuse : VBBM + revenu + capital + étrangers", joint_parsimonious),
}


def load_scope(expected_pairs: int | None = None) -> list[dict[str, object]]:
    replication_scope = get_scope()
    if expected_pairs is None:
        expected_pairs = replication_scope.pair_count
    rows: list[dict[str, object]] = []
    for manifest_path in sorted(R_RUNS.glob("*__H*/manifest_r.json")):
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if payload.get("status") != "success":
            continue
        if (str(payload["election_id"]), str(payload["scenario_id"])) not in replication_scope.pairs:
            continue
        rows.append(
            {
                "election_id": str(payload["election_id"]),
                "scenario_id": str(payload["scenario_id"]),
                "input_csv": str(payload["input_csv"]),
                "source_manifest": str(manifest_path.relative_to(ROOT)).replace("\\", "/"),
            }
        )
    frame = pd.DataFrame(rows)
    observed_pairs = set(frame[["election_id", "scenario_id"]].itertuples(index=False, name=None)) if not frame.empty else set()
    if len(frame) != expected_pairs or observed_pairs != replication_scope.pairs:
        raise AssertionError(f"expected {expected_pairs} unique 2x2 pairs, got {len(frame)}")
    return frame.sort_values(["election_id", "scenario_id"]).to_dict("records")


def build_covariate_lookup(scope: list[dict[str, object]]) -> dict[str, pd.DataFrame]:
    by_election: dict[str, list[pd.DataFrame]] = {}
    desired = ["unit_id", "vbbm", "revenue", "capital", "foreign_share"]
    for row in scope:
        input_path = Path(str(row["input_csv"]))
        columns = pd.read_csv(input_path, nrows=0).columns.tolist()
        available = [column for column in desired if column in columns]
        frame = pd.read_csv(input_path, usecols=available, dtype={"unit_id": "string"})
        by_election.setdefault(str(row["election_id"]), []).append(frame)
    result: dict[str, pd.DataFrame] = {}
    for election_id, frames in by_election.items():
        stacked = pd.concat(frames, ignore_index=True, sort=False)
        lookup = stacked.groupby("unit_id", as_index=False).first()
        missing = [column for column in desired if column not in lookup.columns]
        if missing:
            raise ValueError(f"{election_id}: missing covariate columns {missing}")
        counts = {column: int(lookup[column].isna().sum()) for column in desired[1:]}
        for column, count in counts.items():
            if count == 0:
                continue
            numeric = pd.to_numeric(lookup[column], errors="coerce")
            if column == "vbbm":
                replacement = float(numeric.mode(dropna=True).iloc[0])
            else:
                replacement = float(numeric.median())
            lookup[column] = numeric.fillna(replacement)
        if lookup[desired].isna().any().any():
            raise ValueError(f"{election_id}: incomplete covariate lookup after imputation")
        selected = lookup[desired].copy()
        selected.attrs["imputation_counts"] = counts
        result[election_id] = selected
    return result


def fit_pair_spec(
    row: dict[str, object],
    spec_id: str,
    lookup: pd.DataFrame,
    *,
    n_starts: int,
    max_nfev: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    started = time.perf_counter()
    input_path = Path(str(row["input_csv"]))
    raw = pd.read_csv(input_path, dtype={"unit_id": "string"})
    covariates = lookup.rename(columns={column: f"{column}__lookup" for column in lookup.columns if column != "unit_id"})
    frame = raw.merge(covariates, on="unit_id", how="left", validate="one_to_one")
    for column in ["vbbm", "revenue", "capital", "foreign_share"]:
        lookup_column = f"{column}__lookup"
        if column not in frame:
            frame[column] = frame[lookup_column]
        else:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(frame[lookup_column])

    x_columns = [column for column in frame.columns if column.startswith("X__")]
    y_columns = [column for column in frame.columns if column.startswith("Y__")]
    if len(x_columns) != 2 or len(y_columns) != 2:
        raise ValueError(f"{row['election_id']}/{row['scenario_id']}: expected 2x2 columns")
    required = ["N_g", *x_columns, *y_columns, "vbbm", "revenue", "capital", "foreign_share"]
    fit_frame = frame.dropna(subset=required).copy()
    x = fit_frame[x_columns].to_numpy(dtype=float)
    n = fit_frame["N_g"].to_numpy(dtype=float)
    y = fit_frame[y_columns].to_numpy(dtype=float)
    t = y / n[:, None]
    if not np.allclose(x.sum(axis=1), 1.0, atol=1e-8):
        raise ValueError("group shares do not sum to one")
    if not np.allclose(t.sum(axis=1), 1.0, atol=1e-8):
        raise ValueError("outcome shares do not sum to one")

    spec_label, builder = SPECS[spec_id]
    z, terms, transform = builder(fit_frame)
    varying = np.nanstd(z, axis=0) > 1e-12
    if not np.all(varying):
        dropped_terms = [term for term, keep in zip(terms, varying, strict=True) if not keep]
        z = z[:, varying]
        terms = [term for term, keep in zip(terms, varying, strict=True) if keep]
        transform = {**transform, "dropped_constant_terms": dropped_terms}
    if z.shape[1] == 0:
        raise ValueError(f"{spec_id}: no varying covariate term in this pair")
    if not np.isfinite(z).all():
        raise ValueError(f"{spec_id}: non-finite design matrix")
    data = NLSData(x=x, t=t, n=n, z=z)
    seed = stable_seed(str(row["election_id"]), str(row["scenario_id"]), spec_id)
    best, starts = fit_nls(
        data,
        n_starts=n_starts,
        start_scale=0.35,
        n_start_strata=5,
        max_nfev=max_nfev,
        tolerance=1e-8,
        random_seed=seed,
    )
    pi, fitted = probabilities(best.x, x, z, t.shape[1])
    aggregates = aggregate_probabilities(x, n, pi)
    jacobian = np.asarray(best.jac, dtype=float)
    singular = np.linalg.svd(jacobian, compute_uv=False)
    rank = int(np.linalg.matrix_rank(jacobian))
    condition = float(singular[0] / singular[-1]) if singular.size and singular[-1] > 0 else float("inf")
    successful = [item for item in starts if bool(item["success"])]
    max_prediction_difference = max(
        (float(item["max_abs_prediction_difference_from_best"]) for item in starts), default=float("nan")
    )
    if not bool(best.success) or not np.isfinite(float(best.cost)):
        diagnostic_status = "fail"
    elif rank < best.x.size or not np.isfinite(condition) or condition > 1e8 or max_prediction_difference > 0.05:
        diagnostic_status = "warning"
    else:
        diagnostic_status = "pass"
    elapsed = time.perf_counter() - started
    election_id = str(row["election_id"])
    family = "legislative" if election_id.startswith("leg_") else "presidential"
    year = int(election_id.split("_")[1])
    round_number = int(election_id.rsplit("r", 1)[1])
    estimate_rows = []
    for estimand, estimate in [
        ("b_1", aggregates[0, 0]),
        ("b_2", aggregates[1, 0]),
        ("b_1_minus_b_2", aggregates[0, 0] - aggregates[1, 0]),
    ]:
        estimate_rows.append(
            {
                "panel_id": PANEL_ID,
                "election_id": election_id,
                "election_family": family,
                "year": year,
                "round": round_number,
                "scenario_id": str(row["scenario_id"]),
                "model_key": MODEL_KEY,
                "spec_id": spec_id,
                "spec_label": spec_label,
                "covariate_terms": "|".join(terms),
                "estimand": estimand,
                "estimate": float(estimate),
                "n_communes": int(len(fit_frame)),
                "N_total": int(n.sum()),
                "objective_sse_unweighted": float(np.sum((t[:, :-1] - fitted[:, :-1]) ** 2)),
                "rmse_unweighted": float(np.sqrt(np.mean((t[:, :-1] - fitted[:, :-1]) ** 2))),
                "n_parameters": int(best.x.size),
                "n_starts": int(n_starts),
                "n_successful_starts": int(len(successful)),
                "max_abs_prediction_difference": float(max_prediction_difference),
                "jacobian_rank": rank,
                "jacobian_condition": condition,
                "optimizer_success": bool(best.success),
                "optimizer_status": int(best.status),
                "nfev": int(best.nfev),
                "elapsed_seconds": float(elapsed),
                "diagnostic_status": diagnostic_status,
                "interpretation_status": "descriptive_ecological_sensitivity_not_causal",
                "source_manifest": str(row["source_manifest"]),
            }
        )

    coefficient_array = unpack_params(best.x, 2, 2, len(terms) + 1)
    coefficient_rows = []
    for group_index, x_column in enumerate(x_columns):
        for term_index, term in enumerate(["intercept", *terms]):
            coefficient_rows.append(
                {
                    "panel_id": PANEL_ID,
                    "election_id": election_id,
                    "year": year,
                    "round": round_number,
                    "scenario_id": str(row["scenario_id"]),
                    "spec_id": spec_id,
                    "social_group": x_column.removeprefix("X__"),
                    "vote_category": y_columns[0].removeprefix("Y__"),
                    "reference_vote_category": y_columns[1].removeprefix("Y__"),
                    "term": term,
                    "estimate_logit": float(coefficient_array[group_index, 0, term_index]),
                    "diagnostic_status": diagnostic_status,
                }
            )
    diagnostics = {
        "schema_version": SCHEMA_VERSION,
        "status": "success",
        "panel_id": PANEL_ID,
        "election_id": election_id,
        "scenario_id": str(row["scenario_id"]),
        "spec_id": spec_id,
        "spec_label": spec_label,
        "terms": terms,
        "transform": transform,
        "covariate_imputation_counts": lookup.attrs.get("imputation_counts", {}),
        "n_communes": int(len(fit_frame)),
        "n_parameters": int(best.x.size),
        "n_starts": int(n_starts),
        "n_successful_starts": int(len(successful)),
        "objective_sse_unweighted": estimate_rows[0]["objective_sse_unweighted"],
        "rmse_unweighted": estimate_rows[0]["rmse_unweighted"],
        "jacobian_rank": rank,
        "jacobian_condition": condition,
        "max_abs_prediction_difference": max_prediction_difference,
        "optimizer_success": bool(best.success),
        "optimizer_message": str(best.message),
        "nfev": int(best.nfev),
        "elapsed_seconds": elapsed,
        "diagnostic_status": diagnostic_status,
        "random_seed": seed,
        "finished_at_utc": utc_now(),
        "source_manifest": str(row["source_manifest"]),
    }
    return pd.DataFrame(estimate_rows), pd.DataFrame(coefficient_rows), diagnostics


def _fit_and_save_covariate(
    row: dict[str, object], spec_id: str, lookup: pd.DataFrame, run_dir: Path,
    *, n_starts: int, max_nfev: int,
) -> dict[str, object]:
    """Scientific one-item body used only inside the supervised child."""
    estimates, coefficients, manifest = fit_pair_spec(
        row, spec_id, lookup, n_starts=n_starts, max_nfev=max_nfev,
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    estimates.to_csv(run_dir / "estimates.csv", index=False, encoding="utf-8-sig")
    coefficients.to_csv(run_dir / "coefficients.csv", index=False, encoding="utf-8-sig")
    if manifest.get("status") != "success":
        raise RuntimeError(f"Covariate estimation returned unsuccessful status: {manifest.get('status')}")
    atomic_json(run_dir / "manifest.json", manifest)
    return manifest


def consolidate(output_root: Path, expected_runs: int) -> dict[str, object]:
    replication_scope = get_scope()
    estimates = []
    coefficients = []
    diagnostics = []
    for manifest_path in sorted((output_root / "runs").glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "success":
            continue
        if (str(manifest["election_id"]), str(manifest["scenario_id"])) not in replication_scope.pairs:
            continue
        run_dir = manifest_path.parent
        estimates.append(pd.read_csv(run_dir / "estimates.csv"))
        coefficients.append(pd.read_csv(run_dir / "coefficients.csv"))
        diagnostics.append(manifest)
    if len(estimates) != expected_runs:
        raise AssertionError(f"expected {expected_runs} successful runs, got {len(estimates)}")
    estimate_frame = pd.concat(estimates, ignore_index=True)
    coefficient_frame = pd.concat(coefficients, ignore_index=True)
    diagnostic_frame = pd.DataFrame(diagnostics)
    output_root.mkdir(parents=True, exist_ok=True)
    estimate_frame.to_parquet(output_root / "longitudinal_nls_covariates.parquet", index=False, compression="zstd")
    coefficient_frame.to_parquet(output_root / "longitudinal_nls_covariate_coefficients.parquet", index=False, compression="zstd")
    diagnostic_frame.to_csv(output_root / "nls_covariate_diagnostics.csv", index=False, encoding="utf-8-sig")
    return {
        "successful_runs": len(estimates),
        "estimate_rows": len(estimate_frame),
        "coefficient_rows": len(coefficient_frame),
        "diagnostic_counts": diagnostic_frame["diagnostic_status"].value_counts().to_dict(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--spec", action="append", choices=sorted(SPECS))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--n-starts", type=int, default=4)
    parser.add_argument("--max-nfev", type=int, default=1200)
    parser.add_argument("--expected-pairs", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--supervise", action="store_true",
                        help="Isoler chaque calcul et appliquer les limites du lanceur professeur")
    parser.add_argument("--internal-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--internal-election-id", help=argparse.SUPPRESS)
    parser.add_argument("--internal-scenario-id", help=argparse.SUPPRESS)
    parser.add_argument("--internal-spec-id", choices=sorted(SPECS), help=argparse.SUPPRESS)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    if args.internal_worker:
        if not args.internal_election_id or not args.internal_scenario_id or not args.internal_spec_id:
            parser.error("internal worker requires election, scenario and spec")
        internal_scope = load_scope(expected_pairs=args.expected_pairs)
        selected = [row for row in internal_scope
                    if str(row["election_id"]) == args.internal_election_id
                    and str(row["scenario_id"]) == args.internal_scenario_id]
        if len(selected) != 1:
            raise ValueError("internal covariate key absent, duplicated, or outside scope")
        # ``build_covariate_lookup`` is election-local: no row from another
        # election can contribute to this fit.  Keep the full-scope validation
        # above, then read only this election's 8--10 source matrices inside
        # the isolated worker instead of rereading all 240 matrices for every
        # one of the 960 supervised fits.
        election_scope = [
            row for row in internal_scope
            if str(row["election_id"]) == args.internal_election_id
        ]
        lookup = build_covariate_lookup(election_scope)
        key = f"{args.internal_election_id}__{args.internal_scenario_id}__{args.internal_spec_id}"
        manifest = _fit_and_save_covariate(
            selected[0], args.internal_spec_id, lookup[args.internal_election_id],
            output_root / "runs" / key, n_starts=args.n_starts, max_nfev=args.max_nfev,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return
    selected_specs = args.spec or list(SPECS)
    scope = load_scope(expected_pairs=args.expected_pairs)
    lookup = build_covariate_lookup(scope)
    work = [(row, spec_id) for row in scope for spec_id in selected_specs]
    if args.limit is not None:
        work = work[: args.limit]
    status_path = output_root / "status.json"
    status = {
        "schema_version": SCHEMA_VERSION,
        "status": "running",
        "started_at_utc": utc_now(),
        "pairs_total": len(scope),
        "specs": selected_specs,
        "runs_planned": len(work),
        "runs_completed": 0,
        "current": None,
    }
    atomic_json(status_path, status)
    completed_runs: set[str] = set()

    def run_one(item):
        row, spec_id = item
        run_name = f"{row['election_id']}__{row['scenario_id']}__{spec_id}"
        run_dir = output_root / "runs" / run_name
        manifest_path = run_dir / "manifest.json"
        if manifest_path.is_file() and not args.force:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if existing.get("status") == "success":
                required = [run_dir / "estimates.csv", run_dir / "coefficients.csv"]
                if not all(path.is_file() and path.stat().st_size > 0 for path in required):
                    raise RuntimeError(f"Covariate success is missing saved outputs: {run_name}")
                completed_runs.add(run_name)
                return existing
        run_dir.mkdir(parents=True, exist_ok=True)
        status["current"] = run_name
        status["status"] = "running"
        status["runs_completed"] = len(completed_runs)
        atomic_json(status_path, status)
        try:
            if args.supervise:
                safe = re.sub(r"[^A-Za-z0-9_.-]", "_", run_name)
                state = ROOT / ".runtime" / ("replication_v2" if get_scope().is_full else "replication_court")
                log = state / "estimation_processes" / "covariate" / f"{safe}.log"
                command = [
                    sys.executable, "-m", "code_longitudinal.run_fast_nls_covariate_specs",
                    "--internal-worker", "--output-root", str(output_root),
                    "--internal-election-id", str(row["election_id"]),
                    "--internal-scenario-id", str(row["scenario_id"]),
                    "--internal-spec-id", spec_id,
                    "--n-starts", str(args.n_starts), "--max-nfev", str(args.max_nfev),
                    "--expected-pairs", str(len(scope)),
                ]
                run_supervised(
                    command, family="covariate", key=run_name, cwd=ROOT,
                    stdout_path=log, environment=os.environ.copy(),
                )
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            else:
                manifest = _fit_and_save_covariate(
                    row, spec_id, lookup[str(row["election_id"])], run_dir,
                    n_starts=args.n_starts, max_nfev=args.max_nfev,
                )
            if manifest.get("status") != "success":
                raise RuntimeError(f"Covariate estimation returned unsuccessful status: {manifest.get('status')}")
            required = [run_dir / "estimates.csv", run_dir / "coefficients.csv"]
            if not all(path.is_file() and path.stat().st_size > 0 for path in required):
                raise RuntimeError(f"Covariate success is missing saved outputs: {run_name}")
            completed_runs.add(run_name)
        except Exception as exc:
            atomic_json(
                manifest_path,
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "failed",
                    "election_id": row["election_id"],
                    "scenario_id": row["scenario_id"],
                    "spec_id": spec_id,
                    "error": str(exc),
                    "finished_at_utc": utc_now(),
                },
            )
            status.update({"status": "failed", "current": run_name, "error": str(exc)})
            atomic_json(status_path, status)
            raise
        return manifest

    replication_scope = get_scope()
    try:
        execute_estimation_batch(
            work, batch_name="nls_covariates",
            key_fn=lambda item: f"{item[0]['election_id']}__{item[0]['scenario_id']}__{item[1]}", run=run_one,
            state_dir=ROOT / ".runtime" / ("replication_v2" if replication_scope.is_full else "replication_court") / "estimation_failures",
            retry_failed=os.environ.get("LONGITUDINAL_RETRY_FAILED") == "1",
        )
    except BatchEstimationError:
        status.update(status="failed", runs_completed=len(completed_runs), finished_at_utc=utc_now())
        atomic_json(status_path, status)
        raise
    summary = consolidate(output_root, len(work))
    status.pop("error", None)  # Resolved transient errors remain in the batch receipt history.
    status.update(
        {
            "status": "complete",
            "finished_at_utc": utc_now(),
            "runs_completed": len(completed_runs),
            "current": None,
            **summary,
        }
    )
    atomic_json(status_path, status)
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
