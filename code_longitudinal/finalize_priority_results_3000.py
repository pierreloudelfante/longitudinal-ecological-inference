"""Finaliseur reproductible des résultats KRT 3 000 communes.

Ce module est volontairement indépendant des finaliseurs V1 et V2/500.  Il
ne lance jamais PyMC : il ne peut produire une livraison que lorsque les six
fits requis H0A/H1 x 1962/1986/2022 sont marqués ``success`` dans le registre
de production et satisfont le contrat fixe du panel commun.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import matplotlib.pyplot as plt
import arviz as az
import numpy as np
import pandas as pd

from .density_figures_v2 import generate_density_figures
from .identification_v2 import assess_identification
from .paths import DOCS_DIR, FIGURE_DIR, OUTPUT_DIR, ROOT, RUNS_DIR, ensure_runtime_dirs
from .postprocess_aggregates_v2 import aggregate_krt_trace_files_v2, summarize_krt_aggregates_v2
from .prepare_inputs import x_columns, y_columns
from .spec_registry import SCENARIO_BY_ID
from .utils import file_sha256, write_json


FINALIZER_SCHEMA_VERSION = "priority_results_3000_finalizer_v1.3"
OUTPUT_PATH = OUTPUT_DIR / "v2" / "priority_3000_final"
FIGURE_PATH = FIGURE_DIR / "v2" / "priority_3000_final"
REPORT_PATH = DOCS_DIR / "PRIORITY_RESULTS_3000_FINAL.md"
SAMPLING_PATH = DOCS_DIR / "METHODE_ECHANTILLONNAGE_PANEL_3000.md"
PROJECT_GUIDE_PATH = DOCS_DIR / "README_PRODUCTION_3000_H0A_H1.md"
WORK_SUMMARY_PATH = DOCS_DIR / "RESUME_TRAVAIL_ET_ANALYSES_3000.md"
DENSITY_REVIEW_PATH = DOCS_DIR / "COMPARAISON_DENSITES_JOINTES_3_PERIODES.md"
METHODOLOGY_PATH = DOCS_DIR / "METHODOLOGIE_ET_CHOIX_SENSIBLES_3000.md"
PROFESSOR_REPORT_PATH = DOCS_DIR / "RESUME_GENERAL_PROFESSEUR_3000.md"
ZIP_PATH = ROOT / "deliverables" / "longitudinal_priority_results_v2_3000_H0A_H1_complete.zip"
SHA_PATH = ZIP_PATH.with_suffix(".zip.sha256")
PROGRESS_PATH = OUTPUT_DIR / "v2" / "priority_production_progress_v2.json"
PANEL_PATH = ROOT / "panel" / "panel_3000_common_1962_1986_2022_v2.csv"
PANEL_MANIFEST_PATH = PANEL_PATH.with_name("panel_3000_common_1962_1986_2022_v2_manifest.json")
PANEL_BALANCE_PATH = PANEL_PATH.with_name("panel_3000_common_1962_1986_2022_v2_balance.csv")
PANEL_ATTEMPTS_PATH = PANEL_PATH.with_name("panel_3000_common_1962_1986_2022_v2_attempts.csv")

SCENARIOS = ("H0A", "H1")
ELECTIONS = ("leg_1962_r1", "leg_1986_r1", "leg_2022_r1")
YEARS = (1962, 1986, 2022)
FIXED_PARAMETERS = {
    "sample_size": 3000,
    "draws": 1000,
    "tune": 1000,
    "chains": 4,
    "target_accept": 0.99,
    "max_treedepth": 14,
    "model_key": "krt_beta_binomial",
}
CHANGE_SEED = 20260804
CHANGE_RESAMPLES = 50_000

BLUE, GOLD, RED, INK = "#315C8C", "#C6922B", "#A14E45", "#20262E"


@dataclass(frozen=True)
class CompletedFit:
    """One validated fit authorised to enter the 3 000-commune release."""

    item_id: str
    election_id: str
    scenario_id: str
    year: int
    run_id: str
    run_dir: Path
    item: Mapping[str, Any]
    manifest: Mapping[str, Any]


def _year(election_id: str) -> int:
    try:
        return int(election_id.split("_")[1][:4])
    except (IndexError, ValueError) as exc:
        raise ValueError(f"identifiant d'élection invalide : {election_id}") from exc


def required_item_id(election_id: str, scenario_id: str) -> str:
    return f"{election_id}__{scenario_id}__{FIXED_PARAMETERS['model_key']}"


def required_item_ids() -> tuple[str, ...]:
    return tuple(required_item_id(election_id, scenario_id) for scenario_id in SCENARIOS for election_id in ELECTIONS)


def _require_fixed_contract(values: Mapping[str, Any], *, label: str) -> None:
    for name, expected in FIXED_PARAMETERS.items():
        observed = values.get(name)
        if isinstance(expected, float):
            valid = observed is not None and np.isclose(float(observed), expected)
        else:
            valid = observed == expected
        if not valid:
            raise ValueError(f"{label}: paramètre {name}={observed!r}, attendu {expected!r}")


def _model_input_path(manifest: Mapping[str, Any]) -> Path:
    candidates = [Path(path) for path in manifest.get("input_sha256", {}) if str(path).endswith(".parquet")]
    if len(candidates) != 1:
        raise ValueError(f"le manifeste doit référencer un unique input parquet, observé={candidates}")
    if not candidates[0].exists():
        raise FileNotFoundError(f"input du fit absent : {candidates[0]}")
    return candidates[0]


def load_completed_required_fits(
    progress_path: Path = PROGRESS_PATH,
    runs_dir: Path = RUNS_DIR,
) -> list[CompletedFit]:
    """Validate the production registry and return exactly six required fits.

    The progress file is used only to locate the canonical runs.  Diagnostics
    are deliberately not read from its mirrored audit summary.
    """

    progress = json.loads(Path(progress_path).read_text(encoding="utf-8"))
    _require_fixed_contract(progress.get("configuration", {}), label="configuration de production")
    panel = progress.get("panel", {})
    if int(panel.get("n_communes", -1)) != 3000:
        raise ValueError("le registre de production ne décrit pas un panel de 3 000 communes")
    registered_panel_path = Path(str(panel.get("panel_path", "")))
    registered_panel_sha = str(panel.get("panel_sha256", ""))
    if not registered_panel_path.exists() or file_sha256(registered_panel_path) != registered_panel_sha:
        raise ValueError("le panel du registre est absent ou son SHA-256 ne correspond plus")
    items = progress.get("items", {})
    completed: list[CompletedFit] = []
    for scenario_id in SCENARIOS:
        for election_id in ELECTIONS:
            item_id = required_item_id(election_id, scenario_id)
            item = items.get(item_id)
            if not item or item.get("status") != "success":
                status = None if not item else item.get("status")
                raise RuntimeError(f"finalisation refusée : {item_id} n'est pas terminé (status={status!r})")
            _require_fixed_contract(item, label=item_id)
            if str(item.get("panel_sha256", "")) != registered_panel_sha:
                raise ValueError(f"{item_id}: SHA-256 de panel différent du registre")
            if item.get("election_id") != election_id or item.get("scenario_id") != scenario_id:
                raise ValueError(f"{item_id}: identité incohérente dans le registre")
            run_id = str(item.get("run_id") or "")
            run_dir = Path(runs_dir) / run_id
            manifest_path = run_dir / "manifest.json"
            if not run_id or not manifest_path.exists():
                raise FileNotFoundError(f"{item_id}: manifeste de run introuvable")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            parameters = manifest.get("parameters", {})
            _require_fixed_contract(parameters, label=f"manifest {run_id}")
            if Path(str(parameters.get("panel_path", ""))).resolve() != registered_panel_path.resolve():
                raise ValueError(f"manifest {run_id}: chemin de panel différent du registre")
            preparation = manifest.get("preparation_manifest", {})
            if str(preparation.get("panel_source_sha256", "")) != registered_panel_sha:
                raise ValueError(f"manifest {run_id}: empreinte du panel absente ou incohérente")
            if manifest.get("status") != "success" or manifest.get("election_id") != election_id or manifest.get("scenario_id") != scenario_id:
                raise ValueError(f"manifest {run_id}: statut ou identité incompatible")
            if int(manifest.get("n_communes_used", -1)) != 3000:
                raise ValueError(f"manifest {run_id}: n_communes_used doit être 3000")
            completed.append(CompletedFit(item_id, election_id, scenario_id, _year(election_id), run_id, run_dir, item, manifest))
    if len(completed) != 6 or len({fit.run_id for fit in completed}) != 6:
        raise ValueError("la livraison nécessite exactement six runs distincts H0A/H1 × trois dates")
    return completed


def canonical_diagnostic(run_dir: Path) -> dict[str, Any]:
    """Read the one authoritative diagnostic attached to a successful run."""

    path = Path(run_dir) / "mcmc_diagnostics_v2.json"
    if not path.exists():
        raise FileNotFoundError(f"diagnostic MCMC canonique absent : {path}")
    diagnostic = json.loads(path.read_text(encoding="utf-8"))
    required = {"diagnostic_schema_version", "fit_status", "mcmc_status", "saved_chains", "saved_draws_per_chain"}
    missing = sorted(required.difference(diagnostic))
    if missing:
        raise ValueError(f"diagnostic canonique incomplet ({path.name}) : {missing}")
    if diagnostic["diagnostic_schema_version"] != "mcmc_diagnostics_v2.0":
        raise ValueError(f"version de diagnostic non reconnue : {diagnostic['diagnostic_schema_version']!r}")
    if diagnostic["fit_status"] != "success" or diagnostic["mcmc_status"] not in {"pass", "caveat", "fail"}:
        raise ValueError(f"diagnostic canonique invalide pour {run_dir.name}")
    if int(diagnostic["saved_chains"]) != 4 or int(diagnostic["saved_draws_per_chain"]) != 1000:
        raise ValueError(f"diagnostic {run_dir.name}: 4 chaînes et 1 000 draws sauvegardés sont requis")
    return diagnostic


def beta_scope_diagnostic(diagnostic: Mapping[str, Any]) -> dict[str, Any]:
    """Build a beta-centred diagnostic with conservative non-beta reserves.

    R-hat and ESS are restricted to the 6,000 ``b_1``/``b_2`` parameters.
    Divergences, BFMI and tree depth remain sampler-wide checks.  A caveat on
    the four hyperparameters cannot replace the beta metrics, but it does turn
    the final assessment into ``satisfactory_with_reserve``.
    """

    beta_blocks = [
        row for row in diagnostic.get("block_metrics", [])
        if row.get("block") == "latent_preferences"
    ]
    beta_variables = [
        row for row in diagnostic.get("variable_metrics", [])
        if row.get("variable") in {"b_1", "b_2"}
    ]
    if len(beta_blocks) != 1 or {row.get("variable") for row in beta_variables} != {"b_1", "b_2"}:
        raise ValueError("le diagnostic source ne contient pas un bloc beta b_1/b_2 complet")
    block = beta_blocks[0]
    if int(block.get("n_parameters", -1)) != 6000:
        raise ValueError(f"nombre de paramètres beta inattendu: {block.get('n_parameters')!r}")
    non_beta_blocks = [
        row for row in diagnostic.get("block_metrics", [])
        if row.get("block") == "hyperparameters"
    ]
    if len(non_beta_blocks) != 1 or int(non_beta_blocks[0].get("n_parameters", -1)) != 4:
        raise ValueError("le diagnostic source ne contient pas les quatre hyperparamètres attendus")
    non_beta_block = non_beta_blocks[0]

    thresholds = {
        "rhat_pass": 1.01,
        "rhat_fail": 1.05,
        "ess_bulk_pass": 400.0,
        "ess_bulk_fail": 100.0,
        "ess_tail_pass": 400.0,
        "ess_tail_fail": 100.0,
        "bfmi_pass": 0.30,
        "bfmi_fail": 0.20,
        "divergence_fraction_fail": 0.001,
        "treedepth_fraction_fail": 0.01,
        **diagnostic.get("thresholds", {}),
    }
    max_rhat = float(block["max_rhat"])
    min_ess_bulk = float(block["min_ess_bulk"])
    min_ess_tail = float(block["min_ess_tail"])
    min_bfmi = float(diagnostic["min_bfmi"])
    divergences = int(diagnostic.get("divergences", 0))
    divergence_fraction = float(diagnostic.get("divergence_fraction", 0.0))
    treedepth_hits = int(diagnostic.get("max_treedepth_hits", 0))
    treedepth_fraction = float(diagnostic.get("max_treedepth_hit_fraction", 0.0))

    reasons: list[str] = []
    severity = 0

    def register(value: bool, reason: str, level: int) -> None:
        nonlocal severity
        if value:
            reasons.append(reason)
            severity = max(severity, level)

    register(max_rhat > float(thresholds["rhat_fail"]), "beta_max_rhat_above_fail_threshold", 2)
    register(
        float(thresholds["rhat_pass"]) < max_rhat <= float(thresholds["rhat_fail"]),
        "beta_max_rhat_above_pass_threshold",
        1,
    )
    register(min_ess_bulk < float(thresholds["ess_bulk_fail"]), "beta_min_ess_bulk_below_fail_threshold", 2)
    register(
        float(thresholds["ess_bulk_fail"]) <= min_ess_bulk < float(thresholds["ess_bulk_pass"]),
        "beta_min_ess_bulk_below_pass_threshold",
        1,
    )
    register(min_ess_tail < float(thresholds["ess_tail_fail"]), "beta_min_ess_tail_below_fail_threshold", 2)
    register(
        float(thresholds["ess_tail_fail"]) <= min_ess_tail < float(thresholds["ess_tail_pass"]),
        "beta_min_ess_tail_below_pass_threshold",
        1,
    )
    register(min_bfmi < float(thresholds["bfmi_fail"]), "min_bfmi_below_fail_threshold", 2)
    register(
        float(thresholds["bfmi_fail"]) <= min_bfmi < float(thresholds["bfmi_pass"]),
        "min_bfmi_below_pass_threshold",
        1,
    )
    register(divergence_fraction > float(thresholds["divergence_fraction_fail"]), "divergence_fraction_above_fail_threshold", 2)
    register(0 < divergences and divergence_fraction <= float(thresholds["divergence_fraction_fail"]), "nonzero_divergences", 1)
    register(treedepth_fraction > float(thresholds["treedepth_fraction_fail"]), "treedepth_fraction_above_fail_threshold", 2)
    register(0 < treedepth_hits and treedepth_fraction <= float(thresholds["treedepth_fraction_fail"]), "nonzero_treedepth_saturation", 1)
    register(str(diagnostic.get("fit_status")) != "success", "fit_not_successful", 2)
    beta_diagnostic_status = ("pass", "caveat", "fail")[severity]

    non_beta_reasons: list[str] = []
    non_beta_severity = 0

    def register_non_beta(value: bool, reason: str, level: int) -> None:
        nonlocal non_beta_severity
        if value:
            non_beta_reasons.append(reason)
            non_beta_severity = max(non_beta_severity, level)

    non_beta_max_rhat = float(non_beta_block["max_rhat"])
    non_beta_min_ess_bulk = float(non_beta_block["min_ess_bulk"])
    non_beta_min_ess_tail = float(non_beta_block["min_ess_tail"])
    register_non_beta(
        non_beta_max_rhat > float(thresholds["rhat_fail"]),
        "non_beta_max_rhat_above_fail_threshold", 2,
    )
    register_non_beta(
        float(thresholds["rhat_pass"]) < non_beta_max_rhat <= float(thresholds["rhat_fail"]),
        "non_beta_max_rhat_above_pass_threshold", 1,
    )
    register_non_beta(
        non_beta_min_ess_bulk < float(thresholds["ess_bulk_fail"]),
        "non_beta_min_ess_bulk_below_fail_threshold", 2,
    )
    register_non_beta(
        float(thresholds["ess_bulk_fail"]) <= non_beta_min_ess_bulk < float(thresholds["ess_bulk_pass"]),
        "non_beta_min_ess_bulk_below_pass_threshold", 1,
    )
    register_non_beta(
        non_beta_min_ess_tail < float(thresholds["ess_tail_fail"]),
        "non_beta_min_ess_tail_below_fail_threshold", 2,
    )
    register_non_beta(
        float(thresholds["ess_tail_fail"]) <= non_beta_min_ess_tail < float(thresholds["ess_tail_pass"]),
        "non_beta_min_ess_tail_below_pass_threshold", 1,
    )
    non_beta_parameter_status = ("pass", "caveat", "fail")[non_beta_severity]
    overall_severity = max(severity, non_beta_severity)
    status = ("pass", "caveat", "fail")[overall_severity]
    assessment = ("satisfactory", "satisfactory_with_reserve", "insufficient")[overall_severity]
    assessment_label = ("satisfaisant", "satisfaisant avec réserve", "insuffisant")[overall_severity]

    worst_rhat = max(beta_variables, key=lambda row: float(row["max_rhat"]))["variable"]
    worst_bulk = min(beta_variables, key=lambda row: float(row["min_ess_bulk"]))["variable"]
    worst_tail = min(beta_variables, key=lambda row: float(row["min_ess_tail"]))["variable"]
    return {
        "diagnostic_schema_version": "beta_centered_mcmc_diagnostics_3000_v1.1",
        "source_diagnostic_schema_version": diagnostic.get("diagnostic_schema_version"),
        "source_trace_path": diagnostic.get("trace_path", ""),
        "source_all_parameter_diagnostic": "each_run/mcmc_diagnostics_v2.json",
        "diagnostic_scope": "beta_headline_metrics_with_non_beta_parameter_reserve_and_sampler_checks",
        "headline_metric_scope": "worst_over_6000_communal_beta_parameters_b1_b2",
        "fit_status": diagnostic.get("fit_status"),
        "mcmc_status": status,
        "mcmc_assessment": assessment,
        "mcmc_assessment_label": assessment_label,
        "mcmc_reasons": reasons + non_beta_reasons,
        "beta_diagnostic_status": beta_diagnostic_status,
        "beta_diagnostic_reasons": reasons,
        "non_beta_parameter_status": non_beta_parameter_status,
        "non_beta_parameter_reasons": non_beta_reasons,
        "non_beta_parameter_count": int(non_beta_block["n_parameters"]),
        "saved_chains": int(diagnostic["saved_chains"]),
        "saved_draws_per_chain": int(diagnostic["saved_draws_per_chain"]),
        "posterior_variables": ["b_1", "b_2"],
        "beta_parameter_count": int(block["n_parameters"]),
        "max_rhat": max_rhat,
        "min_ess_bulk": min_ess_bulk,
        "min_ess_tail": min_ess_tail,
        "worst_rhat_beta_variable": worst_rhat,
        "worst_ess_bulk_beta_variable": worst_bulk,
        "worst_ess_tail_beta_variable": worst_tail,
        "divergences": divergences,
        "divergence_fraction": divergence_fraction,
        "bfmi_by_chain": diagnostic.get("bfmi_by_chain", []),
        "min_bfmi": min_bfmi,
        "configured_max_treedepth": diagnostic.get("configured_max_treedepth"),
        "observed_max_treedepth": diagnostic.get("observed_max_treedepth"),
        "max_treedepth_hits": treedepth_hits,
        "max_treedepth_hit_fraction": treedepth_fraction,
        "mean_acceptance_rate": diagnostic.get("mean_acceptance_rate"),
        "thresholds": thresholds,
        "beta_variable_metrics": beta_variables,
        "beta_block_metrics": block,
    }


def _read_latent(run_dir: Path) -> pd.DataFrame:
    parquet = run_dir / "commune_latent_summaries.parquet"
    csv = run_dir / "commune_latent_summaries.csv"
    latent = pd.read_parquet(parquet) if parquet.exists() else pd.read_csv(csv)
    required = {"unit_id", "sample_rank", "b1_weight", "b2_weight", "b1_mean", "b2_mean"}
    missing = sorted(required.difference(latent.columns))
    if missing:
        raise ValueError(f"latents incomplets ({run_dir.name}) : {missing}")
    if len(latent) != 3000 or latent["unit_id"].astype(str).duplicated().any():
        raise ValueError(f"latents {run_dir.name}: exactement 3 000 communes distinctes sont requises")
    ranks = pd.to_numeric(latent["sample_rank"], errors="raise").astype(int)
    if ranks.tolist() != list(range(1, 3001)):
        raise ValueError(f"latents {run_dir.name}: sample_rank doit être 1..3000 dans l'ordre")
    return latent


def _identification(fit: CompletedFit, latent: pd.DataFrame) -> dict[str, Any]:
    input_frame = pd.read_parquet(_model_input_path(fit.manifest))
    if len(input_frame) != 3000 or input_frame["unit_id"].astype(str).duplicated().any():
        raise ValueError(f"input {fit.run_id}: contrat de 3 000 unit_id uniques non respecté")
    if set(input_frame["unit_id"].astype(str)) != set(latent["unit_id"].astype(str)):
        raise ValueError(f"input {fit.run_id}: unités différentes des latents")
    scenario = SCENARIO_BY_ID[fit.scenario_id]
    group_fraction = input_frame[x_columns(scenario)[0]].to_numpy(float)
    vote_fraction = input_frame[y_columns(scenario)[0]].to_numpy(float) / input_frame["N_g"].to_numpy(float)
    return assess_identification(group_fraction, vote_fraction)


def _summary_to_estimates(summary: pd.DataFrame, fit: CompletedFit) -> pd.DataFrame:
    corrected = summary.loc[summary["aggregation_method"].eq("group_specific_population_v2")].copy()
    corrected.insert(0, "run_id", fit.run_id)
    corrected.insert(1, "election_id", fit.election_id)
    corrected.insert(2, "year", fit.year)
    corrected.insert(3, "scenario_id", fit.scenario_id)
    return corrected


def _verify_saved_aggregate(fit: CompletedFit, summary: pd.DataFrame) -> None:
    """Reconcile the finalizer's draw-wise estimate with the run-time export."""

    path = fit.run_dir / "aggregate_comparison_v2.csv"
    if not path.exists():
        raise FileNotFoundError(f"export d'agrégation absent pour {fit.run_id}: {path}")
    saved = pd.read_csv(path)
    saved = saved.loc[saved["aggregation_method"].eq("group_specific_population_v2")].copy()
    expected = summary.loc[:, ["beta_parameter", "mean", "q025", "q50", "q975"]].sort_values("beta_parameter")
    observed = saved.loc[:, ["beta_parameter", "mean", "q025", "q50", "q975"]].sort_values("beta_parameter")
    if expected["beta_parameter"].tolist() != observed["beta_parameter"].tolist():
        raise ValueError(f"{fit.run_id}: paramètres agrégés incompatibles avec l'export du run")
    difference = np.max(
        np.abs(
            expected[["mean", "q025", "q50", "q975"]].to_numpy(float)
            - observed[["mean", "q025", "q50", "q975"]].to_numpy(float)
        )
    )
    if not np.isfinite(difference) or difference > 1e-10:
        raise ValueError(f"{fit.run_id}: agrégat draw-wise non réconcilié (écart max={difference})")


def _estimand_diagnostic_rows(fit: CompletedFit, draws: Any) -> list[dict[str, Any]]:
    """Calculate chain diagnostics for the three reported aggregate estimands."""

    estimands = {
        "beta_1_aggregate": (
            draws["b_1_group_weighted"],
            "sum_i(N1_i * beta1_i) / sum_i(N1_i)",
        ),
        "beta_2_aggregate": (
            draws["b_2_group_weighted"],
            "sum_i(N2_i * beta2_i) / sum_i(N2_i)",
        ),
    }
    estimands["beta_1_minus_beta_2"] = (
        estimands["beta_1_aggregate"][0] - estimands["beta_2_aggregate"][0],
        "beta_1_aggregate - beta_2_aggregate",
    )
    rows: list[dict[str, Any]] = []
    for estimand, (values, definition) in estimands.items():
        if set(values.dims) != {"chain", "draw"} or values.sizes["chain"] != 4 or values.sizes["draw"] != 1000:
            raise ValueError(f"{fit.run_id}: dimensions inattendues pour {estimand}: {dict(values.sizes)}")
        rhat = float(np.asarray(az.rhat(values, method="rank")).squeeze())
        ess_bulk = float(np.asarray(az.ess(values, method="bulk")).squeeze())
        ess_tail = float(np.asarray(az.ess(values, method="tail")).squeeze())
        mcse_mean = float(np.asarray(az.mcse(values, method="mean")).squeeze())
        mcse_sd = float(np.asarray(az.mcse(values, method="sd")).squeeze())
        flat = np.asarray(values, dtype=float).reshape(-1)
        metrics = np.array([rhat, ess_bulk, ess_tail, mcse_mean, mcse_sd], dtype=float)
        if not np.isfinite(flat).all() or not np.isfinite(metrics).all():
            raise ValueError(f"{fit.run_id}: diagnostic non fini pour {estimand}")
        if rhat > 1.05 or ess_bulk < 100 or ess_tail < 100:
            status = "fail"
        elif rhat > 1.01 or ess_bulk < 400 or ess_tail < 400:
            status = "caveat"
        else:
            status = "pass"
        rows.append({
            "estimand_diagnostic_schema_version": "estimand_mcmc_diagnostics_3000_v1.0",
            "run_id": fit.run_id,
            "election_id": fit.election_id,
            "year": fit.year,
            "scenario_id": fit.scenario_id,
            "estimand": estimand,
            "definition": definition,
            "mean": float(flat.mean()),
            "sd": float(flat.std(ddof=1)),
            "rhat": rhat,
            "ess_bulk": ess_bulk,
            "ess_tail": ess_tail,
            "mcse_mean": mcse_mean,
            "mcse_sd": mcse_sd,
            "n_chains": int(values.sizes["chain"]),
            "draws_per_chain": int(values.sizes["draw"]),
            "estimand_mcmc_status": status,
        })
    return rows


def compute_artifacts(
    fits: Sequence[CompletedFit],
    *,
    verify_run_exports: bool = True,
) -> dict[str, pd.DataFrame]:
    """Recompute draw-wise aggregates and all statistical release tables."""

    aggregate_parts: list[pd.DataFrame] = []
    diagnostic_rows: list[dict[str, Any]] = []
    estimand_diagnostic_rows: list[dict[str, Any]] = []
    identification_rows: list[dict[str, Any]] = []
    contrast_rows: list[dict[str, Any]] = []
    latent_parts: list[pd.DataFrame] = []
    draw_index: dict[tuple[str, int], np.ndarray] = {}

    for fit in fits:
        latent = _read_latent(fit.run_dir)
        source_diagnostic = canonical_diagnostic(fit.run_dir)
        diagnostic = beta_scope_diagnostic(source_diagnostic)
        identification = _identification(fit, latent)
        draws = aggregate_krt_trace_files_v2(fit.run_dir / "trace.nc", fit.run_dir / "commune_latent_summaries.parquet")
        # The helper can expose legacy-total weights for audit comparisons.  This
        # final release writes only the corrected group-denominator estimand.
        summary = summarize_krt_aggregates_v2(draws)
        summary = summary.loc[summary["aggregation_method"].eq("group_specific_population_v2")].copy()
        if verify_run_exports:
            _verify_saved_aggregate(fit, summary)
        summary = _summary_to_estimates(summary, fit)
        aggregate_parts.append(summary)
        b1 = np.asarray(draws["b_1_group_weighted"].values, dtype=float).reshape(-1)
        b2 = np.asarray(draws["b_2_group_weighted"].values, dtype=float).reshape(-1)
        if len(b1) != 4000 or len(b2) != 4000:
            raise ValueError(f"{fit.run_id}: 4 000 tirages postérieurs agrégés attendus")
        delta = b1 - b2
        draw_index[(fit.scenario_id, fit.year)] = delta
        estimand_diagnostic_rows.extend(_estimand_diagnostic_rows(fit, draws))
        contrast_rows.append({
            "run_id": fit.run_id, "election_id": fit.election_id, "year": fit.year, "scenario_id": fit.scenario_id,
            "contrast": "beta_1_minus_beta_2", "estimate": float(delta.mean()), "lower": float(np.quantile(delta, .025)),
            "median": float(np.quantile(delta, .5)), "upper": float(np.quantile(delta, .975)),
            "probability_gt_zero": float(np.mean(delta > 0)), "n_posterior_draws": len(delta),
        })
        public_diagnostic = dict(diagnostic)
        identification_at_sampling = source_diagnostic.get("identification_status", "not_assessed")
        identification_status = str(identification["identification_status"])
        retained = (
            str(public_diagnostic["fit_status"]) == "success"
            and str(public_diagnostic["mcmc_status"]) != "fail"
            and identification_status != "fail"
        )
        reporting_reasons = []
        if str(public_diagnostic["mcmc_status"]) == "caveat":
            reporting_reasons.append("mcmc_caveat")
        if identification_status == "caveat":
            reporting_reasons.append("identification_caveat")
        reporting_status = "not_retained" if not retained else "retained_with_caveats" if reporting_reasons else "retained"
        diagnostic_rows.append({
            "run_id": fit.run_id,
            "election_id": fit.election_id,
            "year": fit.year,
            "scenario_id": fit.scenario_id,
            **public_diagnostic,
            "identification_status_at_sampling": identification_at_sampling,
            "identification_status": identification_status,
            "retained_for_descriptive_reporting": retained,
            "reporting_status": reporting_status,
            "reporting_reasons": reporting_reasons,
        })
        identification_rows.append({"run_id": fit.run_id, "election_id": fit.election_id, "year": fit.year, "scenario_id": fit.scenario_id, **identification})
        density = latent.loc[:, ["unit_id", "sample_rank", "b1_weight", "b2_weight", "b1_mean", "b2_mean"]].copy()
        density.insert(0, "run_id", fit.run_id)
        density.insert(1, "scenario_id", fit.scenario_id)
        density.insert(2, "year", fit.year)
        density.insert(3, "schema_version", "joint_latent_3000_v1.0")
        latent_parts.append(density)

    changes: list[dict[str, Any]] = []
    rng = np.random.default_rng(CHANGE_SEED)
    for scenario_id in SCENARIOS:
        for earlier, later in ((1962, 1986), (1986, 2022), (1962, 2022)):
            first, second = draw_index[(scenario_id, earlier)], draw_index[(scenario_id, later)]
            change = second[rng.integers(0, len(second), CHANGE_RESAMPLES)] - first[rng.integers(0, len(first), CHANGE_RESAMPLES)]
            changes.append({
                "scenario_id": scenario_id, "earlier_year": earlier, "later_year": later,
                "contrast_change": "delta_later_minus_delta_earlier", "estimate": float(change.mean()),
                "lower": float(np.quantile(change, .025)), "median": float(np.quantile(change, .5)),
                "upper": float(np.quantile(change, .975)), "probability_gt_zero": float(np.mean(change > 0)),
                "resamples": CHANGE_RESAMPLES, "random_seed": CHANGE_SEED,
                "assumption": "tirages postérieurs indépendants entre estimations électorales séparées",
            })
    aggregates = pd.concat(aggregate_parts, ignore_index=True)
    joint = pd.concat(latent_parts, ignore_index=True)
    if len(joint) != 18_000 or joint.duplicated(["scenario_id", "year", "unit_id"]).any():
        raise ValueError("le fichier latent joint doit contenir 18 000 lignes uniques scénario/date/commune")
    unit_sets = {
        frozenset(part["unit_id"].astype(str))
        for _, part in joint.groupby(["scenario_id", "year"], sort=False)
    }
    if len(unit_sets) != 1:
        raise ValueError("les six estimations n'utilisent pas exactement les mêmes 3 000 communes")
    return {
        "aggregates": aggregates, "contrasts": pd.DataFrame(contrast_rows), "changes": pd.DataFrame(changes),
        "diagnostics": pd.DataFrame(diagnostic_rows), "estimands": pd.DataFrame(estimand_diagnostic_rows),
        "identification": pd.DataFrame(identification_rows), "joint_latent": joint,
    }


def validate_artifacts(artifacts: Mapping[str, pd.DataFrame]) -> None:
    expected_rows = {
        "aggregates": 12,
        "contrasts": 6,
        "changes": 6,
        "diagnostics": 6,
        "estimands": 18,
        "identification": 6,
        "joint_latent": 18_000,
    }
    observed = {name: len(artifacts[name]) for name in expected_rows}
    if observed != expected_rows:
        raise AssertionError(f"comptages de livraison invalides: {observed}, attendu={expected_rows}")
    if not artifacts["diagnostics"]["mcmc_status"].isin(["pass", "caveat", "fail"]).all():
        raise AssertionError("statut MCMC canonique invalide")
    if "selected_for_interpretation" in artifacts["diagnostics"].columns:
        raise AssertionError("le champ interne selected_for_interpretation ne doit pas être publié")
    expected_scope = "beta_headline_metrics_with_non_beta_parameter_reserve_and_sampler_checks"
    if not artifacts["diagnostics"]["diagnostic_scope"].eq(expected_scope).all():
        raise AssertionError("le diagnostic publié doit porter sur les bêta communaux b_1/b_2")
    if not artifacts["diagnostics"]["beta_parameter_count"].eq(6000).all():
        raise AssertionError("le diagnostic publié doit résumer exactement 6 000 paramètres bêta")
    if not artifacts["diagnostics"]["non_beta_parameter_count"].eq(4).all():
        raise AssertionError("la réserve complémentaire doit contrôler exactement quatre hyperparamètres")
    if not artifacts["diagnostics"]["posterior_variables"].map(
        lambda variables: set(variables) == {"b_1", "b_2"}
    ).all():
        raise AssertionError("le diagnostic publié contient des variables autres que b_1 et b_2")
    if not artifacts["diagnostics"]["retained_for_descriptive_reporting"].all():
        raise AssertionError("au moins un ajustement non retenu figure dans la livraison")
    for name in ("aggregates", "contrasts", "changes", "estimands"):
        frame = artifacts[name]
        numeric = frame.select_dtypes(include="number")
        if numeric.empty or not np.isfinite(numeric.to_numpy(float)).all():
            raise AssertionError(f"valeurs numériques non finies dans {name}")


def write_artifacts(artifacts: Mapping[str, pd.DataFrame], output_path: Path = OUTPUT_PATH) -> dict[str, Path]:
    output_path.mkdir(parents=True, exist_ok=True)
    names = {
        "aggregates": "aggregate_drawwise_corrected_3000_v1.csv", "contrasts": "within_period_contrasts_3000_v1.csv",
        "changes": "between_period_contrast_changes_3000_v1.csv", "diagnostics": "canonical_mcmc_diagnostics_3000_v1.csv",
        "estimands": "estimand_mcmc_diagnostics_3000_v1.csv",
        "identification": "identification_separate_3000_v1.csv", "joint_latent": "joint_latent_3000_v1.csv",
    }
    paths = {key: output_path / filename for key, filename in names.items()}
    for key, path in paths.items():
        artifacts[key].to_csv(path, index=False, encoding="utf-8-sig")
    write_json(output_path / "release_manifest_3000_v1.json", {
        "schema_version": FINALIZER_SCHEMA_VERSION, "required_items": list(required_item_ids()),
        "fixed_parameters": FIXED_PARAMETERS, "change_resamples": CHANGE_RESAMPLES, "change_seed": CHANGE_SEED,
        "model_hyperparameters": {"king_lambda": 0.5},
        "joint_latent_rows": int(len(artifacts["joint_latent"])),
        "estimand_diagnostic_rows": int(len(artifacts["estimands"])),
        "published_diagnostic_scope": "beta_headline_metrics_with_non_beta_parameter_reserve_and_sampler_checks",
        "headline_metric_scope": "worst_over_6000_communal_beta_parameters_b1_b2",
        "published_diagnostic_source": "beta metrics from block_metrics[latent_preferences], conservative reserve from block_metrics[hyperparameters], sampler checks from each_run/mcmc_diagnostics_v2.json",
        "source_all_parameter_diagnostic": "each_run/mcmc_diagnostics_v2.json (audit artifact, not the published headline diagnostic)",
        "estimand_diagnostic_source": "draw-wise group-weighted aggregates from each_run/trace.nc",
        "run_ids": artifacts["diagnostics"]["run_id"].astype(str).tolist(),
        "canonical_diagnostic_sha256": {
            run_id: file_sha256(RUNS_DIR / run_id / "mcmc_diagnostics_v2.json")
            for run_id in artifacts["diagnostics"]["run_id"].astype(str)
        },
        "trace_sha256": {
            run_id: file_sha256(RUNS_DIR / run_id / "trace.nc")
            for run_id in artifacts["diagnostics"]["run_id"].astype(str)
        },
        "commune_latent_sha256": {
            run_id: file_sha256(RUNS_DIR / run_id / "commune_latent_summaries.parquet")
            for run_id in artifacts["diagnostics"]["run_id"].astype(str)
        },
    })
    return paths


def _save(fig: plt.Figure, stem: str, figure_path: Path = FIGURE_PATH) -> None:
    figure_path.mkdir(parents=True, exist_ok=True)
    fig.savefig(figure_path / f"{stem}.png", dpi=180, bbox_inches="tight", facecolor="white")
    fig.savefig(figure_path / f"{stem}.svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_release_figures(artifacts: Mapping[str, pd.DataFrame], figure_path: Path = FIGURE_PATH) -> None:
    aggregates = artifacts["aggregates"].query("aggregation_method == 'group_specific_population_v2'")
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), sharey=True)
    for axis, scenario_id in zip(axes, SCENARIOS, strict=True):
        part = aggregates.loc[aggregates.scenario_id.eq(scenario_id)]
        for beta, color in (("b_1", BLUE), ("b_2", GOLD)):
            data = part.loc[part.beta_parameter.eq(beta)].sort_values("year")
            axis.errorbar(data.year, data["mean"], yerr=np.vstack((data["mean"] - data.q025, data.q975 - data["mean"])), fmt="o", color=color, capsize=3, label=beta)
        axis.set_title(scenario_id); axis.set_ylim(0, 1); axis.grid(axis="y", color="#e4e8eb"); axis.legend(frameon=False)
    axes[0].set_ylabel("Probabilité agrégée corrigée")
    fig.suptitle("Agrégats KRT corrigés draw-wise — panel commun de 3 000 communes", color=INK)
    fig.tight_layout(); _save(fig, "aggregate_drawwise_corrected_3000_v1", figure_path)

    contrasts = artifacts["contrasts"].sort_values(["scenario_id", "year"]).reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    for idx, row in contrasts.iterrows():
        ax.errorbar(row.estimate, idx, xerr=[[row.estimate-row.lower], [row.upper-row.estimate]], fmt="o", color=BLUE if row.scenario_id == "H0A" else GOLD, capsize=3)
    ax.axvline(0, color=INK, ls="--"); ax.set_yticks(range(len(contrasts)), contrasts.scenario_id + " — " + contrasts.year.astype(str)); ax.set_xlabel("Contraste β₁ − β₂")
    ax.set_title("Contrastes intra-période"); ax.grid(axis="x", color="#e4e8eb"); fig.tight_layout(); _save(fig, "within_period_contrasts_3000_v1", figure_path)

    diagnostic = artifacts["diagnostics"]
    colors = diagnostic.mcmc_status.map({"pass": BLUE, "caveat": GOLD, "fail": RED}).fillna(RED)
    fig, ax = plt.subplots(figsize=(8, 4.5)); ax.scatter(diagnostic.max_rhat, diagnostic.min_ess_bulk, c=colors, s=65, edgecolor=INK, lw=.4)
    for row in diagnostic.itertuples(): ax.annotate(f"{row.scenario_id}-{row.year}", (row.max_rhat, row.min_ess_bulk), xytext=(3, 3), textcoords="offset points", fontsize=8)
    ax.axvline(1.01, color=INK, ls="--"); ax.axhline(400, color=INK, ls=":"); ax.set_xlabel("R-hat maximal parmi les β communaux"); ax.set_ylabel("ESS bulk minimal parmi les β communaux")
    for status, label, color in (
        ("pass", "satisfaisant", BLUE),
        ("caveat", "satisfaisant avec réserve", GOLD),
        ("fail", "insuffisant", RED),
    ):
        if diagnostic.mcmc_status.eq(status).any():
            ax.scatter([], [], color=color, edgecolor=INK, lw=.4, s=55, label=label)
    ax.legend(frameon=False, title="Statut de synthèse")
    ax.set_title("Diagnostics des β et réserves de synthèse"); ax.grid(color="#e4e8eb"); fig.tight_layout(); _save(fig, "canonical_diagnostics_3000_v1", figure_path)

    estimands = (
        artifacts["estimands"]
        .loc[lambda frame: frame.estimand.eq("beta_1_minus_beta_2")]
        .sort_values(["scenario_id", "year"])
        .reset_index(drop=True)
    )
    labels = estimands.scenario_id + " — " + estimands.year.astype(str)
    positions = np.arange(len(estimands))
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.8), sharey=True)
    axes[0].scatter(estimands.rhat, positions, color=BLUE, edgecolor=INK, linewidth=.5, s=55, zorder=3)
    axes[0].axvline(1.01, color=INK, linestyle="--", linewidth=1, label="seuil pass = 1,01")
    axes[0].set_xlabel("R-hat du contraste")
    axes[0].set_yticks(positions, labels)
    axes[0].legend(frameon=False, fontsize=8, loc="lower right")
    axes[1].scatter(estimands.ess_bulk, positions, color=BLUE, edgecolor=INK, linewidth=.5, s=55, label="ESS bulk", zorder=3)
    axes[1].scatter(estimands.ess_tail, positions, facecolor="white", edgecolor=GOLD, linewidth=1.2, marker="s", s=48, label="ESS tail", zorder=3)
    axes[1].axvline(400, color=INK, linestyle="--", linewidth=1, label="seuil pass = 400")
    axes[1].set_xlabel("Taille effective du contraste")
    axes[1].legend(frameon=False, fontsize=8, loc="lower right")
    for axis in axes:
        axis.grid(axis="x", color="#e4e8eb")
        axis.set_axisbelow(True)
        axis.spines[["top", "right"]].set_visible(False)
    axes[0].invert_yaxis()
    fig.suptitle("Diagnostics MCMC des contrastes agrégés", color=INK)
    fig.text(.5, .015, "Panel commun de 3 000 communes · 4 chaînes × 1 000 tirages", ha="center", fontsize=9, color="#52606D")
    fig.tight_layout(rect=(0, .05, 1, .95))
    _save(fig, "estimand_diagnostics_3000_v1", figure_path)


def _markdown_table(frame: pd.DataFrame, columns: Iterable[str]) -> str:
    show = frame.loc[:, list(columns)].copy()
    for column in show.select_dtypes(include="number"):
        if column in {"year", "earlier_year", "later_year", "divergences"}:
            show[column] = show[column].map(lambda x: f"{int(x)}" if pd.notna(x) else "")
        else:
            show[column] = show[column].map(lambda x: f"{x:.3f}" if pd.notna(x) else "")
    lines = ["| " + " | ".join(show.columns) + " |", "| " + " | ".join("---" for _ in show.columns) + " |"]
    lines.extend("| " + " | ".join(map(str, row)) + " |" for row in show.itertuples(index=False, name=None))
    return "\n".join(lines)


def write_sampling_note(progress_path: Path = PROGRESS_PATH, path: Path = SAMPLING_PATH) -> Path:
    del progress_path  # Le document détaillé est maintenu séparément et audité.
    if not path.exists():
        raise FileNotFoundError(f"documentation détaillée de l'échantillonnage absente: {path}")
    text = path.read_text(encoding="utf-8")
    required_phrases = (
        "tirage aléatoire sans remise",
        "33 922",
        "20260802",
        "0,01939",
        "biais de stabilité ou de survivance",
    )
    missing = [phrase for phrase in required_phrases if phrase not in text]
    if missing:
        raise ValueError(f"documentation d'échantillonnage incomplète: {missing}")
    return path


def write_report(artifacts: Mapping[str, pd.DataFrame], report_path: Path = REPORT_PATH) -> Path:
    diagnostics = artifacts["diagnostics"]
    contrasts = artifacts["contrasts"].copy()
    changes = artifacts["changes"]
    estimands = artifacts["estimands"].loc[
        artifacts["estimands"]["estimand"].eq("beta_1_minus_beta_2")
    ].copy()
    contrasts["positive_draws"] = (
        (contrasts["probability_gt_zero"] * contrasts["n_posterior_draws"]).round().astype(int).astype(str)
        + " / "
        + contrasts["n_posterior_draws"].astype(int).astype(str)
    )
    status_counts = diagnostics["mcmc_status"].value_counts()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(f"""# Résultats consolidés sur 3 000 communes — H0A et H1

## Périmètre

La production comprend six ajustements KRT : H0A et H1 pour 1962, 1986 et 2022. Ils utilisent le même panel de 3 000 communes. Les réglages sont fixes : 4 chaînes, 1 000 itérations de chauffe, 1 000 tirages par chaîne, `target_accept=0,99` et `max_treedepth=14`.

Le bilan conservateur compte **{int(status_counts.get('pass', 0))} ajustements satisfaisants**, **{int(status_counts.get('caveat', 0))} satisfaisants avec réserve** et **{int(status_counts.get('fail', 0))} insuffisant**. Les valeurs chiffrées présentées sont les pires parmi les β communaux ; une réserve est ajoutée si les quatre hyperparamètres sont moins bien échantillonnés. Les six ajustements ont zéro divergence et zéro saturation de profondeur d'arbre.

## Définition des deux hypothèses

- **H0A** oppose les ouvriers et employés aux autres groupes sociaux et modélise leur probabilité d'abstention parmi les inscrits ;
- **H1** utilise la même partition sociale et modélise la probabilité de vote à gauche parmi les suffrages exprimés.

`β₁` désigne la probabilité latente des ouvriers et employés ; `β₂` celle du groupe complémentaire.

## Résultats agrégés

Les agrégats sont calculés à chaque tirage avec les effectifs propres aux deux groupes : `Σ N1ᵢβ1ᵢ / ΣN1ᵢ` et `Σ N2ᵢβ2ᵢ / ΣN2ᵢ`. Le contraste est `β₁−β₂`.

{_markdown_table(contrasts.sort_values(['scenario_id', 'year']), ['scenario_id', 'year', 'estimate', 'lower', 'upper', 'positive_draws'])}

Les changements entre dates utilisent 50 000 paires de tirages indépendants, avec la graine `{CHANGE_SEED}`. Les intervalles sont des intervalles postérieurs de comparaison sous indépendance des ajustements.

{_markdown_table(changes.sort_values(['scenario_id', 'earlier_year']), ['scenario_id', 'earlier_year', 'later_year', 'estimate', 'lower', 'upper'])}

![Agrégats corrigés](../figures/v2/priority_3000_final/aggregate_drawwise_corrected_3000_v1.png)

![Contrastes intra-période](../figures/v2/priority_3000_final/within_period_contrasts_3000_v1.png)

## Diagnostics MCMC des β communaux

Le diagnostic publié retient le R-hat le plus élevé et les ESS les plus faibles parmi les 6 000 paramètres communaux `b_1` et `b_2`. Les divergences, le BFMI et la profondeur d'arbre restent contrôlés sur le sampler. Si les quatre hyperparamètres ont un R-hat ou un ESS moins favorable, le statut devient `satisfaisant avec réserve`, sans remplacer les métriques β affichées.

{_markdown_table(diagnostics.sort_values(['scenario_id', 'year']), ['scenario_id', 'year', 'mcmc_assessment_label', 'beta_diagnostic_status', 'non_beta_parameter_status', 'identification_status', 'max_rhat', 'min_ess_bulk', 'min_ess_tail', 'min_bfmi', 'divergences'])}

![Diagnostics des β communaux](../figures/v2/priority_3000_final/canonical_diagnostics_3000_v1.png)

Les diagnostics des estimands portent sur les deux agrégats et leur contraste. Ils complètent le diagnostic des paramètres β communaux.

{_markdown_table(estimands.sort_values(['scenario_id', 'year']), ['scenario_id', 'year', 'estimand_mcmc_status', 'rhat', 'ess_bulk', 'ess_tail', 'mcse_mean'])}

![Diagnostics des contrastes agrégés](../figures/v2/priority_3000_final/estimand_diagnostics_3000_v1.png)

## Identification écologique

L'identification est évaluée séparément à partir des bornes de tomographie et de la variation de composition. H0A–1986 est `pass` ; les cinq autres ajustements sont `caveat`. Une bonne convergence MCMC ne suffit donc pas à identifier précisément des comportements individuels.

## Densités jointes

`joint_latent_3000_v1.csv` contient 18 000 lignes. Les densités utilisent un lissage commun aux trois dates à l'intérieur de chaque hypothèse.

### Communes équipondérées

![Densité jointe H0A — communes équipondérées](../figures/v2/priority_3000_final/densities/joint_beta_H0A_common_bandwidth_equal_communes.png)

![Densité jointe H1 — communes équipondérées](../figures/v2/priority_3000_final/densities/joint_beta_H1_common_bandwidth_equal_communes.png)

### Pondération par la taille communale

![Densité jointe H0A — pondération N total](../figures/v2/priority_3000_final/densities/joint_beta_H0A_common_bandwidth_N_total_weighted.png)

![Densité jointe H1 — pondération N total](../figures/v2/priority_3000_final/densities/joint_beta_H1_common_bandwidth_N_total_weighted.png)

### Densités marginales comparées

![Densités marginales H0A](../figures/v2/priority_3000_final/densities/marginal_beta_H0A_group_population_weighted.png)

![Densités marginales H1](../figures/v2/priority_3000_final/densities/marginal_beta_H1_group_population_weighted.png)

## Échantillonnage, portée et limites

Le panel provient d'un tirage sans remise dans 33 922 communes admissibles aux trois dates. La graine `20260802` est acceptée au premier essai après contrôle d'équilibre sur des variables 2022.

Les résultats sont conditionnels au panel, aux marges reconstruites et aux priors KRT. Ils ne propagent pas l'incertitude entre panels alternatifs. Les ajustements sont séparés par date : ils ne décrivent ni les mêmes électeurs suivis dans le temps, ni des transferts individuels.

## Prochaines vérifications

Les contrôles restant à faire sont les posterior predictive checks, la sensibilité aux priors et à `king_lambda`, puis la répétition sur plusieurs panels équilibrés.

La méthode de sélection et le contrat du panel sont détaillés dans `METHODE_ECHANTILLONNAGE_PANEL_3000.md`.

Le résumé autonome est dans `RESUME_TRAVAIL_ET_ANALYSES_3000.md`, le contrôle visuel des densités dans `COMPARAISON_DENSITES_JOINTES_3_PERIODES.md` et les choix méthodologiques sensibles dans `METHODOLOGIE_ET_CHOIX_SENSIBLES_3000.md`.

Le rapport tout-en-un destiné au professeur est `RESUME_GENERAL_PROFESSEUR_3000.md`.
""", encoding="utf-8")
    return report_path


def validate_documentation(paths: Mapping[str, Path]) -> dict[str, int]:
    """Ensure that the reader-facing Markdown matches the generated release."""

    required_docs = (
        PROJECT_GUIDE_PATH,
        REPORT_PATH,
        SAMPLING_PATH,
        WORK_SUMMARY_PATH,
        DENSITY_REVIEW_PATH,
        METHODOLOGY_PATH,
        PROFESSOR_REPORT_PATH,
        DOCS_DIR / "README.md",
        OUTPUT_PATH / "README.md",
        FIGURE_PATH / "README.md",
    )
    missing_docs = [str(path) for path in required_docs if not path.exists()]
    if missing_docs:
        raise FileNotFoundError(f"documentation canonique absente: {missing_docs}")

    expected_rows = {
        "aggregates": 12,
        "contrasts": 6,
        "changes": 6,
        "diagnostics": 6,
        "estimands": 18,
        "identification": 6,
        "joint_latent": 18_000,
    }
    observed_rows = {key: len(pd.read_csv(paths[key])) for key in expected_rows}
    if observed_rows != expected_rows:
        raise AssertionError(f"documentation impossible à valider: comptages={observed_rows}")

    guide = PROJECT_GUIDE_PATH.read_text(encoding="utf-8")
    output_readme = (OUTPUT_PATH / "README.md").read_text(encoding="utf-8")
    for path in paths.values():
        if path.name not in guide or path.name not in output_readme:
            raise AssertionError(f"output final non documenté: {path.name}")
    for phrase in ("2 satisfaisants", "4 satisfaisants avec réserve", "0 insuffisant", "33 922", "18 000", "79 tests"):
        if phrase not in guide:
            raise AssertionError(f"guide général incomplet: {phrase!r}")

    expected_png = {
        "aggregate_drawwise_corrected_3000_v1.png",
        "within_period_contrasts_3000_v1.png",
        "canonical_diagnostics_3000_v1.png",
        "estimand_diagnostics_3000_v1.png",
        "joint_beta_H0A_common_bandwidth_equal_communes.png",
        "joint_beta_H0A_common_bandwidth_N_total_weighted.png",
        "joint_beta_H1_common_bandwidth_equal_communes.png",
        "joint_beta_H1_common_bandwidth_N_total_weighted.png",
        "marginal_beta_H0A_group_population_weighted.png",
        "marginal_beta_H1_group_population_weighted.png",
    }
    observed_png = {path.name for path in FIGURE_PATH.rglob("*.png")}
    observed_svg = {path.with_suffix(".png").name for path in FIGURE_PATH.rglob("*.svg")}
    if observed_png != expected_png or observed_svg != expected_png:
        raise AssertionError("le catalogue Markdown ne correspond pas aux dix figures PNG/SVG attendues")
    figure_readme = (FIGURE_PATH / "README.md").read_text(encoding="utf-8")
    if any(Path(name).stem not in figure_readme for name in expected_png):
        raise AssertionError("au moins une figure finale n'est pas documentée dans son README")

    report = REPORT_PATH.read_text(encoding="utf-8")
    image_targets = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", report)
    unresolved = [target for target in image_targets if not (REPORT_PATH.parent / target).resolve().exists()]
    if len(image_targets) != 10 or unresolved:
        raise AssertionError(f"liens d'images du rapport invalides: n={len(image_targets)}, absents={unresolved}")
    professor_report = PROFESSOR_REPORT_PATH.read_text(encoding="utf-8")
    professor_images = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", professor_report)
    professor_unresolved = [
        target for target in professor_images
        if not (PROFESSOR_REPORT_PATH.parent / target).resolve().exists()
    ]
    if len(professor_images) != 10 or professor_unresolved:
        raise AssertionError(
            f"liens d'images du rapport professeur invalides: n={len(professor_images)}, absents={professor_unresolved}"
        )
    required_professor_phrases = (
        "production intermédiaire consolidée",
        "tirages où β₁−β₂>0",
        "intervalle postérieur de comparaison sous indépendance des ajustements",
        "estimand_mcmc_diagnostics_3000_v1.csv",
        "Dans l’archive complète, chaque run conserve sa trace NetCDF",
    )
    missing_phrases = [phrase for phrase in required_professor_phrases if phrase not in professor_report]
    if missing_phrases:
        raise AssertionError(f"rapport professeur incomplet: {missing_phrases}")
    return {
        **observed_rows,
        "figures_png": len(observed_png),
        "report_images": len(image_targets),
        "professor_report_images": len(professor_images),
    }


def build_release_zip(paths: Mapping[str, Path], *, zip_path: Path = ZIP_PATH, sha_path: Path = SHA_PATH) -> tuple[Path, Path]:
    """Write an explicit whitelist archive; legacy diagnostic mirrors cannot leak in."""

    files = [
        REPORT_PATH,
        SAMPLING_PATH,
        PROJECT_GUIDE_PATH,
        WORK_SUMMARY_PATH,
        DENSITY_REVIEW_PATH,
        METHODOLOGY_PATH,
        PROFESSOR_REPORT_PATH,
        DOCS_DIR / "README.md",
        ROOT / "code_longitudinal" / "README.md",
        ROOT / "panel" / "README.md",
        OUTPUT_PATH / "README.md",
        PANEL_PATH,
        PANEL_MANIFEST_PATH,
        PANEL_BALANCE_PATH,
        PANEL_ATTEMPTS_PATH,
        *paths.values(),
        OUTPUT_PATH / "release_manifest_3000_v1.json",
        OUTPUT_PATH / "density_bandwidths_3000_v1.csv",
    ]
    files.extend(sorted(FIGURE_PATH.rglob("*")))
    files.extend([Path(__file__).resolve(), ROOT / "code_longitudinal" / "postprocess_aggregates_v2.py", ROOT / "code_longitudinal" / "density_figures_v2.py", ROOT / "code_longitudinal" / "identification_v2.py"])
    diagnostics = pd.read_csv(paths["diagnostics"])
    for run_id in diagnostics["run_id"].astype(str):
        run_dir = RUNS_DIR / run_id
        files.extend(
            run_dir / name
            for name in (
                "manifest.json",
                "mcmc_diagnostics_v2.json",
                "mcmc_variable_metrics_v2.csv",
                "mcmc_block_metrics_v2.csv",
                "aggregate_comparison_v2.csv",
                "longitudinal_estimates.csv",
                "commune_latent_summaries.parquet",
                "trace.nc",
            )
        )
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        files.extend(
            Path(source_path)
            for source_path in manifest.get("input_sha256", {})
            if Path(source_path).suffix.lower() == ".parquet"
        )
    files = [path for path in dict.fromkeys(files) if path.exists() and path.is_file()]
    forbidden = {"model_diagnostics.csv"}
    if any(path.name in forbidden or "diagnostic_audits" in path.parts for path in files):
        raise AssertionError("un diagnostic historique ou miroir a été sélectionné pour le ZIP")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(
            "README.md",
            "# Livraison 3 000 communes — H0A/H1\n\n"
            "Lire d'abord `docs/RESUME_GENERAL_PROFESSEUR_3000.md`, puis "
            "`docs/RESUME_TRAVAIL_ET_ANALYSES_3000.md`, "
            "`docs/COMPARAISON_DENSITES_JOINTES_3_PERIODES.md` et "
            "`docs/METHODOLOGIE_ET_CHOIX_SENSIBLES_3000.md`. Le guide général est "
            "`docs/README_PRODUCTION_3000_H0A_H1.md`.\n\n"
            "Les six traces NetCDF, leurs latents communaux, diagnostics canoniques, "
            "entrées modèle et empreintes SHA-256 sont inclus pour permettre la réplication.\n",
        )
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(zip_path) as archive:
        members = archive.namelist()
        if any(name.endswith("model_diagnostics.csv") or "diagnostic_audits/" in name for name in members):
            raise AssertionError("contrôle ZIP : contenu diagnostic interdit")
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    sha_path.write_text(f"{digest}  {zip_path.name}\n", encoding="ascii")
    return zip_path, sha_path


def finalize() -> dict[str, Path]:
    """Run the post-processing only after all six required fits are complete."""

    ensure_runtime_dirs()
    fits = load_completed_required_fits()
    artifacts = compute_artifacts(fits)
    validate_artifacts(artifacts)
    paths = write_artifacts(artifacts)
    plot_release_figures(artifacts)
    density_paths, _ = generate_density_figures(paths["joint_latent"], FIGURE_PATH / "densities", metadata_path=OUTPUT_PATH / "density_bandwidths_3000_v1.csv", scenarios=SCENARIOS)
    if not density_paths:
        raise AssertionError("les figures de densité n'ont pas été produites")
    write_sampling_note()
    write_report(artifacts)
    validate_documentation(paths)
    zip_path, sha_path = build_release_zip(paths)
    return {**paths, "report": REPORT_PATH, "sampling": SAMPLING_PATH, "zip": zip_path, "sha": sha_path}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-ready", action="store_true", help="Vérifie le contrat sans lire les traces ni écrire de livraison.")
    args = parser.parse_args()
    if args.check_ready:
        fits = load_completed_required_fits()
        print(f"Prêt : {len(fits)} fits H0A/H1 validés pour la finalisation.")
        return
    result = finalize()
    print(json.dumps({key: str(value) for key, value in result.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
