from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd
from reproducibility.replication_scope import get_scope

from .spec_registry import (
    ELECTIONS,
    HARMONIZATION_VERSION,
    SCENARIOS as SCENARIO_SPECS,
    SPEC_VERSION,
    scenario_is_allowed,
)


ROOT = Path(__file__).resolve().parents[1]
FULL = ROOT / "work" / "longitudinal_2000_v1_full_240_professeur_candidate"
LIGHT = ROOT / "work" / "longitudinal_2000_release_professeur_candidate"
TECH = ROOT / "work" / "longitudinal_2000_release_technique_candidate"
REPORT_BUILD = ROOT / "work" / "professor_report_build"

CANON = FULL / "01_DONNEES_CANONIQUES"
TRANSPARENT = FULL / "02_BASE_TRANSPARENTE"
TABLES = LIGHT / "02_TABLES_PRINCIPALES"
FIGURES = LIGHT / "03_FIGURES"
PANEL_DIR = LIGHT / "04_PANEL_ET_HARMONISATION"
DIAG_DIR = LIGHT / "05_DIAGNOSTICS"
DOC_DIR = LIGHT / "06_DOCUMENTATION"

KRT_AGG = CANON / "01_PYTHON_NUMPYRO" / "krt_aggregate_240.parquet"
KRT_COMMUNE = CANON / "01_PYTHON_NUMPYRO" / "krt_commune_240.parquet"
R_AGG = CANON / "02_R_EI_EIPACK" / "king_ei_aggregate_240.parquet"
R_COMMUNE = CANON / "02_R_EI_EIPACK" / "king_ei_commune_240.parquet"
R_AUDIT = CANON / "02_R_EI_EIPACK" / "run_audit_240.csv"
NLS = CANON / "04_NLS" / "longitudinal_nls.parquet"
NLS_COV_ROOT = ROOT / "outputs" / "longitudinal_2000_v1" / "nls_covariates_fast"
NLS_COV = NLS_COV_ROOT / "longitudinal_nls_covariates.parquet"
NLS_COV_COEFFICIENTS = NLS_COV_ROOT / "longitudinal_nls_covariate_coefficients.parquet"
NLS_COV_DIAGNOSTICS = NLS_COV_ROOT / "nls_covariate_diagnostics.csv"
PANEL = CANON / "05_PANEL" / "panel_2000.parquet"
PANEL_BALANCE = ROOT / "panel" / "longitudinal_2000_v1_balance.parquet"
PANEL_BALANCE_BY_ELECTION = ROOT / "panel" / "longitudinal_2000_v1_balance_by_election.parquet"
DEPARTMENT54_EVIDENCE = (
    ROOT
    / "work"
    / "longitudinal_2000_v1.0.2_H0A_H1_validated"
    / "03_panel_et_audit"
    / "department54_pre1988_rows.csv"
)
SCENARIOS = FULL / "05_METHODE_ET_LIMITES" / "DEFINITIONS_HYPOTHESES.csv"
COMPARISON = TRANSPARENT / "comparaison_python_r.parquet"
KRT_SELECTION = CANON / "01_PYTHON_NUMPYRO" / "selection_240.csv"
KRT_RUNS = ROOT / "outputs" / "runs"

BLUE = "#2457A7"
ORANGE = "#D97706"
GOLD = "#B78B20"
INK = "#20242A"
GRID = "#D8DDE5"
GREY = "#8A929D"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_reset(path: Path, expected_name: str) -> None:
    resolved = path.resolve()
    if resolved.parent != (ROOT / "work").resolve() or resolved.name != expected_name:
        raise ValueError(f"refusing to reset unexpected path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".md":
        text = scope_text(text) if path.name != "CHANGELOG.md" else text
        if not get_scope().is_full:
            text = scope_notice() + "\n\n" + text
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def scope_notice() -> str:
    scope = get_scope()
    return (
        f"Périmètre `{scope.name}` : {scope.pair_count} couples KRT/R et {len(scope.nls_pairs)} couples NLS ; "
        f"scrutins : {', '.join(sorted(scope.election_ids))}. "
        "Production par la chaîne ordinaire, restreinte à ces couples. Ce document ne certifie pas "
        "la reproduction complète de la série historique ; les scrutins hors périmètre ne sont pas estimés."
    )


def scope_text(text: str) -> str:
    """Adapt coverage prose only; never rewrite paths, scientific thresholds or data."""
    scope = get_scope()
    entries = scope_reference_entries()
    # The historical report classified runs with missing backend metadata as PyMC.
    # Replay uses the explicit backend in the frozen per-pair contract instead.
    for old, new in {
        "145 runs PyMC": f"{sum(e['arguments']['sampler_backend'] == 'pymc' for e in entries)} runs PyMC",
        "95 NumPyro": f"{sum(e['arguments']['sampler_backend'] == 'numpyro' for e in entries)} NumPyro",
        "145 PyMC": f"{sum(e['arguments']['sampler_backend'] == 'pymc' for e in entries)} PyMC",
    }.items():
        text = text.replace(old, new)
    if scope.is_full:
        return text
    replacements = {
        "480 000": f"{scope.pair_count * 2000:,}".replace(",", " "),
        "52 runs `canonical_v1.0.2`": f"{sum(e['reference_selection_status'] == 'canonical_v1.0.2' for e in entries)} runs `canonical_v1.0.2`",
        "188 `initial_fit_user_selected`": f"{sum(e['reference_selection_status'] == 'initial_fit_user_selected' for e in entries)} `initial_fit_user_selected`",
        "52 `canonical_v1.0.2`": f"{sum(e['reference_selection_status'] == 'canonical_v1.0.2' for e in entries)} `canonical_v1.0.2`",
        "Six runs H0A/H1": "Les runs H0A/H1 désignés dans le contrat",
        "six runs H0A/H1": "les runs H0A/H1 désignés dans le contrat",
        "toutes années 1962–2022": "dans le périmètre sélectionné",
        "pour toutes les années": "pour les années sélectionnées",
        "1962–2022": "périmètre sélectionné",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    for old, new in ((240, scope.pair_count), (480, scope.density_count), (292, len(scope.nls_pairs)), (960, scope.pair_count * 4)):
        text = re.sub(rf"(?<![\w]){old}(?![\w])", str(new), text)
    return text


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def enrich_commune_metadata(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    """Preserve the preparation schema of the selected historical run.

    Initial H0A/H1 fits predate the extended covariate-provenance columns.
    The six targeted reruns used the extended schema, as recorded by their
    historical panel_id in the frozen replay contract. A current preparation
    regenerates more metadata, but filling those historical omissions would
    silently change the delivered table. This export-only projection does not
    modify model-ready data, vote margins, weights or posterior estimates.

    Do not replace genuinely missing metadata by the string "unknown" or
    borrow another scenario's values. The complete current preparation remains
    available in the run evidence; only historical public-column availability
    is reproduced here. No reference result values are loaded.
    """

    result = frame.copy()
    metadata_columns = [
        "vbbm",
        "vbbm_reference_year",
        "vbbm_status",
        "vbbm_source_column",
        "revenue_ratio",
        "revenue_reference_year",
        "revenue_status",
        "revenue_source_column",
        "capital_ratio",
        "capital_reference_year",
        "capital_status",
        "capital_source_column",
        "foreign_share",
        "foreign_share_reference_year",
        "foreign_share_status",
        "foreign_share_source_column",
        "commune_name_canonical",
        "geography_version",
        "commune_name_reference_year",
    ]
    before = {column: int(result[column].isna().sum()) for column in metadata_columns}
    late_columns = [
        "vbbm_reference_year", "vbbm_status", "vbbm_source_column",
        "revenue_reference_year", "revenue_status", "revenue_source_column",
        "capital_reference_year", "capital_status", "capital_source_column",
        "foreign_share", "foreign_share_reference_year", "foreign_share_status", "foreign_share_source_column",
    ]
    contract_path = Path(__file__).resolve().parents[1] / "reproducibility/contract_v2/krt_replay_240.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    canonical = {
        (str(row["election_id"]), str(row["scenario_id"])): row["historical_hash_payload"]["parameters"]
        for row in contract["entries"] if row["scenario_id"] in {"H0A", "H1"}
    }
    initial_pairs = {
        pair for pair, parameters in canonical.items()
        if parameters["panel_id"] != "v101_targeted_rerun_current_primary_2000"
    }
    pairs = pd.MultiIndex.from_frame(result[["election_id", "scenario_id"]].astype("string"))
    canonical_mask = result["scenario_id"].isin(["H0A", "H1"])
    unknown_pairs = set(pairs[canonical_mask]) - set(canonical)
    if unknown_pairs:
        raise AssertionError(f"unknown canonical metadata schema: {sorted(unknown_pairs)}")
    initial_mask = pairs.isin(initial_pairs)
    for column in late_columns:
        result.loc[initial_mask, column] = np.nan if pd.api.types.is_numeric_dtype(result[column]) else pd.NA
    unresolved = result[["vbbm", "revenue_ratio", "capital_ratio", "foreign_share"]].isna().any(axis=1)
    result["metadata_join_status"] = np.where(initial_mask, "historical_initial_schema_preserved", "source_value")
    after = {column: int(result[column].isna().sum()) for column in metadata_columns}
    audit = {
        "schema_version": "commune_historical_metadata_projection_v2",
        "rule": "preserve initial-versus-targeted preparation schema recorded by the frozen replay contract",
        "contract_path": "reproducibility/contract_v2/krt_replay_240.json",
        "contract_sha256": sha256(contract_path),
        "initial_schema_pairs": [list(pair) for pair in sorted(initial_pairs)],
        "columns_absent_in_initial_schema": late_columns,
        "rows_with_initial_schema": int(initial_mask.sum()),
        "estimates_recomputed": False,
        "before_nulls": before,
        "after_nulls": after,
        "rows_filled": 0,
        "rows_with_unknown_remaining": int(unresolved.sum()),
    }
    return result, audit


def election_family(series: pd.Series) -> pd.Series:
    return np.where(series.str.startswith("leg_"), "legislative", "presidential")


def r_aggregate_election_family(series: pd.Series) -> pd.Series:
    """Keep this table's historical vocabulary, distinct from plotting labels."""
    return np.where(series.str.startswith("leg_"), "legislative", "presidentielle")


def configure_plotting() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.titlesize": 14,
            "axes.labelsize": 10,
            "axes.edgecolor": INK,
            "axes.labelcolor": INK,
            "xtick.color": INK,
            "ytick.color": INK,
            "text.color": INK,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.7,
            "grid.alpha": 0.75,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )


def save_figure(fig: plt.Figure, directory: Path, stem: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    fig.savefig(directory / f"{stem}.png", dpi=180, bbox_inches="tight", facecolor="white")
    fig.savefig(directory / f"{stem}.svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def scope_reference_entries() -> list[dict[str, object]]:
    """Select frozen reference expectations, never infer acceptance from a rerun."""
    entries = json.loads((ROOT / "reproducibility" / "contract_v2" / "krt_replay_240.json").read_text(encoding="utf-8"))["entries"]
    selected = [entry for entry in entries if (entry["election_id"], entry["scenario_id"]) in get_scope().pairs]
    if len(selected) != get_scope().pair_count:
        raise AssertionError("incomplete frozen replay expectations for replication scope")
    return selected


def assert_pair_scope(frame: pd.DataFrame, *, nls: bool = False) -> None:
    expected = get_scope().nls_pairs if nls else get_scope().pairs
    actual = set(map(tuple, frame[["election_id", "scenario_id"]].astype(str).values))
    if actual != expected:
        raise AssertionError(f"unexpected table pair scope: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}")


def read_r_manifests(expected_pairs: int | None = None) -> pd.DataFrame:
    expected_pairs = get_scope().pair_count if expected_pairs is None else expected_pairs
    rows: list[dict[str, object]] = []
    manifest_root = ROOT / "outputs" / "longitudinal_2000_v1" / "r_replication" / "king_ei_runs"
    for path in sorted(manifest_root.glob("*__H*/manifest_r.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("status") != "success":
            continue
        rows.append(
            {
                "election_id": payload["election_id"],
                "scenario_id": payload["scenario_id"],
                "r_version": payload.get("r_version"),
                "ei_version": payload.get("ei_version"),
                "eiPack_version": payload.get("eiPack_version"),
                "seed": payload.get("seed"),
                "native_importance_draws": payload.get("native_importance_draws"),
                "hessian_condition_number": payload.get("hessian_condition_number"),
                "elapsed_seconds": payload.get("elapsed_seconds"),
                "source_manifest": f"outputs/longitudinal_2000_v1/r_replication/king_ei_runs/{path.parent.name}/manifest_r.json",
            }
        )
    frame = pd.DataFrame(rows)
    if len(frame) != expected_pairs or frame[["election_id", "scenario_id"]].duplicated().any():
        raise AssertionError(f"expected {expected_pairs} unique R manifests, got {len(frame)}")
    assert_pair_scope(frame)
    return frame


def _contrast_three_methods_from_frames(
    krt_agg: pd.DataFrame,
    r_agg: pd.DataFrame,
    nls: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "election_id", "year", "round", "scenario_id", "model_key",
        "estimand", "estimate", "q025", "q975", "diagnostic_status",
        "election_family",
    ]
    krt = krt_agg.loc[krt_agg["estimand"].eq("b_1_minus_b_2")].copy()
    krt_rows = pd.DataFrame(
        {
            "election_id": krt["election_id"],
            "year": krt["year"],
            "round": krt["round"],
            "scenario_id": krt["scenario_id"],
            "model_key": krt["model_key"],
            "estimand": krt["estimand"],
            "estimate": krt["mean"],
            "q025": krt["q025"],
            "q975": krt["q975"],
            "diagnostic_status": krt["mcmc_status"],
            "election_family": election_family(krt["election_id"]),
        }
    )
    r = r_agg.loc[r_agg["estimand"].isin(["contrast_aggregate", "b_1_minus_b_2"])].copy()
    if r.duplicated(["election_id", "scenario_id", "model_key"]).any():
        raise AssertionError("duplicate native/normalized R contrast for the same pair")
    r_rows = pd.DataFrame(
        {
            "election_id": r["election_id"],
            "year": r["year"],
            "round": r["round"],
            "scenario_id": r["scenario_id"],
            "model_key": r["model_key"],
            "estimand": "b_1_minus_b_2",
            "estimate": r["mean"],
            "q025": r["q025"],
            "q975": r["q975"],
            "diagnostic_status": "native_ei_importance_resampling",
            "election_family": election_family(r["election_id"]),
        }
    )
    nls = nls.loc[
        nls["estimand_type"].eq("group_contrast")
        & nls["scenario_id"].isin(["H0A", "H0B", "H0C", "H1", "H2", "H3", "H4", "H5", "H6", "H7"])
    ].copy()
    nls_rows = pd.DataFrame(
        {
            "election_id": nls["election_id"],
            "year": nls["year"],
            "round": nls["round"],
            "scenario_id": nls["scenario_id"],
            "model_key": "rosen_nls_2x2_unadjusted",
            "estimand": "b_1_minus_b_2",
            "estimate": nls["estimate"],
            "q025": np.nan,
            "q975": np.nan,
            "diagnostic_status": nls["diagnostic_status"],
            "election_family": election_family(nls["election_id"]),
        }
    )
    return pd.concat(
        [r_rows.reindex(columns=columns), krt_rows.reindex(columns=columns), nls_rows.reindex(columns=columns)],
        ignore_index=True,
    )


def build_main_tables(expected_pairs: int | None = None) -> dict[str, int]:
    expected_pairs = get_scope().pair_count if expected_pairs is None else expected_pairs
    TABLES.mkdir(parents=True, exist_ok=True)
    krt_agg = pd.read_parquet(KRT_AGG)
    krt_commune_raw = pd.read_parquet(KRT_COMMUNE)
    krt_commune, metadata_audit = enrich_commune_metadata(krt_commune_raw)
    r_agg = pd.read_parquet(R_AGG)
    r_commune = pd.read_parquet(R_COMMUNE)
    nls = pd.read_parquet(NLS)
    for frame in (krt_agg, krt_commune, r_agg, r_commune):
        assert_pair_scope(frame)
    assert_pair_scope(nls, nls=True)
    r_manifests = read_r_manifests(expected_pairs)

    if len(krt_agg) != expected_pairs * 3 or len(krt_commune) != expected_pairs * 2_000:
        raise AssertionError("invalid KRT row counts")
    if len(r_agg) != expected_pairs * 3 or len(r_commune) != expected_pairs * 2_000:
        raise AssertionError("invalid R EI row counts")

    krt_commune = krt_commune.drop(columns=["metadata_join_status"], errors="ignore")
    krt_agg.to_parquet(TABLES / "longitudinal_krt_aggregate.parquet", index=False, compression="zstd")
    krt_commune.to_parquet(TABLES / "longitudinal_krt_commune.parquet", index=False, compression="zstd")
    write_json(DOC_DIR / "METADATA_ENRICHMENT_AUDIT.json", metadata_audit)
    nls.to_parquet(TABLES / "longitudinal_nls.parquet", index=False, compression="zstd")
    if not NLS_COV.is_file() or not NLS_COV_COEFFICIENTS.is_file():
        raise FileNotFoundError("NLS covariate sensitivity outputs are incomplete")
    nls_cov = pd.read_parquet(NLS_COV)
    nls_cov_coefficients = pd.read_parquet(NLS_COV_COEFFICIENTS)
    if len(nls_cov) != expected_pairs * 4 * 3:
        raise AssertionError(
            f"expected {expected_pairs * 4 * 3:,} NLS covariate estimate rows, got {len(nls_cov)}"
        )
    nls_cov.to_parquet(TABLES / "longitudinal_nls_covariates.parquet", index=False, compression="zstd")
    nls_cov_coefficients.to_parquet(
        TABLES / "longitudinal_nls_covariate_coefficients.parquet", index=False, compression="zstd"
    )

    geo_columns = [
        "panel_id",
        "election_id",
        "scenario_id",
        "unit_id",
        "department",
        "region13",
        "vbbm",
        "vbbm_reference_year",
        "vbbm_status",
        "vbbm_source_column",
        "revenue_ratio",
        "revenue_reference_year",
        "revenue_status",
        "revenue_source_column",
        "capital_ratio",
        "capital_reference_year",
        "capital_status",
        "capital_source_column",
        "foreign_share",
        "foreign_share_reference_year",
        "foreign_share_status",
        "foreign_share_source_column",
        "N_g",
        "b1_weight",
        "b2_weight",
        "commune_name_canonical",
        "geography_version",
        "commune_name_reference_year",
    ]
    geo = krt_commune[geo_columns].drop_duplicates(
        ["panel_id", "election_id", "scenario_id", "unit_id"]
    )
    r_commune_enriched = r_commune.merge(
        geo,
        on=["panel_id", "election_id", "scenario_id", "unit_id"],
        how="left",
        validate="one_to_one",
    ).merge(r_manifests, on=["election_id", "scenario_id"], how="left", validate="many_to_one")
    r_commune_enriched["model_key"] = "king_ei_1997_r"
    r_commune_enriched["numerical_status"] = "valid_native_ei_importance_resampling"
    r_commune_enriched["identification_status"] = "not_directly_comparable_to_krt_diagnostic"
    r_commune_enriched["provenance_table"] = "02_TABLES_PRINCIPALES/longitudinal_r_ei_commune.parquet"
    if r_commune_enriched[["department", "region13", "seed", "r_version"]].isna().any().any():
        raise AssertionError("R commune enrichment left required values missing")
    r_commune_enriched.to_parquet(
        TABLES / "longitudinal_r_ei_commune.parquet", index=False, compression="zstd"
    )

    election_meta = krt_agg[
        [
            "panel_id",
            "election_id",
            "year",
            "round",
            "scenario_id",
            "n_communes",
            "weight_total",
        ]
    ].drop_duplicates(["panel_id", "election_id", "scenario_id"])
    r_aggregate_enriched = r_agg.merge(
        election_meta,
        on=["panel_id", "election_id", "scenario_id"],
        how="left",
        validate="many_to_one",
    ).merge(r_manifests, on=["election_id", "scenario_id"], how="left", validate="many_to_one")
    # This historical R table uses a French label, while the cross-method
    # contrast table intentionally uses the English plotting vocabulary.
    r_aggregate_enriched["election_family"] = r_aggregate_election_family(r_aggregate_enriched["election_id"])
    r_aggregate_enriched["numerical_status"] = "valid_native_ei_importance_resampling"
    r_aggregate_enriched["identification_status"] = "not_directly_comparable_to_krt_diagnostic"
    r_aggregate_enriched["provenance_table"] = "02_TABLES_PRINCIPALES/longitudinal_r_ei_aggregate.parquet"
    r_aggregate_enriched.to_parquet(
        TABLES / "longitudinal_r_ei_aggregate.parquet", index=False, compression="zstd"
    )
    contract_columns = {
        "longitudinal_krt_commune.parquet": [
            "panel_id", "election_id", "year", "round", "scenario_id", "run_id", "model_key",
            "spec_version", "harmonization_version", "unit_id", "department", "region13", "vbbm",
            "vbbm_reference_year", "vbbm_status", "vbbm_source_column", "revenue_ratio",
            "revenue_reference_year", "revenue_status", "revenue_source_column", "capital_ratio",
            "capital_reference_year", "capital_status", "capital_source_column", "foreign_share",
            "foreign_share_reference_year", "foreign_share_status", "foreign_share_source_column",
            "N_g", "b1_weight", "b2_weight", "b1_mean", "b1_sd", "b1_q025", "b1_q50",
            "b1_q975", "b2_mean", "b2_sd", "b2_q025", "b2_q50", "b2_q975", "mcmc_status",
            "identification_status", "commune_name_canonical", "geography_version",
            "commune_name_reference_year", "public_schema_version", "source_panel_id",
            "selection_status", "run_key", "sample_id", "sample_rank",
        ],
        "longitudinal_r_ei_commune.parquet": [
            "panel_id", "election_id", "scenario_id", "unit_id", "sample_rank", "b1_mean", "b2_mean",
            "b1_sd", "b2_sd", "b1_q025", "b2_q025", "b1_q50", "b2_q50", "b1_q975", "b2_q975",
            "department", "region13", "vbbm", "vbbm_reference_year", "vbbm_status", "vbbm_source_column",
            "revenue_ratio", "revenue_reference_year", "revenue_status", "revenue_source_column",
            "capital_ratio", "capital_reference_year", "capital_status", "capital_source_column",
            "foreign_share", "foreign_share_reference_year", "foreign_share_status",
            "foreign_share_source_column", "N_g", "b1_weight", "b2_weight", "commune_name_canonical",
            "geography_version", "commune_name_reference_year", "r_version", "ei_version", "eiPack_version",
            "seed", "native_importance_draws", "hessian_condition_number", "elapsed_seconds",
            "source_manifest", "model_key", "numerical_status", "identification_status", "provenance_table",
        ],
    }
    krt_commune = krt_commune.reindex(columns=contract_columns["longitudinal_krt_commune.parquet"])
    krt_commune.to_parquet(TABLES / "longitudinal_krt_commune.parquet", index=False, compression="zstd")
    r_commune_enriched = r_commune_enriched.reindex(
        columns=contract_columns["longitudinal_r_ei_commune.parquet"]
    )
    r_commune_enriched.to_parquet(
        TABLES / "longitudinal_r_ei_commune.parquet", index=False, compression="zstd"
    )
    contrasts_three_methods = _contrast_three_methods_from_frames(krt_agg, r_aggregate_enriched, nls)
    contrasts_three_methods.to_parquet(
        TABLES / "longitudinal_contrasts_krt_r_nls.parquet", index=False, compression="zstd"
    )

    return {
        "longitudinal_krt_commune.parquet": len(krt_commune),
        "longitudinal_krt_aggregate.parquet": len(krt_agg),
        "longitudinal_nls.parquet": len(nls),
        "longitudinal_nls_covariates.parquet": len(nls_cov),
        "longitudinal_nls_covariate_coefficients.parquet": len(nls_cov_coefficients),
        "longitudinal_r_ei_commune.parquet": len(r_commune_enriched),
        "longitudinal_r_ei_aggregate.parquet": len(r_aggregate_enriched),
        "longitudinal_contrasts_krt_r_nls.parquet": len(contrasts_three_methods),
    }


def build_panel_and_harmonisation() -> None:
    PANEL_DIR.mkdir(parents=True, exist_ok=True)
    panel = pd.read_parquet(PANEL)
    primary = panel.loc[panel["included_primary_2000"].astype(bool)].copy()
    if len(primary) != 2000:
        raise AssertionError(f"expected panel 2000, got {len(primary)}")
    primary.to_csv(PANEL_DIR / "panel_2000.csv", index=False, encoding="utf-8-sig")

    numeric = ["log1p_inscrits", "vbbm", "share_ouvr", "share_empl", "share_cadr", "share_agri_indp"]
    rows: list[dict[str, object]] = []
    for column in numeric:
        universe = panel[column].astype(float)
        sample = primary[column].astype(float)
        denom = universe.std(ddof=1)
        rows.append(
            {
                "check_type": "continuous",
                "variable": column,
                "panel_n": int(sample.notna().sum()),
                "reference_n": int(universe.notna().sum()),
                "panel_mean": sample.mean(),
                "reference_mean": universe.mean(),
                "reference_sd": denom,
                "standardized_mean_difference": (sample.mean() - universe.mean()) / denom if denom else np.nan,
                "status": "descriptive_pass" if abs((sample.mean() - universe.mean()) / denom) <= 0.10 else "review",
            }
        )
    for column in ["region13", "department"]:
        panel_share = primary[column].value_counts(normalize=True, dropna=False)
        ref_share = panel[column].value_counts(normalize=True, dropna=False)
        max_gap = float((panel_share - ref_share).abs().fillna(0).max())
        rows.append(
            {
                "check_type": "categorical",
                "variable": column,
                "panel_n": len(primary),
                "reference_n": len(panel),
                "panel_mean": np.nan,
                "reference_mean": np.nan,
                "reference_sd": np.nan,
                "standardized_mean_difference": max_gap,
                "status": "descriptive_pass" if max_gap <= 0.02 else "review",
            }
        )
    pd.DataFrame(rows).to_csv(PANEL_DIR / "balance_checks_summary.csv", index=False, encoding="utf-8-sig")

    scenarios = pd.read_csv(SCENARIOS)
    scenarios = scenarios.loc[scenarios["scenario_id"].isin(get_scope().scenario_ids)].copy()
    scenarios["interpretation_rule"] = "association_ecologique_non_causale"
    scenarios["availability_rule"] = np.where(
        scenarios["scenario_id"].isin(["H6", "H7"]), "scrutins_a_partir_de_1986", "tous_scrutins_admissibles"
    )
    scenarios.to_csv(PANEL_DIR / "HARMONISATION_POLITIQUE.csv", index=False, encoding="utf-8-sig")

    krt = pd.read_parquet(KRT_AGG)[["election_id", "year", "round", "scenario_id"]].drop_duplicates()
    r_ei = pd.read_parquet(R_AGG)[["election_id", "scenario_id"]].drop_duplicates()
    nls = pd.read_parquet(NLS)[["election_id", "scenario_id", "diagnostic_status"]].drop_duplicates()
    coverage = (
        krt.groupby(["election_id", "year", "round"], as_index=False)
        .agg(expected_scenarios=("scenario_id", "nunique"), python_krt_successes=("scenario_id", "nunique"))
    )
    coverage = coverage.merge(
        r_ei.groupby("election_id", as_index=False).agg(r_ei_successes=("scenario_id", "nunique")),
        on="election_id",
        how="left",
    ).merge(
        nls.groupby("election_id", as_index=False).agg(
            nls_scenarios=("scenario_id", "nunique"),
            nls_passes=("diagnostic_status", lambda s: int((s == "pass").sum())),
        ),
        on="election_id",
        how="left",
    )
    coverage["election_family"] = r_aggregate_election_family(coverage["election_id"])
    coverage["python_complete"] = coverage["python_krt_successes"].eq(coverage["expected_scenarios"])
    coverage["r_complete"] = coverage["r_ei_successes"].eq(coverage["expected_scenarios"])
    coverage.to_csv(PANEL_DIR / "coverage_by_election.csv", index=False, encoding="utf-8-sig")


def krt_status_summary(krt: pd.DataFrame) -> pd.DataFrame:
    """The production status matrix, also used for isolated reference rendering."""
    krt_diag = krt.drop_duplicates(["election_id", "scenario_id"])
    by_scenario = (
        krt_diag.groupby(["scenario_id", "mcmc_status"], as_index=False).size()
        .pivot(index="scenario_id", columns="mcmc_status", values="size")
        .fillna(0)
        .astype(int)
        .reindex(columns=["pass", "caveat", "fail"], fill_value=0)
        .reset_index()
    )
    by_scenario["total"] = by_scenario[["pass", "caveat", "fail"]].sum(axis=1)
    reference_entries = scope_reference_entries()
    expected = {
        scenario: tuple(sum(entry["scenario_id"] == scenario and entry["reference_mcmc_status"] == status for entry in reference_entries) for status in ("pass", "caveat", "fail"))
        for scenario in sorted(get_scope().scenario_ids)
    }
    observed = {
        row.scenario_id: (int(row.pass_), int(row.caveat), int(row.fail))
        for row in by_scenario.rename(columns={"pass": "pass_"}).itertuples(index=False)
    }
    if observed != expected:
        raise AssertionError(f"unexpected KRT status matrix: {observed}")
    return by_scenario


def build_diagnostics() -> None:
    DIAG_DIR.mkdir(parents=True, exist_ok=True)
    krt = pd.read_parquet(KRT_AGG)
    krt_diag = krt[
        [
            "election_id",
            "year",
            "round",
            "scenario_id",
            "run_id",
            "draws",
            "tune",
            "chains",
            "target_accept",
            "max_treedepth",
            "mcmc_status",
            "identification_status",
            "selection_status",
        ]
    ].drop_duplicates(["election_id", "scenario_id"])
    krt_diag.to_csv(DIAG_DIR / "diagnostics_KRT_resume.csv", index=False, encoding="utf-8-sig")
    by_scenario = krt_status_summary(krt_diag)
    reference_entries = scope_reference_entries()
    by_scenario.to_csv(DIAG_DIR / "diagnostics_KRT_par_hypothese.csv", index=False, encoding="utf-8-sig")

    selection = pd.read_csv(KRT_SELECTION)
    run_rows: list[dict[str, object]] = []
    for selected in selection.itertuples(index=False):
        manifest_path = KRT_RUNS / str(selected.run_id) / "manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        parameters = payload.get("parameters", {})
        command = str(payload.get("command", "")).lower()
        backend = str(parameters.get("sampler_backend") or payload.get("sampler_backend") or "").lower()
        if not backend:
            # Older H0A/H1 manifests omit the sampler field. Their saved traces
            # identify the inference library; absence is not evidence of PyMC.
            from netCDF4 import Dataset
            trace_path = manifest_path.parent / "trace.nc"
            if not trace_path.is_file():
                raise AssertionError(f"missing sampler provenance and trace: {manifest_path}")
            with Dataset(trace_path, "r") as trace:
                posterior = trace.groups.get("posterior")
                if posterior is None or "inference_library" not in posterior.ncattrs():
                    raise AssertionError(f"trace lacks sampler provenance: {trace_path}")
                backend = str(posterior.getncattr("inference_library")).lower()
        if backend not in {"numpyro", "pymc"}:
            raise AssertionError(f"unrecognized sampler provenance {backend}: {manifest_path}")
        backend = "NumPyro" if "numpyro" in backend else "PyMC"
        run_rows.append(
            {
                "election_id": selected.election_id,
                "scenario_id": selected.scenario_id,
                "run_id": selected.run_id,
                "selection_status": selected.selection_status,
                "mcmc_status": selected.mcmc_status,
                "identification_status": selected.identification_status,
                "backend": backend,
                "draws": parameters.get("draws", payload.get("draws")),
                "tune": parameters.get("tune", payload.get("tune")),
                "chains": parameters.get("chains", payload.get("chains")),
                "target_accept": parameters.get("target_accept", payload.get("target_accept")),
                "max_treedepth": parameters.get("max_treedepth", payload.get("max_treedepth")),
            }
        )
    runs = pd.DataFrame(run_rows)
    expected_backends = Counter("NumPyro" if "numpyro" in entry["arguments"]["sampler_backend"].lower() else "PyMC" for entry in reference_entries)
    if runs["backend"].value_counts().to_dict() != dict(expected_backends):
        raise AssertionError(f"unexpected backend counts: {runs['backend'].value_counts().to_dict()}")
    if runs["selection_status"].value_counts().to_dict() != dict(Counter(entry["reference_selection_status"] for entry in reference_entries)):
        raise AssertionError("unexpected selection status counts")
    run_diagnostics = pd.DataFrame(run_rows)
    run_diagnostics.to_csv(DIAG_DIR / "diagnostics_KRT_runs.csv", index=False, encoding="utf-8-sig")

    nls = pd.read_parquet(NLS)
    nls_diag = (
        nls.groupby(["election_id", "year", "round", "scenario_id"], as_index=False)
        .agg(
            objective=("objective", "max"),
            optimality=("optimality", "max"),
            bread_rank_min=("bread_rank", "min"),
            bread_condition_max=("bread_condition", "max"),
            n_starts_min=("n_starts", "min"),
            n_successful_starts_min=("n_successful_starts", "min"),
            max_abs_solution_difference=("max_abs_solution_difference", "max"),
            boundary_estimate_any=("boundary_estimate", "max"),
            fit_status=("fit_status", lambda s: ";".join(sorted(set(map(str, s))))),
            diagnostic_status=("diagnostic_status", lambda s: "fail" if (s == "fail").any() else "pass"),
        )
    )
    nls_diag.to_csv(DIAG_DIR / "diagnostics_NLS_resume.csv", index=False, encoding="utf-8-sig")
    nls_cov_diag = pd.read_csv(NLS_COV_DIAGNOSTICS)
    if len(nls_cov_diag) != get_scope().pair_count * 4:
        raise AssertionError(f"expected {get_scope().pair_count * 4} NLS covariate diagnostics, got {len(nls_cov_diag)}")
    nls_cov_diag.to_csv(
        DIAG_DIR / "diagnostics_NLS_covariables_resume.csv", index=False, encoding="utf-8-sig"
    )

    r_diag = read_r_manifests()
    r_diag["status"] = "valid"
    r_diag.to_csv(DIAG_DIR / "diagnostics_R_EI_resume.csv", index=False, encoding="utf-8-sig")

    identification = krt_diag[
        ["election_id", "year", "round", "scenario_id", "mcmc_status", "identification_status"]
    ].merge(
        nls_diag[["election_id", "scenario_id", "diagnostic_status", "bread_condition_max"]],
        on=["election_id", "scenario_id"],
        how="left",
        suffixes=("_krt", "_nls"),
    )
    identification["r_ei_identification_status"] = "not_directly_comparable_to_krt_diagnostic"
    identification.to_csv(DIAG_DIR / "identification_resume.csv", index=False, encoding="utf-8-sig")

    coverage = pd.read_csv(PANEL_DIR / "coverage_by_election.csv")
    matrix = coverage[
        [
            "election_id",
            "year",
            "round",
            "election_family",
            "expected_scenarios",
            "python_krt_successes",
            "r_ei_successes",
            "nls_scenarios",
            "nls_passes",
        ]
    ]
    matrix.to_csv(DIAG_DIR / "matrice_couverture_modeles.csv", index=False, encoding="utf-8-sig")


def contrast_three_methods() -> pd.DataFrame:
    data = pd.read_parquet(TRANSPARENT / "base_resultats_long.parquet")
    data = data.loc[data["estimand"].eq("b_1_minus_b_2")].copy()
    nls = pd.read_parquet(NLS)
    nls = nls.loc[nls["estimand_type"].eq("group_contrast")].copy()
    nls_rows = pd.DataFrame(
        {
            "election_id": nls["election_id"],
            "year": nls["year"],
            "round": nls["round"],
            "scenario_id": nls["scenario_id"],
            "model_key": "rosen_nls_2x2_unadjusted",
            "estimand": "b_1_minus_b_2",
            "estimate": nls["estimate"],
            "q025": np.nan,
            "q975": np.nan,
            "diagnostic_status": nls["diagnostic_status"],
            "election_family": np.where(
                nls["election_id"].str.startswith("leg_"), "legislative", "presidential"
            ),
        }
    )
    columns = [
        "election_id",
        "year",
        "round",
        "scenario_id",
        "model_key",
        "estimand",
        "estimate",
        "q025",
        "q975",
        "diagnostic_status",
        "election_family",
    ]
    return pd.concat([data.reindex(columns=columns), nls_rows], ignore_index=True)


def normalized_status(values: pd.Series) -> pd.Series:
    status = values.fillna("pass").astype(str).str.lower()
    return np.select(
        [status.eq("fail"), status.isin(["caveat", "warning", "review"])],
        ["fail", "caveat"],
        default="pass",
    )


def plot_status_series(
    ax: plt.Axes,
    subset: pd.DataFrame,
    *,
    color: str,
    marker: str,
    linestyle: str,
    label: str,
    linewidth: float = 2.0,
) -> None:
    subset = subset.sort_values("year").copy()
    if subset.empty:
        return
    subset["plot_status"] = normalized_status(subset["diagnostic_status"])
    valid_line = subset["estimate"].where(~subset["plot_status"].eq("fail"))
    ax.plot(subset["year"], valid_line, color=color, ls=linestyle, lw=linewidth, label=label)
    passed = subset["plot_status"].eq("pass")
    caveat = subset["plot_status"].eq("caveat")
    failed = subset["plot_status"].eq("fail")
    ax.scatter(subset.loc[passed, "year"], subset.loc[passed, "estimate"], s=34, marker=marker, color=color, zorder=3)
    ax.scatter(
        subset.loc[caveat, "year"], subset.loc[caveat, "estimate"], s=42, marker=marker,
        facecolors="white", edgecolors=color, linewidths=1.4, zorder=3,
    )
    ax.scatter(subset.loc[failed, "year"], subset.loc[failed, "estimate"], s=42, marker="x", color=GREY, linewidths=1.5, zorder=3)
    interval = ~failed & subset["q025"].notna() & subset["q975"].notna()
    if interval.any():
        ax.fill_between(
            subset.loc[interval, "year"].astype(float),
            subset.loc[interval, "q025"].astype(float),
            subset.loc[interval, "q975"].astype(float),
            color=color, alpha=0.08,
        )


def add_status_legend(ax: plt.Axes) -> None:
    handles = [
        Line2D([], [], marker="o", linestyle="None", color=INK, label="pass"),
        Line2D([], [], marker="o", linestyle="None", markerfacecolor="white", markeredgecolor=INK, label="caveat / warning"),
        Line2D([], [], marker="x", linestyle="None", color=GREY, label="fail (ligne interrompue)"),
    ]
    method_handles, method_labels = ax.get_legend_handles_labels()
    ax.legend(method_handles + handles, method_labels + [h.get_label() for h in handles], frameon=False, ncol=3, fontsize=8, loc="best")


def plot_trajectory(scenario: str, family: str, target_dir: Path, data: pd.DataFrame) -> None:
    data = data.loc[
        data["scenario_id"].eq(scenario) & data["election_family"].eq(family)
    ].sort_values(["model_key", "year"])
    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    if not get_scope().is_full and data.empty:
        ax.text(0.5, 0.5, "Hors périmètre : aucun couple estimé", ha="center", transform=ax.transAxes)
    for model, color, marker, linestyle, label in [
        ("krt_beta_binomial", BLUE, "o", "-", "KRT bêta-binomial (Python)"),
        ("king_ei_1997_r", ORANGE, "s", "-", "King EI normale tronquée (R)"),
        ("rosen_nls_2x2_unadjusted", GOLD, "^", "--", "NLS non ajusté"),
    ]:
        subset = data.loc[data["model_key"].eq(model)]
        ax.plot(
            subset["year"], subset["estimate"], color=color, marker=marker, ls=linestyle,
            lw=2.1, ms=5, label=label,
        )
        if model != "rosen_nls_2x2_unadjusted":
            ax.fill_between(subset["year"], subset["q025"], subset["q975"], color=color, alpha=0.09)
    ax.axhline(0, color=INK, lw=1.0)
    label_family = "législatives" if family == "legislative" else "présidentielles"
    ax.set_title(f"Trajectoire {scenario} — {label_family}", loc="left", fontweight="bold", pad=28)
    ax.text(
        0,
        1.01,
        "Contraste agrégé β₁−β₂ ; bandes = intervalles KRT/R à 95 %, NLS ponctuel. Association écologique.",
        transform=ax.transAxes,
        fontsize=9,
        color="#4B5563",
    )
    ax.set_xlabel("Année")
    ax.set_ylabel("Contraste β₁−β₂")
    ax.legend(frameon=False, ncol=3, loc="upper left")
    fig.tight_layout()
    save_figure(fig, target_dir, f"{scenario}_{family}")


def build_figures() -> None:
    configure_plotting()
    all_contrasts = contrast_three_methods()
    scenarios_all = ["H0A", "H0B", "H0C", "H1", "H2", "H3", "H4", "H5", "H6", "H7"]
    for scenario in scenarios_all:
        for family in ["legislative", "presidential"]:
            target = FIGURES / f"trajectoire_{scenario}" if scenario in {"H0A", "H1"} else (
                FIGURES / "trajectoires_KRT_R_NLS_toutes_hypotheses" / scenario
            )
            plot_trajectory(scenario, family, target, all_contrasts)

    overview_scenarios = ["H0B", "H0C", "H2", "H3", "H4", "H5", "H6", "H7"]
    for family in ["legislative", "presidential"]:
        fig, axes = plt.subplots(4, 2, figsize=(12, 15), sharey=False)
        for ax, scenario in zip(axes.flat, overview_scenarios):
            subset = all_contrasts.loc[
                all_contrasts["scenario_id"].eq(scenario)
                & all_contrasts["election_family"].eq(family)
            ].sort_values("year")
            if not get_scope().is_full and subset.empty:
                ax.text(0.5, 0.5, "Hors périmètre", ha="center", transform=ax.transAxes)
            for model, color, marker, linestyle, label in [
                ("krt_beta_binomial", BLUE, "o", "-", "KRT"),
                ("king_ei_1997_r", ORANGE, "s", "-", "R EI"),
                ("rosen_nls_2x2_unadjusted", GOLD, "^", "--", "NLS"),
            ]:
                part = subset.loc[subset["model_key"].eq(model)]
                ax.plot(part["year"], part["estimate"], color=color, marker=marker, ls=linestyle, lw=1.55, ms=3.5, label=label)
            ax.axhline(0, color=INK, lw=0.75)
            ax.set_title(scenario, loc="left", fontweight="bold")
            ax.set_xlabel("Année")
            ax.set_ylabel("β₁−β₂")
        axes.flat[0].legend(frameon=False, ncol=3, loc="best")
        family_label = "législatives" if family == "legislative" else "présidentielles"
        fig.suptitle(
            f"Trajectoires KRT–R–NLS — autres hypothèses, {family_label}",
            x=0.08, y=0.995, ha="left", fontsize=15, fontweight="bold",
        )
        fig.text(
            0.08, 0.968,
            "Contraste agrégé β₁−β₂ ; NLS ponctuel, KRT/R avec incertitude détaillée dans les figures individuelles.",
            fontsize=9, color="#4B5563",
        )
        fig.tight_layout(rect=(0, 0, 1, 0.945))
        save_figure(
            fig,
            FIGURES / "trajectoires_NLS_autres_hypotheses",
            f"trajectoires_krt_r_nls_{family}",
        )

    nls_cov = pd.read_parquet(NLS_COV)
    nls_cov = nls_cov.loc[nls_cov["estimand"].eq("b_1_minus_b_2")].copy()
    base_nls = all_contrasts.loc[all_contrasts["model_key"].eq("rosen_nls_2x2_unadjusted")].copy()
    base_nls["spec_id"] = "base_unadjusted"
    base_nls["spec_label"] = "NLS non ajusté"
    sensitivity = pd.concat(
        [
            base_nls[["election_id", "year", "scenario_id", "election_family", "spec_id", "spec_label", "estimate"]],
            nls_cov[["election_id", "year", "scenario_id", "election_family", "spec_id", "spec_label", "estimate"]],
        ],
        ignore_index=True,
    )
    palette = {
        "base_unadjusted": INK,
        "territorial_vbbm": BLUE,
        "socioeconomic_revenue_capital": ORANGE,
        "demographic_foreign_share": GOLD,
        "joint_parsimonious": "#B24C7C",
    }
    markers = {"base_unadjusted": "o", "territorial_vbbm": "s", "socioeconomic_revenue_capital": "^", "demographic_foreign_share": "D", "joint_parsimonious": "P"}
    for family in ["legislative", "presidential"]:
        fig, axes = plt.subplots(5, 2, figsize=(12, 18), sharey=False)
        for ax, scenario in zip(axes.flat, scenarios_all):
            part = sensitivity.loc[
                sensitivity["scenario_id"].eq(scenario) & sensitivity["election_family"].eq(family)
            ]
            if not get_scope().is_full and part.empty:
                ax.text(0.5, 0.5, "Hors périmètre", ha="center", transform=ax.transAxes)
            for spec_id, label in [
                ("base_unadjusted", "Base"),
                ("territorial_vbbm", "VBBM"),
                ("socioeconomic_revenue_capital", "Revenu + capital"),
                ("demographic_foreign_share", "Étrangers"),
                ("joint_parsimonious", "Jointe"),
            ]:
                sub = part.loc[part["spec_id"].eq(spec_id)].sort_values("year")
                ax.plot(sub["year"], sub["estimate"], color=palette[spec_id], marker=markers[spec_id], lw=1.25, ms=3, label=label)
            ax.axhline(0, color="#6B7280", lw=0.7)
            ax.set_title(scenario, loc="left", fontweight="bold")
            ax.set_xlabel("Année")
            ax.set_ylabel("Contraste NLS")
        axes.flat[0].legend(frameon=False, ncol=2, fontsize=8, loc="best")
        family_label = "législatives" if family == "legislative" else "présidentielles"
        fig.suptitle(
            f"Sensibilité NLS aux covariables — {family_label}",
            x=0.08, y=0.995, ha="left", fontsize=15, fontweight="bold",
        )
        fig.text(
            0.08, 0.972,
            "Spécifications descriptives écologiques ; les avertissements de rang/conditionnement restent attachés aux tables.",
            fontsize=9, color="#4B5563",
        )
        fig.tight_layout(rect=(0, 0, 1, 0.95))
        save_figure(fig, FIGURES / "sensibilite_NLS_covariables", f"sensibilite_nls_{family}")

    krt = pd.read_parquet(KRT_AGG)
    krt = krt.loc[krt["estimand"].eq("b_1_minus_b_2"), ["election_id", "scenario_id", "year", "mean"]]
    nls_contrast = nls = pd.read_parquet(NLS)
    nls_contrast = nls_contrast.loc[nls_contrast["estimand_type"].eq("group_contrast")]
    comparison = krt.merge(
        nls_contrast[["election_id", "scenario_id", "estimate", "diagnostic_status"]],
        on=["election_id", "scenario_id"],
        how="inner",
        validate="one_to_one",
    )
    comparison["family"] = r_aggregate_election_family(comparison["election_id"])
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.3), sharex=True, sharey=True)
    for ax, family, label in zip(axes, ["legislative", "presidentielle"], ["Législatives", "Présidentielles"]):
        part = comparison.loc[comparison["family"].eq(family)]
        if not get_scope().is_full and part.empty:
            ax.text(0.5, 0.5, "Hors périmètre", ha="center", transform=ax.transAxes)
            ax.set_title(label, loc="left", fontweight="bold")
            ax.set_xlabel("Contraste NLS")
            ax.set_ylabel("Contraste KRT")
            continue
        ax.scatter(part["estimate"], part["mean"], c=np.where(part["diagnostic_status"].eq("pass"), BLUE, GOLD), s=28, alpha=0.78, edgecolor="white", linewidth=0.4)
        low = float(min(part["estimate"].min(), part["mean"].min()))
        high = float(max(part["estimate"].max(), part["mean"].max()))
        ax.plot([low, high], [low, high], color=INK, ls="--", lw=1)
        ax.set_title(label, loc="left", fontweight="bold")
        ax.set_xlabel("Contraste NLS")
        ax.set_ylabel("Contraste KRT")
    fig.suptitle("Comparaison KRT–NLS", x=0.07, y=0.995, ha="left", fontsize=15, fontweight="bold")
    fig.text(0.07, 0.945, "Une ligne par élection × hypothèse ; diagonale = égalité. Or = diagnostic NLS à revoir.", fontsize=9, color="#4B5563")
    fig.tight_layout(rect=(0, 0, 1, 0.90))
    save_figure(fig, FIGURES / "comparaison_KRT_NLS", "comparaison_krt_nls")

    commune = pd.read_parquet(KRT_COMMUNE)
    commune = commune.loc[
        commune["year"].eq(2022) & commune["scenario_id"].isin(["H0A", "H1"])
    ]
    fig, axes = plt.subplots(2, 2, figsize=(11, 9.5), sharex=True, sharey=True)
    panels = [
        ("leg_2022_r1", "H0A", "Législatives — H0A"),
        ("pre_2022_r1", "H0A", "Présidentielles — H0A"),
        ("leg_2022_r1", "H1", "Législatives — H1"),
        ("pre_2022_r1", "H1", "Présidentielles — H1"),
    ]
    for ax, (election_id, scenario, title) in zip(axes.flat, panels):
        part = commune.loc[
            commune["election_id"].eq(election_id) & commune["scenario_id"].eq(scenario)
        ]
        if not get_scope().is_full and part.empty:
            ax.text(0.5, 0.5, "Hors périmètre : aucun couple estimé", ha="center", transform=ax.transAxes)
            ax.set_title(title, loc="left", fontweight="bold")
            ax.set_xlabel("β₁ communal — moyenne postérieure")
            ax.set_ylabel("β₂ communal — moyenne postérieure")
            continue
        hb = ax.hexbin(part["b1_mean"], part["b2_mean"], gridsize=34, cmap="Blues", mincnt=1)
        ax.plot([0, 1], [0, 1], color=ORANGE, ls="--", lw=1)
        ax.set_title(title, loc="left", fontweight="bold")
        ax.set_xlabel("β₁ communal — moyenne postérieure")
        ax.set_ylabel("β₂ communal — moyenne postérieure")
        fig.colorbar(hb, ax=ax, label="Communes par hexagone")
    fig.suptitle("Distributions communales bidimensionnelles — 2022", x=0.07, y=0.995, ha="left", fontsize=15, fontweight="bold")
    fig.text(0.07, 0.955, "Chaque commune compte une fois ; la diagonale indique β₁=β₂.", fontsize=9, color="#4B5563")
    fig.tight_layout(rect=(0, 0, 1, 0.925))
    save_figure(fig, FIGURES / "distributions_2D_2022", "distributions_2d_2022")


def report_statistics() -> dict[str, object]:
    base = pd.read_parquet(TRANSPARENT / "base_resultats_long.parquet")
    contrast = base.loc[base["estimand"].eq("b_1_minus_b_2")].copy()
    krt = contrast.loc[contrast["model_key"].eq("krt_beta_binomial")]
    current = krt.loc[
        krt["year"].eq(2022) & krt["scenario_id"].isin(["H0A", "H1"]),
        ["election_id", "scenario_id", "estimate", "q025", "q975", "diagnostic_status", "identification_status"],
    ].sort_values(["scenario_id", "election_id"])
    comparison = pd.read_parquet(COMPARISON)
    comparison = comparison.loc[comparison["estimand"].eq("b_1_minus_b_2")].copy()
    model_gap = comparison.groupby("scenario_id")["absolute_difference"].median().sort_values(ascending=False)
    krt_pairs = pd.read_parquet(KRT_AGG)[
        ["election_id", "scenario_id", "mcmc_status", "identification_status"]
    ].drop_duplicates()
    nls_pairs = pd.read_parquet(NLS)[
        ["election_id", "scenario_id", "diagnostic_status"]
    ].drop_duplicates()
    nls_cov_pairs = pd.read_parquet(NLS_COV)[
        ["election_id", "scenario_id", "spec_id", "diagnostic_status"]
    ].drop_duplicates()
    return {
        "current": current.to_dict(orient="records"),
        "model_gap": model_gap.to_dict(),
        "krt_mcmc": krt_pairs["mcmc_status"].value_counts().to_dict(),
        "krt_identification": krt_pairs["identification_status"].value_counts().to_dict(),
        "nls_diagnostics": nls_pairs["diagnostic_status"].value_counts().to_dict(),
        "nls_covariate_diagnostics": nls_cov_pairs["diagnostic_status"].value_counts().to_dict(),
        "interval_overlap": comparison["intervals_overlap"].value_counts().to_dict(),
    }


def build_report_artifact() -> Path:
    REPORT_BUILD.mkdir(parents=True, exist_ok=True)
    contrasts = contrast_three_methods()
    contrasts["series"] = contrasts["model_key"].map(
        {
            "krt_beta_binomial": "KRT — Python",
            "king_ei_1997_r": "King EI — R",
            "rosen_nls_2x2_unadjusted": "NLS non ajusté",
        }
    ) + " / " + contrasts["election_family"].map(
        {"legislative": "législatives", "presidential": "présidentielles"}
    )
    contrasts["estimate_pct"] = 100 * contrasts["estimate"]

    nls = pd.read_parquet(NLS)
    nls_contrast = nls.loc[nls["estimand_type"].eq("group_contrast")].copy()
    nls_contrast["election_family"] = r_aggregate_election_family(nls_contrast["election_id"])
    nls_contrast["estimate_pct"] = 100 * nls_contrast["estimate"]
    nls_contrast["series"] = nls_contrast["scenario_id"] + " / " + nls_contrast["election_family"]

    krt_contrast = pd.read_parquet(KRT_AGG)
    krt_contrast = krt_contrast.loc[krt_contrast["estimand"].eq("b_1_minus_b_2")]
    krt_nls = krt_contrast[["election_id", "scenario_id", "year", "mean"]].merge(
        nls_contrast[["election_id", "scenario_id", "estimate", "diagnostic_status"]],
        on=["election_id", "scenario_id"],
        validate="one_to_one",
    )
    krt_nls["krt_pct"] = 100 * krt_nls["mean"]
    krt_nls["nls_pct"] = 100 * krt_nls["estimate"]
    krt_nls["election_family"] = r_aggregate_election_family(krt_nls["election_id"])

    py_r = pd.read_parquet(COMPARISON)
    py_r = py_r.loc[py_r["estimand"].eq("b_1_minus_b_2")].copy()
    gaps = (
        py_r.groupby("scenario_id", as_index=False)["absolute_difference"]
        .median()
        .rename(columns={"absolute_difference": "median_absolute_gap"})
        .sort_values("median_absolute_gap", ascending=False)
    )
    gaps["median_absolute_gap_pct"] = 100 * gaps["median_absolute_gap"]

    krt_pairs = pd.read_parquet(KRT_AGG)[
        ["election_id", "scenario_id", "mcmc_status", "identification_status"]
    ].drop_duplicates()
    diagnostics = (
        krt_pairs.groupby("mcmc_status", as_index=False).size().rename(columns={"size": "pairs"})
    )
    stats = report_statistics()

    def records(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, object]]:
        clean = frame[columns].replace({np.nan: None})
        return clean.to_dict(orient="records")

    h0a = contrasts.loc[contrasts["scenario_id"].eq("H0A")]
    h1 = contrasts.loc[contrasts["scenario_id"].eq("H1")]
    other_scenarios = ["H0B", "H0C", "H2", "H3", "H4", "H5", "H6", "H7"]
    other_frames = {scenario: contrasts.loc[contrasts["scenario_id"].eq(scenario)].copy() for scenario in other_scenarios}
    nls_cov = pd.read_parquet(NLS_COV)
    nls_cov = nls_cov.loc[nls_cov["estimand"].eq("b_1_minus_b_2")].copy()
    base_lookup = nls_contrast[["election_id", "scenario_id", "estimate"]].rename(
        columns={"estimate": "base_estimate"}
    )
    nls_cov = nls_cov.merge(base_lookup, on=["election_id", "scenario_id"], validate="many_to_one")
    nls_cov["absolute_shift"] = (nls_cov["estimate"] - nls_cov["base_estimate"]).abs()
    cov_summary = (
        nls_cov.groupby(["spec_id", "spec_label"], as_index=False)
        .agg(
            median_absolute_shift=("absolute_shift", "median"),
            p90_absolute_shift=("absolute_shift", lambda s: float(s.quantile(0.90))),
            pass_pairs=("diagnostic_status", lambda s: int((s == "pass").sum())),
            warning_pairs=("diagnostic_status", lambda s: int((s == "warning").sum())),
            fail_pairs=("diagnostic_status", lambda s: int((s == "fail").sum())),
        )
    )
    cov_summary["median_absolute_shift_pct"] = 100 * cov_summary["median_absolute_shift"]
    cov_summary["p90_absolute_shift_pct"] = 100 * cov_summary["p90_absolute_shift"]
    current = pd.DataFrame(stats["current"])
    current["estimate_pct"] = 100 * current["estimate"]
    current["q025_pct"] = 100 * current["q025"]
    current["q975_pct"] = 100 * current["q975"]

    sources = [
        {
            "id": "krt_aggregate",
            "label": "Table KRT agrégée",
            "path": "02_TABLES_PRINCIPALES/longitudinal_krt_aggregate.parquet",
        },
        {
            "id": "r_aggregate",
            "label": "Table R EI agrégée",
            "path": "02_TABLES_PRINCIPALES/longitudinal_r_ei_aggregate.parquet",
        },
        {
            "id": "nls_table",
            "label": "Table NLS",
            "path": "02_TABLES_PRINCIPALES/longitudinal_nls.parquet",
        },
        {
            "id": "nls_cov_table",
            "label": "Sensibilités NLS avec covariables",
            "path": "02_TABLES_PRINCIPALES/longitudinal_nls_covariates.parquet",
        },
        {
            "id": "contrast_table",
            "label": "Contrastes KRT, R EI et NLS au même grain",
            "path": "02_TABLES_PRINCIPALES/longitudinal_contrasts_krt_r_nls.parquet",
        },
    ]
    top_sources = [
        {
            **source,
            "query": {
                "engine": "duckdb",
                "language": "sql",
                "sql": f'SELECT * FROM read_parquet(\"{source["path"]}\")',
                "description": f"Lecture reproductible de {source['label']}.",
                "tables_used": [source["path"]],
                "executed_at": utc_now(),
            },
        }
        for source in sources
    ]

    cards = [
        {
            "id": "python_coverage",
            "description": "Couples élection × hypothèse disposant d'un ajustement KRT canonique initial.",
            "dataset": "summary",
            "sourceId": "krt_aggregate",
            "metrics": [{"label": "KRT canoniques", "field": "python_pairs", "format": "number"}],
        },
        {
            "id": "r_coverage",
            "description": "Couples répliqués par la normale tronquée de King via R ei/eiPack.",
            "dataset": "summary",
            "sourceId": "r_aggregate",
            "metrics": [{"label": "R EI valides", "field": "r_pairs", "format": "number"}],
        },
        {
            "id": "nls_coverage",
            "description": "Couples NLS au diagnostic numérique pass parmi les 292 admissibles.",
            "dataset": "summary",
            "sourceId": "nls_table",
            "metrics": [{"label": "NLS pass", "field": "nls_pass", "format": "number"}],
        },
        {
            "id": "mcmc_pass",
            "description": "Couples KRT dont le statut MCMC synthétique est pass; les autres restent livrés avec caveat/fail.",
            "dataset": "summary",
            "sourceId": "krt_aggregate",
            "metrics": [{"label": "MCMC pass", "field": "mcmc_pass", "format": "number"}],
        },
    ]

    charts = [
        {
            "id": "h0a_chart",
            "title": "H0A — contraste agrégé selon le scrutin",
            "subtitle": "Points de pourcentage; législatives et présidentielles restent distinguées.",
            "type": "line",
            "dataset": "h0a",
            "sourceId": "contrast_table",
            "encodings": {
                "x": {"field": "year", "type": "ordinal", "label": "Année"},
                "y": {"field": "estimate_pct", "type": "quantitative", "label": "β₁−β₂ (points)"},
                "color": {"field": "series", "type": "nominal", "label": "Modèle / scrutin"},
                "tooltip": [
                    {"field": "election_id", "type": "nominal", "label": "Élection"},
                    {"field": "diagnostic_status", "type": "nominal", "label": "Diagnostic"},
                ],
            },
        },
        {
            "id": "h1_chart",
            "title": "H1 — contraste agrégé selon le scrutin",
            "subtitle": "Points de pourcentage; association écologique, non comportement individuel observé.",
            "type": "line",
            "dataset": "h1",
            "sourceId": "contrast_table",
            "encodings": {
                "x": {"field": "year", "type": "ordinal", "label": "Année"},
                "y": {"field": "estimate_pct", "type": "quantitative", "label": "β₁−β₂ (points)"},
                "color": {"field": "series", "type": "nominal", "label": "Modèle / scrutin"},
            },
        },
        {
            "id": "cov_summary_chart",
            "title": "Sensibilité du contraste NLS aux covariables",
            "subtitle": "Écart absolu médian à la base non ajustée, 240 couples par spécification, en points.",
            "type": "bar",
            "dataset": "cov_summary",
            "sourceId": "nls_cov_table",
            "encodings": {
                "x": {"field": "spec_label", "type": "nominal", "label": "Spécification"},
                "y": {"field": "median_absolute_shift_pct", "type": "quantitative", "label": "Écart absolu médian (points)"},
                "tooltip": [
                    {"field": "p90_absolute_shift_pct", "type": "quantitative", "label": "p90 (points)"},
                    {"field": "pass_pairs", "type": "quantitative", "label": "Pass"},
                    {"field": "warning_pairs", "type": "quantitative", "label": "Warning"},
                    {"field": "fail_pairs", "type": "quantitative", "label": "Fail"},
                ],
            },
        },
        {
            "id": "krt_nls_chart",
            "title": "Accord des contrastes KRT et NLS",
            "subtitle": "240 couples au même grain; la dispersion rappelle que les objectifs et l'incertitude diffèrent.",
            "type": "scatter",
            "dataset": "krt_nls",
            "sourceId": "nls_table",
            "encodings": {
                "x": {"field": "nls_pct", "type": "quantitative", "label": "NLS (points)"},
                "y": {"field": "krt_pct", "type": "quantitative", "label": "KRT (points)"},
                "color": {"field": "election_family", "type": "nominal", "label": "Scrutin"},
                "tooltip": [
                    {"field": "election_id", "type": "nominal", "label": "Élection"},
                    {"field": "scenario_id", "type": "nominal", "label": "Hypothèse"},
                    {"field": "diagnostic_status", "type": "nominal", "label": "Diagnostic NLS"},
                ],
            },
        },
        {
            "id": "gap_chart",
            "title": "Sensibilité KRT–R EI par hypothèse",
            "subtitle": "Médiane de l'écart absolu agrégé, en points de pourcentage.",
            "type": "bar",
            "dataset": "gaps",
            "sourceId": "r_aggregate",
            "encodings": {
                "x": {"field": "scenario_id", "type": "nominal", "label": "Hypothèse"},
                "y": {"field": "median_absolute_gap_pct", "type": "quantitative", "label": "Écart absolu médian (points)"},
            },
        },
        {
            "id": "diagnostics_chart",
            "title": "Statut MCMC synthétique des 240 couples KRT",
            "subtitle": "Les succès de calcul ne valent pas tous validation diagnostique.",
            "type": "bar",
            "dataset": "diagnostics",
            "sourceId": "krt_aggregate",
            "encodings": {
                "x": {"field": "mcmc_status", "type": "nominal", "label": "Statut"},
                "y": {"field": "pairs", "type": "quantitative", "label": "Couples"},
            },
        },
    ]
    charts.extend(
        {
            "id": f"trajectory_{scenario}_chart",
            "title": f"{scenario} — contraste KRT, R EI et NLS",
            "subtitle": "β₁−β₂ en points; législatives et présidentielles sont des séries distinctes.",
            "type": "line",
            "dataset": f"trajectory_{scenario}",
            "sourceId": "contrast_table",
            "encodings": {
                "x": {"field": "year", "type": "ordinal", "label": "Année"},
                "y": {"field": "estimate_pct", "type": "quantitative", "label": "β₁−β₂ (points)"},
                "color": {"field": "series", "type": "nominal", "label": "Méthode / scrutin"},
                "tooltip": [
                    {"field": "election_id", "type": "nominal", "label": "Élection"},
                    {"field": "diagnostic_status", "type": "nominal", "label": "Diagnostic"},
                ],
            },
        }
        for scenario in other_scenarios
    )

    tables = [
        {
            "id": "current_table",
            "title": "Repères 2022 — KRT",
            "subtitle": "Contrastes agrégés H0A et H1, intervalles à 95 % et statuts.",
            "dataset": "current",
            "sourceId": "krt_aggregate",
            "defaultSort": {"field": "scenario_id", "direction": "asc"},
            "columns": [
                {"field": "election_id", "label": "Élection", "type": "text"},
                {"field": "scenario_id", "label": "Hypothèse", "type": "text"},
                {"field": "estimate_pct", "label": "Contraste (pts)", "format": "number"},
                {"field": "q025_pct", "label": "q2,5 (pts)", "format": "number"},
                {"field": "q975_pct", "label": "q97,5 (pts)", "format": "number"},
                {"field": "diagnostic_status", "label": "MCMC", "type": "text"},
                {"field": "identification_status", "label": "Identification", "type": "text"},
            ],
        }
    ]

    summary = {
        "python_pairs": get_scope().pair_count,
        "r_pairs": get_scope().pair_count,
        "nls_pass": int(stats["nls_diagnostics"].get("pass", 0)),
        "mcmc_pass": int(stats["krt_mcmc"].get("pass", 0)),
    }
    h0a_2022 = current.loc[current["scenario_id"].eq("H0A")]
    h1_2022 = current.loc[current["scenario_id"].eq("H1")]
    h0a_text = "; ".join(
        f"{row.election_id}: {row.estimate_pct:+.1f} points [{row.q025_pct:+.1f}; {row.q975_pct:+.1f}]"
        for row in h0a_2022.itertuples(index=False)
    )
    h1_text = "; ".join(
        f"{row.election_id}: {row.estimate_pct:+.1f} points [{row.q025_pct:+.1f}; {row.q975_pct:+.1f}]"
        for row in h1_2022.itertuples(index=False)
    )

    blocks = [
        {"id": "title", "type": "markdown", "body": "# Résultats longitudinaux d'inférence écologique — panel de 2 000 communes"},
        {
            "id": "results",
            "type": "markdown",
            "sourceId": "krt_aggregate",
            "body": (
                "## Résumé des résultats\n\n"
                "La couverture est complète pour les **240 couples KRT canoniques** et les **240 réplications R EI**. "
                f"En 2022, H0A vaut {h0a_text}. H1 vaut {h1_text}. "
                "La lecture principale est un déplacement temporel de contrastes écologiques, pas une observation de comportements individuels. "
                f"La sensibilité inter-modèle est la plus forte en médiane pour **{max(stats['model_gap'], key=stats['model_gap'].get)}**."
            ),
        },
        {"id": "metrics", "type": "metric-strip", "cardIds": ["python_coverage", "r_coverage", "nls_coverage", "mcmc_pass"]},
        {"id": "current", "type": "table", "tableId": "current_table"},
        {
            "id": "question",
            "type": "markdown",
            "body": (
                "## Question scientifique et lien avec Cagé–Piketty\n\n"
                "Le projet étudie comment les associations entre structure sociale communale et choix électoraux se déplacent entre 1962 et 2022. "
                "Le lien avec le programme Cagé–Piketty tient à la transformation de la composition sociale des électorats; les résultats présentés ici constituent une mesure écologique locale de ces contrastes, complémentaire aux analyses agrégées nationales."
            ),
        },
        {
            "id": "data_limits",
            "type": "markdown",
            "body": (
                "## Données et limites de l'inférence écologique\n\n"
                "Les marges électorales et sociales sont observées au niveau communal. Les β sont latents et estimés sous contraintes comptables. "
                "Ils ne prouvent ni transfert individuel, ni causalité. Le panel fixe améliore la comparabilité temporelle mais décrit des communes survivantes dans la géographie harmonisée."
            ),
        },
        {
            "id": "panel",
            "type": "markdown",
            "body": (
                "## Construction du panel de 2 000 communes\n\n"
                "Le panel correspond aux 2 000 premiers rangs de l'échantillon emboîté défini indépendamment des résultats électoraux. "
                "Les identifiants, départements, régions, VBBM et variables communales jointes sont livrés avec leur provenance; aucune commune historique absente n'est remplacée silencieusement."
            ),
        },
        {
            "id": "methods",
            "type": "markdown",
            "body": (
                "## Méthodes NLS, KRT et réplication R\n\n"
                "KRT estime des β communaux par modèle bêta-binomial NumPyro et fournit des intervalles postérieurs. NLS résout un objectif déterministe multi-départs sans intervalle validé. "
                "La réplication R utilise le modèle classique de King à normale tronquée via `ei`/`eiPack`; elle teste la robustesse, sans identité mathématique avec KRT."
            ),
        },
        {"id": "h0a", "type": "chart", "chartId": "h0a_chart"},
        {
            "id": "h0a_note",
            "type": "markdown",
            "sourceId": "contrast_table",
            "body": "## Trajectoire H0A : abstention populaire\n\nLe contraste est négatif au début de la série puis devient positif. La bascule et son amplitude diffèrent selon le type de scrutin. KRT, R EI et NLS sont maintenant tracés au même grain; l'accord de forme ne doit pas être confondu avec une identité de modèles.",
        },
        {"id": "h1", "type": "chart", "chartId": "h1_chart"},
        {
            "id": "h1_note",
            "type": "markdown",
            "sourceId": "contrast_table",
            "body": "## Trajectoire H1 : vote populaire à gauche\n\nLe contraste est positif pendant une grande partie de la période, puis se rapproche de zéro et devient négatif dans les scrutins récents. KRT, R EI et NLS apparaissent en parallèle; les législatives et présidentielles sont des séries distinctes.",
        },
        {
            "id": "h23",
            "type": "markdown",
            "sourceId": "contrast_table",
            "body": "## Toutes les autres hypothèses : comparaison KRT–R–NLS\n\nLes trajectoires ci-dessous reprennent exactement la logique de H1 pour H0B, H0C, H2, H3, H4, H5, H6 et H7 : même contraste β₁−β₂, trois méthodes en parallèle et séparation explicite des familles de scrutin. H6/H7 ne sont définies qu'à partir de 1986.",
        },
        {
            "id": "h4h67",
            "type": "markdown",
            "sourceId": "contrast_table",
            "body": "### Lecture des hypothèses sociales\n\nH2 et H3 séparent ouvriers et employés; H4 oppose agriculteurs et indépendants aux salariés sur le vote à droite; H5 porte sur le centre; H6/H7 portent sur le vote FN/RN des ouvriers et employés. Les écarts entre méthodes sont des informations de robustesse, pas des erreurs à moyenner.",
        },
        *[
            {"id": f"trajectory_{scenario}", "type": "chart", "chartId": f"trajectory_{scenario}_chart"}
            for scenario in other_scenarios
        ],
        {
            "id": "covariates_note",
            "type": "markdown",
            "sourceId": "nls_cov_table",
            "body": "## Sensibilités NLS avec covariables communales\n\nQuatre spécifications rapides complètent la base non ajustée : VBBM catégoriel; revenu et capital; part d'étrangers; puis une spécification jointe parcimonieuse. Elles gardent le même objectif NLS non pondéré et sont descriptives au niveau communal. Les rangs déficients, conditionnements élevés et divergences entre départs restent visibles; aucun coefficient n'est présenté comme causal.",
        },
        {"id": "covariates_summary", "type": "chart", "chartId": "cov_summary_chart"},
        {"id": "krt_nls", "type": "chart", "chartId": "krt_nls_chart"},
        {
            "id": "comparison_note",
            "type": "markdown",
            "body": "## Comparaison KRT–NLS\n\nLa comparaison se fait au même grain élection × hypothèse. Les deux méthodes répondent à des objectifs différents : KRT représente l'hétérogénéité communale et l'incertitude postérieure, tandis que NLS fournit une solution ponctuelle globale. L'accord de signe est informatif; une identité numérique n'est pas attendue.",
        },
        {"id": "gap", "type": "chart", "chartId": "gap_chart"},
        {
            "id": "distribution",
            "type": "markdown",
            "body": "## Distributions communales et atlas complet\n\nLes figures 2D placent les moyennes communales β₁ et β₂ au même plan et ajoutent leurs deux marginales pondérées. Les **480 graphiques** KRT/R, couvrant toutes les élections et hypothèses, sont intégrés dans [l'annexe HTML plein format](ANNEXE_ATLAS_DENSITES.html); les planches de synthèse sont dans `03_FIGURES/atlas_densites_resumes`. Les valeurs R non finies sont exclues sans imputation et leur couverture est indiquée sur chaque figure.",
        },
        {"id": "diagnostics", "type": "chart", "chartId": "diagnostics_chart"},
        {
            "id": "convergence",
            "type": "markdown",
            "sourceId": "krt_aggregate",
            "body": (
                "## Convergence, identification et cellules fragiles\n\n"
                f"Sur 240 couples KRT, {stats['krt_mcmc'].get('pass', 0)} ont un statut MCMC `pass`, "
                f"{stats['krt_mcmc'].get('caveat', 0)} `caveat` et {stats['krt_mcmc'].get('fail', 0)} `fail`. "
                f"L'identification est `pass` pour {stats['krt_identification'].get('pass', 0)}, `caveat` pour {stats['krt_identification'].get('caveat', 0)} et `fail` pour {stats['krt_identification'].get('fail', 0)} couple. "
                f"NLS passe sur {stats['nls_diagnostics'].get('pass', 0)}/292 couples admissibles. Ces statuts restent attachés aux estimations et interdisent de transformer une couverture de calcul en validation substantielle générale."
            ),
        },
        {
            "id": "extensions",
            "type": "markdown",
            "body": "## Prochaines extensions : modèle 3×2 et validation des covariables\n\nLes sensibilités NLS covariées sont désormais calculées; l'étape suivante est leur validation hors échantillon et une stratégie d'identification plus forte, puis un modèle 3×2 séparant davantage les groupes sociaux. Toute extension doit conserver le panel, les marges fermées, les graines, les diagnostics et la politique de sélection canonique.",
        },
    ]

    artifact = {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": "Résultats longitudinaux d'inférence écologique — panel de 2 000 communes",
            "description": "Rapport technique orienté résultats, 1962–2022.",
            "generatedAt": utc_now(),
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "sources": sources,
            "blocks": blocks,
        },
        "snapshot": {
            "version": 1,
            "generatedAt": utc_now(),
            "status": "ready",
            "datasets": {
                "summary": [summary],
                "h0a": records(h0a, ["election_id", "year", "election_family", "series", "estimate_pct", "diagnostic_status"]),
                "h1": records(h1, ["election_id", "year", "election_family", "series", "estimate_pct", "diagnostic_status"]),
                **{
                    f"trajectory_{scenario}": records(
                        frame,
                        ["election_id", "year", "scenario_id", "election_family", "series", "estimate_pct", "diagnostic_status"],
                    )
                    for scenario, frame in other_frames.items()
                },
                "cov_summary": records(
                    cov_summary,
                    [
                        "spec_id", "spec_label", "median_absolute_shift_pct", "p90_absolute_shift_pct",
                        "pass_pairs", "warning_pairs", "fail_pairs",
                    ],
                ),
                "krt_nls": records(krt_nls, ["election_id", "year", "scenario_id", "election_family", "krt_pct", "nls_pct", "diagnostic_status"]),
                "gaps": records(gaps, ["scenario_id", "median_absolute_gap_pct"]),
                "diagnostics": records(diagnostics, ["mcmc_status", "pairs"]),
                "current": records(current, ["election_id", "scenario_id", "estimate_pct", "q025_pct", "q975_pct", "diagnostic_status", "identification_status"]),
            },
        },
        "sources": top_sources,
        "package_info": {},
    }

    if not get_scope().is_full:
        # Preserve the historical report structure but never infer full-period
        # conclusions or complete-campaign coverage from a bounded replay.
        for collection in (cards, charts, tables, blocks):
            for item in collection:
                for field in ("title", "subtitle", "description", "body"):
                    if isinstance(item.get(field), str):
                        item[field] = scope_text(item[field])
        overrides = {
            "results": f"## Résultats du périmètre sélectionné\n\n{scope_notice()}\n\nEn 2022, H0A : {h0a_text or 'hors périmètre'}. H1 : {h1_text or 'hors périmètre'}. Les diagnostics restent distincts de la couverture des calculs.",
            "h0a_note": "## H0A : abstention populaire\n\nLes points présentés sont uniquement ceux du périmètre sélectionné. Ils ne suffisent pas à établir une transformation de long terme. KRT, R EI et NLS restent des modèles distincts.",
            "h1_note": "## H1 : vote populaire à gauche\n\nLa lecture est limitée aux scrutins sélectionnés. Aucune conclusion sur toute la période historique n'est déduite de cette exécution. Les législatives et présidentielles restent distinctes.",
            "methods": "## Méthodes NLS, KRT et réplication R\n\nKRT estime les mêmes modèles bêta-binomiaux que le contrat historique, avec le backend PyMC ou NumPyro fixé par couple. NLS conserve son objectif déterministe multi-départs sans intervalle validé. King EI sous R conserve sa formulation à normale tronquée ; il ne constitue pas le même modèle que KRT.",
            "distribution": f"## Distributions communales\n\n{get_scope().density_count} figures KRT/R pour les {get_scope().pair_count} couples sélectionnés, dans [le lecteur plein format](ANNEXE_ATLAS_DENSITES.html). Elles montrent des moyennes communales estimées, ni individus observés ni distribution postérieure nationale. Les valeurs non finies sont exclues sans imputation et leur couverture est indiquée.",
        }
        for block in blocks:
            if block["id"] in overrides:
                block["body"] = overrides[block["id"]]
        artifact["manifest"]["description"] = scope_notice()
        artifact["snapshot"]["replication_scope"] = get_scope().as_dict()
        artifact["snapshot"]["status"] = "share_with_caveats"
    path = REPORT_BUILD / "artifact.json"
    write_json(path, artifact)
    write_json(REPORT_BUILD / "REPORT_STATISTICS.json", stats)
    return path


def build_documentation(row_counts: dict[str, int]) -> None:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    stats = report_statistics()
    readme = f"""# Livraison professeur — résultats longitudinaux 1962–2022

## À retenir

- couverture canonique : **240/240 couples KRT Python** et **240/240 couples R EI** ;
- panel fixe : **2 000 communes**, avec département, région, VBBM et provenance ;
- NLS : **{stats['nls_diagnostics'].get('pass', 0)}/292** couples admissibles au diagnostic numérique `pass` ;
- sensibilités NLS covariées : **960 ajustements** (quatre spécifications × 240 couples), avec statuts de rang et conditionnement conservés ;
- KRT : **{stats['krt_mcmc'].get('pass', 0)}/240** couples au statut MCMC synthétique `pass`; les statuts `caveat` et `fail` restent livrés et visibles ;
- les dix hypothèses sont présentées avec KRT, R EI et NLS en parallèle, en séparant législatives et présidentielles ;
- les 480 graphiques de densité sont accessibles dans `01_RAPPORT/ANNEXE_ATLAS_DENSITES.html` ;
- aucune relance diagnostique ciblée n'est sélectionnée : politique `initial_only`.

## Ordre de lecture

1. `01_RAPPORT/RAPPORT_LONGITUDINAL.html` — surface canonique portable ;
2. `01_RAPPORT/RAPPORT_LONGITUDINAL.pdf` — export secondaire ;
3. `01_RAPPORT/ANNEXE_ATLAS_DENSITES.html` — 480 densités plein format ;
4. `03_FIGURES/` — trajectoires KRT–R–NLS, sensibilités covariées et planches de densités ;
5. `02_TABLES_PRINCIPALES/` — tables Parquet exactes ;
6. `05_DIAGNOSTICS/` — statuts MCMC, identification, NLS et R EI ;
7. `06_DOCUMENTATION/` — dictionnaire, scénarios, reproduction et manifeste.

## Limite d'interprétation

Les β décrivent des associations écologiques estimées sous contraintes de marges. Ils ne sont ni des comportements individuels observés, ni des effets causaux. Une estimation calculée reste accompagnée de son statut de convergence et d'identification.
"""
    write_text(LIGHT / "00_README_PROFESSEUR.md", readme)

    scenarios = pd.read_csv(SCENARIOS)
    scenarios.to_csv(DOC_DIR / "MODEL_SCENARIOS.csv", index=False, encoding="utf-8-sig")

    descriptions = {
        "election_id": "Identifiant stable du scrutin.",
        "scenario_id": "Identifiant de l'hypothèse politique.",
        "unit_id": "Identifiant stable de la commune.",
        "department": "Département harmonisé.",
        "region13": "Région harmonisée à 13 régions.",
        "vbbm": "Classe VBBM jointe à la commune.",
        "b1_mean": "Moyenne postérieure communale de β₁.",
        "b2_mean": "Moyenne postérieure communale de β₂.",
        "mean": "Moyenne de l'estimand agrégé.",
        "q025": "Quantile 2,5 %.",
        "q975": "Quantile 97,5 %.",
        "mcmc_status": "Statut synthétique des diagnostics MCMC.",
        "identification_status": "Statut synthétique d'identification.",
        "objective": "Valeur de l'objectif NLS.",
        "bread_condition": "Conditionnement de la matrice d'information NLS.",
        "seed": "Graine déterministe du run R.",
        "r_version": "Version de R utilisée.",
    }
    dictionary_rows: list[dict[str, object]] = []
    for name in row_counts:
        frame = pd.read_parquet(TABLES / name)
        for column, dtype in frame.dtypes.items():
            dictionary_rows.append(
                {
                    "table": name,
                    "grain": "commune × élection × hypothèse" if "commune" in name else "élection × hypothèse × estimand",
                    "column": column,
                    "dtype": str(dtype),
                    "nullable": bool(frame[column].isna().any()),
                    "description": descriptions.get(column, "Champ documenté par son nom contractuel et sa table source."),
                    "provenance": "sortie canonique initial_only ou jointure déclarée dans build_professor_release_assets.py",
                }
            )
    pd.DataFrame(dictionary_rows).to_csv(DOC_DIR / "DATA_DICTIONARY.csv", index=False, encoding="utf-8-sig")

    reproduce = """# Reproduction

Depuis la racine `ARE/part2/longitudinal_2022`, avec l'environnement Python/R documenté :

```powershell
python -m code_longitudinal.consolidate_current_krt_all_2x2 --selection-policy initial_only
python -m code_longitudinal.consolidate_r_ei_all_2x2
python -m code_longitudinal.compare_python_r_ei_full_240
python -m code_longitudinal.run_fast_nls_covariate_specs
python -m code_longitudinal.build_professor_release_assets
python -m code_longitudinal.build_density_report_atlas
powershell -ExecutionPolicy Bypass -File reproducibility/presentation/compose_slide_figures.ps1
```

Le modèle R est exécuté séquentiellement par `r_replication/run_king_ei_replication.R`. Les relances diagnostiques ciblées déjà présentes sont conservées uniquement dans l'archive technique d'audit et ne sont jamais sélectionnées dans cette livraison.

La présentation validée est figée, contrôlée par SHA-256 et restaurable par `python -m reproducibility.restore_presentation`. Elle couvre les dix hypothèses; les huit compositions législatives-présidentielles sont régénérables par la commande PowerShell ci-dessus.
"""
    write_text(DOC_DIR / "REPRODUCE.md", reproduce)
    changelog = """# Changelog

## 2026-09-01 — présentation complète des hypothèses

- passage de 14 à 20 diapositives ;
- ajout de vues dédiées H0B, H0C et H2-H7 avec trajectoires KRT, R EI et NLS ;
- mise en regard systématique des législatives et des présidentielles ;
- conservation de l'atlas exhaustif des 480 densités comme annexe séparée pour la lisibilité.

## 2026-08-31 — enrichissement analytique

- ajout des trajectoires β₁−β₂ KRT–R–NLS pour les dix hypothèses ;
- ajout de quatre sensibilités NLS avec covariables communales, 960 ajustements ;
- intégration d'un atlas HTML des 480 densités et de 40 planches de synthèse.

## 2026-08-30 — livraison 240/240

- consolidation Python KRT canonique `initial_only` : 240/240 ;
- réplication R EI/eiPack : 240/240 ;
- correction canonique du schéma H4 (`agri_indp` / `salaries`) ;
- ajout des tables R enrichies, des cinq familles de figures, du rapport HTML/PDF et de la présentation ;
- séparation d'un ZIP professeur léger et d'un ZIP technique d'audit.
"""
    write_text(DOC_DIR / "CHANGELOG.md", changelog)


def compose_slide_figures(*, project_root: Path | None = None, script_path: Path | None = None) -> None:
    """Run the unchanged historical eight-figure composition producer."""
    project_root = ROOT if project_root is None else project_root
    script_path = ROOT / "reproducibility/presentation/compose_slide_figures.ps1" if script_path is None else script_path
    subprocess.run([
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        str(script_path), "-ProjectRoot", str(project_root),
    ], cwd=project_root, check=True, stdout=sys.stdout, stderr=sys.stderr)


def main() -> None:
    safe_reset(LIGHT, "longitudinal_2000_release_professeur_candidate")
    REPORT_BUILD.mkdir(parents=True, exist_ok=True)
    row_counts = build_main_tables()
    build_panel_and_harmonisation()
    build_diagnostics()
    build_figures()
    compose_slide_figures()
    build_documentation(row_counts)
    artifact = build_report_artifact()
    receipt = {
        "schema_version": "professor_release_assets_prepare_v1",
        "status": "prepared",
        "created_at_utc": utc_now(),
        "light_candidate": str(LIGHT),
        "report_artifact": str(artifact),
        "table_row_counts": row_counts,
        "python_pairs": get_scope().pair_count,
        "r_pairs": get_scope().pair_count,
        "replication_scope": get_scope().as_dict(),
        "figure_files": len(list(FIGURES.rglob("*.png"))) + len(list(FIGURES.rglob("*.svg"))),
    }
    write_json(REPORT_BUILD / "ASSETS_PREPARE_RECEIPT.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
