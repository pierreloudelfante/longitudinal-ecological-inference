from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .paths import DOCS_DIR, OUTPUT_DIR, RUNS_DIR, ensure_runtime_dirs
from .run_2x2_batch import run_2x2
from .spec_registry import ELECTION_BY_ID, SCENARIO_BY_ID
from .utils import write_json


PRIORITY_ELECTIONS = ("leg_1962_r1", "leg_1986_r1", "leg_2022_r1")
PRIORITY_SCENARIOS = ("H0A", "H1", "H2", "H4")
PRIORITY_MODELS = ("krt_beta_binomial", "king_truncated_normal")
AUDIT_PATH = OUTPUT_DIR / "priority_production_diagnostics.csv"
PROGRESS_PATH = OUTPUT_DIR / "priority_production_progress.json"
REPORT_PATH = DOCS_DIR / "PRIORITY_PRODUCTION_1962_1986_2022.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estimate at most four principal 2x2 hypotheses for 1962, 1986 and 2022."
    )
    parser.add_argument("--sample-size", type=int, default=2000)
    parser.add_argument("--draws", type=int, default=1000)
    parser.add_argument("--tune", type=int, default=1000)
    parser.add_argument("--chains", type=int, default=4)
    parser.add_argument("--cores", type=int, default=4)
    parser.add_argument("--target-accept", type=float, default=0.99)
    parser.add_argument("--max-treedepth", type=int, default=14)
    parser.add_argument("--random-seed", type=int, default=20260802)
    parser.add_argument("--scenarios", nargs="+", default=list(PRIORITY_SCENARIOS))
    parser.add_argument("--elections", nargs="+", default=list(PRIORITY_ELECTIONS))
    parser.add_argument("--models", nargs="+", default=list(PRIORITY_MODELS))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--progressbar", action="store_true")
    return parser.parse_args()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _flatten(dataset: Any) -> np.ndarray:
    arrays = [np.asarray(dataset[name].values, dtype=float).ravel() for name in dataset.data_vars]
    return np.concatenate(arrays) if arrays else np.array([], dtype=float)


def trace_diagnostics(trace_path: Path, *, max_treedepth: int = 10) -> dict[str, object]:
    import arviz as az

    trace = az.from_netcdf(trace_path)
    posterior = trace.posterior
    variables = list(posterior.data_vars)
    chains = int(posterior.sizes.get("chain", 0))
    draws = int(posterior.sizes.get("draw", 0))

    rhat_values = _flatten(az.rhat(trace, var_names=variables, method="rank"))
    ess_bulk_values = _flatten(az.ess(trace, var_names=variables, method="bulk"))
    ess_tail_values = _flatten(az.ess(trace, var_names=variables, method="tail"))
    rhat_values = rhat_values[np.isfinite(rhat_values)]
    ess_bulk_values = ess_bulk_values[np.isfinite(ess_bulk_values)]
    ess_tail_values = ess_tail_values[np.isfinite(ess_tail_values)]

    stats = trace.sample_stats
    divergences = int(np.asarray(stats["diverging"].values).sum()) if "diverging" in stats else -1
    tree_depth = np.asarray(stats["tree_depth"].values, dtype=float) if "tree_depth" in stats else np.array([])
    max_tree_depth = float(np.nanmax(tree_depth)) if tree_depth.size else np.nan
    max_tree_depth_hits = int(np.sum(tree_depth >= max_treedepth)) if tree_depth.size else -1
    acceptance = (
        float(np.asarray(stats["acceptance_rate"].values, dtype=float).mean())
        if "acceptance_rate" in stats
        else np.nan
    )
    # ArviZ 1.x returns a DataTree when the whole InferenceData is passed.
    # Passing the energy DataArray keeps the result directly numeric across
    # both ArviZ 0.x and 1.x.
    bfmi_values = (
        np.asarray(az.bfmi(stats["energy"]), dtype=float).ravel()
        if "energy" in stats
        else np.array([])
    )
    bfmi_values = bfmi_values[np.isfinite(bfmi_values)]

    return {
        "saved_chains": chains,
        "saved_draws_per_chain": draws,
        "divergences": divergences,
        "divergence_fraction": divergences / max(chains * draws, 1) if divergences >= 0 else np.nan,
        "max_rhat": float(rhat_values.max()) if rhat_values.size else np.nan,
        "min_ess_bulk": float(ess_bulk_values.min()) if ess_bulk_values.size else np.nan,
        "min_ess_tail": float(ess_tail_values.min()) if ess_tail_values.size else np.nan,
        "min_bfmi": float(bfmi_values.min()) if bfmi_values.size else np.nan,
        "mean_acceptance_rate": acceptance,
        "max_tree_depth": max_tree_depth,
        "max_tree_depth_hits": max_tree_depth_hits,
    }


def diagnostic_verdict(
    diagnostics: dict[str, object],
    *,
    requested_draws: int,
    requested_chains: int,
) -> tuple[str, str]:
    reasons: list[str] = []

    def finite(name: str) -> float | None:
        try:
            value = float(diagnostics[name])
        except (KeyError, TypeError, ValueError):
            return None
        return value if np.isfinite(value) else None

    chains = finite("saved_chains")
    draws = finite("saved_draws_per_chain")
    divergences = finite("divergences")
    rhat = finite("max_rhat")
    ess_bulk = finite("min_ess_bulk")
    ess_tail = finite("min_ess_tail")
    bfmi = finite("min_bfmi")
    tree_hits = finite("max_tree_depth_hits")

    if chains != requested_chains:
        reasons.append(f"chaînes sauvegardées={chains}, attendu={requested_chains}")
    if draws != requested_draws:
        reasons.append(f"draws sauvegardés={draws}, attendu={requested_draws}")
    if divergences != 0:
        reasons.append(f"divergences={divergences}")
    if rhat is None or rhat > 1.01:
        reasons.append(f"R-hat max={rhat}")
    if ess_bulk is None or ess_bulk < 400:
        reasons.append(f"ESS bulk min={ess_bulk}")
    if ess_tail is None or ess_tail < 400:
        reasons.append(f"ESS tail min={ess_tail}")
    if bfmi is None or bfmi < 0.30:
        reasons.append(f"BFMI min={bfmi}")
    if tree_hits is None or tree_hits > 0:
        reasons.append(f"atteintes profondeur max={tree_hits}")
    return ("pass", "") if not reasons else ("fail", "; ".join(reasons))


def _find_run(parameters: dict[str, object]) -> tuple[str, Path] | None:
    matches: list[tuple[str, Path, str]] = []
    keys = (
        "election_id",
        "scenario_id",
        "model_key",
        "sample_size",
        "draws",
        "tune",
        "chains",
        "cores",
        "target_accept",
        "max_treedepth",
        "random_seed",
    )
    for manifest_path in RUNS_DIR.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        observed = manifest.get("parameters", {})
        if manifest.get("status") != "success" or not isinstance(observed, dict):
            continue
        if all(observed.get(key) == parameters.get(key) for key in keys):
            matches.append(
                (str(manifest.get("run_id", manifest_path.parent.name)), manifest_path.parent, str(manifest.get("finished_at_utc", "")))
            )
    if not matches:
        return None
    run_id, run_dir, _ = max(matches, key=lambda item: item[2])
    return run_id, run_dir


def _audit_row(parameters: dict[str, object], status: str, error: str = "") -> dict[str, object]:
    row = {**parameters, "fit_status": status, "error": error, "run_id": ""}
    match = _find_run(parameters)
    if match is None:
        row.update({"diagnostic_verdict": "fail", "diagnostic_reasons": "trace de production introuvable"})
        return row
    run_id, run_dir = match
    row["run_id"] = run_id
    diagnostics = trace_diagnostics(
        run_dir / "trace.nc", max_treedepth=int(parameters["max_treedepth"])
    )
    verdict, reasons = diagnostic_verdict(
        diagnostics,
        requested_draws=int(parameters["draws"]),
        requested_chains=int(parameters["chains"]),
    )
    row.update(diagnostics)
    row.update({"diagnostic_verdict": verdict, "diagnostic_reasons": reasons})
    return row


def _write_audit(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    frame = pd.DataFrame(rows)
    if AUDIT_PATH.exists() and AUDIT_PATH.stat().st_size:
        existing = pd.read_csv(AUDIT_PATH)
        frame = pd.concat([existing, frame], ignore_index=True, sort=False)
    key = [
        "election_id",
        "scenario_id",
        "model_key",
        "sample_size",
        "draws",
        "tune",
        "chains",
        "target_accept",
        "max_treedepth",
    ]
    frame = frame.drop_duplicates(key, keep="last")
    frame.to_csv(AUDIT_PATH, index=False, encoding="utf-8-sig")
    return frame.to_dict(orient="records")


def _write_report(rows: list[dict[str, object]]) -> None:
    frame = pd.DataFrame(rows)
    passed = int(frame.get("diagnostic_verdict", pd.Series(dtype=str)).eq("pass").sum())
    total = len(frame)
    failed = frame.loc[~frame.get("diagnostic_verdict", pd.Series(index=frame.index, dtype=str)).eq("pass")]
    failed_lines = [
        f"- `{row.election_id}/{row.scenario_id}/{row.model_key}` : {row.diagnostic_reasons or row.error}"
        for row in failed.itertuples()
    ]
    report = f"""# Production MCMC prioritaire — législatives 1962, 1986 et 2022

## Périmètre

- Hypothèses principales : H0A, H1, H2 et H4 (quatre par année).
- Modèles : King — normale tronquée et KRT — bêta-binomial.
- Paramètres : 4 chaînes, 1 000 tune, 1 000 draws par chaîne, `target_accept=0,99`, profondeur d'arbre maximale {int(frame['max_treedepth'].iloc[0]) if total else 'n/a'}.
- Taille du panel demandée : {int(frame['sample_size'].iloc[0]) if total else 'n/a'} communes.

## Verdict diagnostique

{passed}/{total} ajustements passent simultanément les critères : zéro divergence, R-hat max ≤ 1,01,
ESS bulk et tail min ≥ 400, BFMI min ≥ 0,30, aucune atteinte de la profondeur d'arbre maximale,
et présence exacte des 4 × 1 000 tirages attendus.

{chr(10).join(failed_lines) if failed_lines else '- Tous les ajustements passent.'}

## Sources reproductibles

- `outputs/priority_production_diagnostics.csv` : diagnostic détaillé par ajustement ;
- `outputs/runs/<run_id>/trace.nc` : traces postérieures complètes ;
- `outputs/runs/<run_id>/longitudinal_estimates.csv` : estimations agrégées ;
- `outputs/runs/<run_id>/commune_latent_summaries.parquet` : résumés communaux.
"""
    REPORT_PATH.write_text(report, encoding="utf-8")


def main() -> None:
    ensure_runtime_dirs()
    args = parse_args()
    scenarios = tuple(dict.fromkeys(args.scenarios))
    elections = tuple(dict.fromkeys(args.elections))
    models = tuple(dict.fromkeys(args.models))
    if len(scenarios) > 4:
        raise ValueError("Le lot de production est limité à quatre hypothèses par année.")
    unknown = [scenario for scenario in scenarios if scenario not in PRIORITY_SCENARIOS]
    if unknown:
        raise ValueError(f"Hypothèses non retenues dans le lot principal : {unknown}")
    if any(election not in PRIORITY_ELECTIONS for election in elections):
        raise ValueError(f"Périodes hors lot principal : {elections}")
    if any(model not in PRIORITY_MODELS for model in models):
        raise ValueError(f"Modèles hors lot principal : {models}")
    if args.draws < 1000 or args.tune < 1000 or args.chains < 4 or args.target_accept < 0.99:
        raise ValueError("La production principale exige au moins 4 chaînes, 1 000 tune, 1 000 draws et target_accept=0.99.")

    planned = [
        (election_id, scenario_id, model_key)
        for scenario_id in scenarios
        for election_id in elections
        for model_key in models
    ]
    rows: list[dict[str, object]] = []
    started_at = _utc_now()
    for position, (election_id, scenario_id, model_key) in enumerate(planned, start=1):
        parameters = {
            "election_id": election_id,
            "scenario_id": scenario_id,
            "model_key": model_key,
            "sample_size": args.sample_size,
            "draws": args.draws,
            "tune": args.tune,
            "chains": args.chains,
            "cores": args.cores,
            "target_accept": args.target_accept,
            "max_treedepth": args.max_treedepth,
            "random_seed": args.random_seed,
        }
        write_json(
            PROGRESS_PATH,
            {
                "status": "running",
                "started_at_utc": started_at,
                "updated_at_utc": _utc_now(),
                "completed": len(rows),
                "total": len(planned),
                "current": parameters,
            },
        )
        print(f"[{position}/{len(planned)}] {election_id}/{scenario_id}/{model_key}", flush=True)
        try:
            result = run_2x2(
                ELECTION_BY_ID[election_id],
                SCENARIO_BY_ID[scenario_id],
                model_key,
                sample_size=args.sample_size,
                draws=args.draws,
                tune=args.tune,
                chains=args.chains,
                cores=args.cores,
                target_accept=args.target_accept,
                max_treedepth=args.max_treedepth,
                random_seed=args.random_seed,
                force=args.force,
                progressbar=args.progressbar,
            )
            row = _audit_row(parameters, str(result.get("status", "success")))
        except Exception as exc:
            row = _audit_row(parameters, "failed", str(exc))
            print(f"ÉCHEC: {exc}", flush=True)
        rows.append(row)
        merged_rows = _write_audit(rows)
        current_rows = [
            item
            for item in merged_rows
            if int(item.get("sample_size", -1)) == args.sample_size
            and item.get("scenario_id") in scenarios
            and item.get("election_id") in elections
            and item.get("model_key") in models
        ]
        _write_report(current_rows)
        print(
            f"Diagnostic: {row.get('diagnostic_verdict')} {row.get('diagnostic_reasons', '')}",
            flush=True,
        )

    write_json(
        PROGRESS_PATH,
        {
            "status": "completed",
            "started_at_utc": started_at,
            "finished_at_utc": _utc_now(),
            "completed": len(rows),
            "total": len(planned),
            "diagnostic_passes": sum(row.get("diagnostic_verdict") == "pass" for row in rows),
        },
    )
    print(json.dumps({"audit": str(AUDIT_PATH), "report": str(REPORT_PATH)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
