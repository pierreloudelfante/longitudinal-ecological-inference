from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .density_figures_v2 import (
    plot_joint_density_v2,
    plot_marginal_density_v2,
    validate_density_data,
)
from .paths import ROOT
from .spec_registry import ELECTION_BY_ID
from .utils import file_sha256


SCENARIOS = ("H0A", "H1")
ESTIMANDS = ("b_1", "b_2", "b_1_minus_b_2")
PANEL_ID = "longitudinal_2000_v1__strict_nested_3000__seed_20260803"
DEFAULT_OUTPUT = ROOT / "deliverables" / "h0a_h1_king_nls_r_eipack_2000_20260827"
VALIDATED_ROOT = ROOT / "work" / "longitudinal_2000_v1.0.2_H0A_H1_validated"
PYTHON_RESULTS = VALIDATED_ROOT / "01_resultats_python"
R_REPLICATION = ROOT / "outputs" / "longitudinal_2000_v1" / "r_replication"

KRT_AGGREGATE = PYTHON_RESULTS / "longitudinal_krt_aggregate.parquet"
KRT_COMMUNE = PYTHON_RESULTS / "longitudinal_krt_commune.parquet"
NLS_RESULTS = PYTHON_RESULTS / "longitudinal_nls.parquet"
R_AGGREGATE = R_REPLICATION / "longitudinal_king_ei_r_aggregate_all_2x2.parquet"
R_COMMUNE = R_REPLICATION / "longitudinal_king_ei_r_commune_all_2x2.parquet"

METHODS = {
    "krt": {
        "label": "KRT Python",
        "color": "#2F6B9A",
        "marker": "o",
        "linestyle": "-",
    },
    "r_eipack": {
        "label": "R ei/eiPack",
        "color": "#D0823B",
        "marker": "s",
        "linestyle": "--",
    },
    "nls": {
        "label": "NLS",
        "color": "#4B5563",
        "marker": "D",
        "linestyle": ":",
    },
}

SCENARIO_LABELS = {
    "H0A": "H0A — Abstention, ouvriers et employés vs autres CSP",
    "H1": "H1 — Vote à gauche, ouvriers et employés vs autres CSP",
}

ESTIMAND_LABELS = {
    "b_1": "β₁ — ouvriers et employés",
    "b_2": "β₂ — autres CSP",
    "b_1_minus_b_2": "Contraste β₁ − β₂",
}

ELECTION_LABELS = {
    "legislative": "Législatives",
    "presidential": "Présidentielles",
}

DENSITY_ELECTIONS = ("leg_1962_r1", "leg_1986_r1", "leg_2022_r1")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _election_frame() -> pd.DataFrame:
    rows = [
        {
            "election_id": election.election_id,
            "year": election.year,
            "round": election.round,
            "election_type": election.election_type,
        }
        for election in ELECTION_BY_ID.values()
    ]
    return pd.DataFrame(rows)


def _assert_unique(frame: pd.DataFrame, keys: list[str], label: str) -> None:
    duplicates = frame.duplicated(keys, keep=False)
    if duplicates.any():
        sample = frame.loc[duplicates, keys].head(10).to_dict("records")
        raise AssertionError(f"{label} contains duplicate keys: {sample}")


def _assert_complete_aggregate(frame: pd.DataFrame, label: str) -> None:
    keys = ["panel_id", "election_id", "scenario_id", "estimand"]
    _assert_unique(frame, keys, label)
    pairs = frame[["election_id", "scenario_id"]].drop_duplicates()
    if len(pairs) != 52:
        counts = pairs.groupby("scenario_id").size().to_dict()
        raise AssertionError(f"{label} must contain 52 pairs; found {counts}")
    if len(frame) != 156:
        counts = frame.groupby(["scenario_id", "estimand"]).size().to_dict()
        raise AssertionError(f"{label} must contain 156 aggregate rows; found {counts}")


def _load_krt() -> tuple[pd.DataFrame, pd.DataFrame]:
    aggregate = pd.read_parquet(_require(KRT_AGGREGATE))
    aggregate = aggregate.loc[
        aggregate["scenario_id"].isin(SCENARIOS)
        & aggregate["estimand"].isin(ESTIMANDS)
        & aggregate["panel_id"].eq(PANEL_ID)
    ].copy()
    aggregate["election_type"] = aggregate["election_id"].map(
        lambda value: ELECTION_BY_ID[str(value)].election_type
    )
    aggregate["method"] = "krt"
    aggregate["q50"] = aggregate["median"]
    _assert_complete_aggregate(aggregate, "KRT aggregate")

    commune = pd.read_parquet(_require(KRT_COMMUNE))
    commune = commune.loc[
        commune["scenario_id"].isin(SCENARIOS) & commune["panel_id"].eq(PANEL_ID)
    ].copy()
    _assert_unique(commune, ["election_id", "scenario_id", "unit_id"], "KRT commune")
    if len(commune) != 104_000:
        raise AssertionError(f"KRT commune must contain 104000 rows; found {len(commune)}")
    return aggregate, commune


def _load_nls() -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_parquet(_require(NLS_RESULTS))
    raw = raw.loc[
        raw["scenario_id"].isin(SCENARIOS) & raw["panel_id"].eq(PANEL_ID)
    ].copy()
    _assert_unique(
        raw,
        ["election_id", "scenario_id", "estimand_type", "social_group", "vote_category"],
        "NLS raw",
    )
    if len(raw) != 260:
        raise AssertionError(f"NLS H0A/H1 must contain 260 source rows; found {len(raw)}")

    event = {"H0A": "abstention", "H1": "gauche"}
    rows: list[pd.DataFrame] = []
    for scenario_id in SCENARIOS:
        scenario = raw.loc[
            raw["scenario_id"].eq(scenario_id)
            & raw["vote_category"].eq(event[scenario_id])
        ]
        selectors = (
            ("cell_probability", "target_group", "b_1"),
            ("cell_probability", "complement_group", "b_2"),
            ("group_contrast", "target_group_minus_complement_group", "b_1_minus_b_2"),
        )
        for estimand_type, social_group, estimand in selectors:
            selected = scenario.loc[
                scenario["estimand_type"].eq(estimand_type)
                & scenario["social_group"].eq(social_group)
            ].copy()
            selected["estimand"] = estimand
            rows.append(selected)
    aggregate = pd.concat(rows, ignore_index=True)
    aggregate["election_type"] = aggregate["election_id"].map(
        lambda value: ELECTION_BY_ID[str(value)].election_type
    )
    aggregate["method"] = "nls"
    aggregate["mean"] = aggregate["estimate"].astype(float)
    aggregate["q025"] = np.nan
    aggregate["q50"] = aggregate["estimate"].astype(float)
    aggregate["q975"] = np.nan
    _assert_complete_aggregate(aggregate, "NLS aggregate")
    return aggregate, raw


def _load_r_eipack(*, allow_partial: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    aggregate = pd.read_parquet(_require(R_AGGREGATE))
    aggregate = aggregate.loc[
        aggregate["scenario_id"].isin(SCENARIOS) & aggregate["panel_id"].eq(PANEL_ID)
    ].copy()
    mapping = {
        "beta1_aggregate": "b_1",
        "beta2_aggregate": "b_2",
        "contrast_aggregate": "b_1_minus_b_2",
    }
    aggregate["estimand"] = aggregate["estimand"].map(mapping).fillna(aggregate["estimand"])
    aggregate = aggregate.merge(_election_frame(), on="election_id", how="left", validate="many_to_one")
    aggregate["method"] = "r_eipack"
    if allow_partial:
        _assert_unique(
            aggregate,
            ["panel_id", "election_id", "scenario_id", "estimand"],
            "R ei/eiPack aggregate",
        )
        counts = aggregate.groupby(["scenario_id", "estimand"]).size().to_dict()
        if counts.get(("H0A", "b_1"), 0) != 26:
            raise AssertionError(f"partial R output must at least contain complete H0A; found {counts}")
    else:
        _assert_complete_aggregate(aggregate, "R ei/eiPack aggregate")

    commune = pd.read_parquet(_require(R_COMMUNE))
    commune = commune.loc[
        commune["scenario_id"].isin(SCENARIOS) & commune["panel_id"].eq(PANEL_ID)
    ].copy()
    commune = commune.merge(_election_frame(), on="election_id", how="left", validate="many_to_one")
    _assert_unique(commune, ["election_id", "scenario_id", "unit_id"], "R ei/eiPack commune")
    if not allow_partial and len(commune) != 104_000:
        counts = commune.groupby("scenario_id").size().to_dict()
        raise AssertionError(f"R ei/eiPack commune must contain 104000 rows; found {counts}")
    if allow_partial and len(commune) < 52_000:
        raise AssertionError(f"partial R commune output must at least contain H0A; found {len(commune)}")
    return aggregate, commune


def _comparison(
    krt: pd.DataFrame, nls: pd.DataFrame, r_eipack: pd.DataFrame
) -> pd.DataFrame:
    keys = [
        "panel_id",
        "election_id",
        "year",
        "round",
        "election_type",
        "scenario_id",
        "estimand",
    ]
    krt_columns = keys + [
        "run_id",
        "mean",
        "q025",
        "q50",
        "q975",
        "mcmc_status",
        "identification_status",
        "n_posterior_draws",
        "n_communes",
    ]
    nls_columns = keys + [
        "run_id",
        "mean",
        "fit_status",
        "diagnostic_status",
        "objective",
        "bread_condition",
        "n_communes",
    ]
    r_columns = keys + ["mean", "sd", "q025", "q50", "q975", "n_posterior_draws"]

    result = krt[krt_columns].rename(
        columns={
            "run_id": "run_id_krt",
            "mean": "mean_krt",
            "q025": "q025_krt",
            "q50": "q50_krt",
            "q975": "q975_krt",
            "n_posterior_draws": "n_posterior_draws_krt",
            "n_communes": "n_communes_krt",
        }
    )
    result = result.merge(
        r_eipack[r_columns].rename(
            columns={
                "mean": "mean_r_eipack",
                "sd": "sd_r_eipack",
                "q025": "q025_r_eipack",
                "q50": "q50_r_eipack",
                "q975": "q975_r_eipack",
                "n_posterior_draws": "n_posterior_draws_r_eipack",
            }
        ),
        on=keys,
        how="left",
        validate="one_to_one",
    )
    result = result.merge(
        nls[nls_columns].rename(
            columns={
                "run_id": "run_id_nls",
                "mean": "mean_nls",
                "fit_status": "fit_status_nls",
                "diagnostic_status": "diagnostic_status_nls",
                "objective": "objective_nls",
                "bread_condition": "bread_condition_nls",
                "n_communes": "n_communes_nls",
            }
        ),
        on=keys,
        how="left",
        validate="one_to_one",
    )
    if len(result) != 156:
        raise AssertionError(f"comparison must contain 156 rows; found {len(result)}")
    required = ["mean_krt", "mean_nls"]
    if result[required].isna().any().any():
        missing = result.loc[result[required].isna().any(axis=1), keys + required]
        raise AssertionError(f"method comparison is incomplete: {missing.head(10).to_dict('records')}")

    result["r_minus_krt"] = result["mean_r_eipack"] - result["mean_krt"]
    result["nls_minus_krt"] = result["mean_nls"] - result["mean_krt"]
    result["r_minus_nls"] = result["mean_r_eipack"] - result["mean_nls"]
    for column in ("r_minus_krt", "nls_minus_krt", "r_minus_nls"):
        result[f"abs_{column}"] = result[column].abs()
    r_available = result["mean_r_eipack"].notna()
    result["r_krt_intervals_overlap"] = pd.Series(pd.NA, index=result.index, dtype="boolean")
    result.loc[r_available, "r_krt_intervals_overlap"] = (
        result.loc[r_available, ["q975_r_eipack", "q975_krt"]].min(axis=1)
        >= result.loc[r_available, ["q025_r_eipack", "q025_krt"]].max(axis=1)
    )
    result["nls_inside_krt_interval"] = result["mean_nls"].between(
        result["q025_krt"], result["q975_krt"]
    )
    result["nls_inside_r_interval"] = pd.Series(pd.NA, index=result.index, dtype="boolean")
    result.loc[r_available, "nls_inside_r_interval"] = result.loc[r_available, "mean_nls"].between(
        result.loc[r_available, "q025_r_eipack"], result.loc[r_available, "q975_r_eipack"]
    )
    return result.sort_values(["scenario_id", "election_type", "year", "estimand"])


def _method_summary(comparison: pd.DataFrame) -> pd.DataFrame:
    method_pairs = (
        ("R ei/eiPack vs KRT", "mean_r_eipack", "mean_krt", "r_minus_krt"),
        ("NLS vs KRT", "mean_nls", "mean_krt", "nls_minus_krt"),
        ("R ei/eiPack vs NLS", "mean_r_eipack", "mean_nls", "r_minus_nls"),
    )
    rows: list[dict[str, object]] = []
    for (scenario_id, estimand), group in comparison.groupby(["scenario_id", "estimand"]):
        for label, left, right, difference in method_pairs:
            available = group[[left, right, difference]].dropna()
            rows.append(
                {
                    "scenario_id": scenario_id,
                    "estimand": estimand,
                    "comparison": label,
                    "n_elections": len(available),
                    "mean_difference": float(available[difference].mean()) if len(available) else np.nan,
                    "mean_absolute_difference": float(available[difference].abs().mean()) if len(available) else np.nan,
                    "median_absolute_difference": float(available[difference].abs().median()) if len(available) else np.nan,
                    "max_absolute_difference": float(available[difference].abs().max()) if len(available) else np.nan,
                    "pearson_correlation": float(available[left].corr(available[right])) if len(available) > 1 else np.nan,
                }
            )
    summary = pd.DataFrame(rows)
    interval_rows = (
        comparison.groupby(["scenario_id", "estimand"])
        .agg(
            r_krt_interval_overlap_rate=("r_krt_intervals_overlap", "mean"),
            nls_inside_krt_rate=("nls_inside_krt_interval", "mean"),
            nls_inside_r_rate=("nls_inside_r_interval", "mean"),
        )
        .reset_index()
    )
    return summary.merge(interval_rows, on=["scenario_id", "estimand"], how="left")


def _pair_diagnostics(
    krt: pd.DataFrame, nls: pd.DataFrame, r_eipack: pd.DataFrame
) -> pd.DataFrame:
    keys = ["panel_id", "election_id", "year", "round", "election_type", "scenario_id"]
    krt_pairs = krt[
        keys
        + [
            "run_id",
            "mcmc_status",
            "identification_status",
            "draws",
            "tune",
            "chains",
            "target_accept",
            "max_treedepth",
            "king_lambda",
        ]
    ].drop_duplicates(keys)
    nls_pairs = nls[
        keys + ["run_id", "fit_status", "diagnostic_status", "objective", "bread_condition"]
    ].drop_duplicates(keys)
    r_pairs = r_eipack[keys].drop_duplicates(keys)
    result = krt_pairs.merge(
        nls_pairs.rename(
            columns={
                "run_id": "run_id_nls",
                "fit_status": "fit_status_nls",
                "diagnostic_status": "diagnostic_status_nls",
                "objective": "objective_nls",
                "bread_condition": "bread_condition_nls",
            }
        ),
        on=keys,
        how="left",
        validate="one_to_one",
    )
    result = result.rename(columns={"run_id": "run_id_krt"})
    result = result.merge(
        r_pairs.assign(r_eipack_status="success"),
        on=keys,
        how="left",
        validate="one_to_one",
    )
    if len(result) != 52:
        raise AssertionError(f"pair diagnostics must contain 52 rows; found {len(result)}")
    result["r_eipack_status"] = result["r_eipack_status"].fillna("pending")
    return result.sort_values(["scenario_id", "election_type", "year"])


def _style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 10.5,
            "axes.labelsize": 9,
            "axes.edgecolor": "#98A2AD",
            "axes.linewidth": 0.8,
            "axes.grid": True,
            "grid.color": "#E5E7EB",
            "grid.linewidth": 0.7,
            "grid.alpha": 0.9,
            "xtick.color": "#374151",
            "ytick.color": "#374151",
            "text.color": "#1F2937",
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "legend.frameon": False,
        }
    )


def _save_figure(fig: plt.Figure, base: Path) -> list[Path]:
    paths = [base.with_suffix(".png"), base.with_suffix(".svg")]
    fig.savefig(paths[0], dpi=220, bbox_inches="tight", facecolor="white")
    fig.savefig(paths[1], bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return paths


def _method_series(frame: pd.DataFrame, method: str) -> tuple[np.ndarray, ...]:
    return (
        frame["year"].to_numpy(dtype=float),
        frame[f"mean_{method}"].to_numpy(dtype=float),
        frame[f"q025_{method}"].to_numpy(dtype=float)
        if f"q025_{method}" in frame.columns
        else np.full(len(frame), np.nan),
        frame[f"q975_{method}"].to_numpy(dtype=float)
        if f"q975_{method}" in frame.columns
        else np.full(len(frame), np.nan),
    )


def _finite_max(*series: pd.Series, default: float = 0.0) -> float:
    values = np.concatenate([item.to_numpy(dtype=float) for item in series])
    values = values[np.isfinite(values)]
    return float(values.max()) if len(values) else default


def _finite_absmax(*series: pd.Series, default: float = 0.0) -> float:
    values = np.concatenate([item.to_numpy(dtype=float) for item in series])
    values = values[np.isfinite(values)]
    return float(np.abs(values).max()) if len(values) else default


def _plot_scenario_trajectories(
    comparison: pd.DataFrame, scenario_id: str, figures: Path
) -> list[Path]:
    data = comparison.loc[comparison["scenario_id"].eq(scenario_id)]
    fig, axes = plt.subplots(2, 3, figsize=(17.0, 8.6), sharex="row")
    fig.text(
        0.025,
        0.99,
        SCENARIO_LABELS[scenario_id],
        fontsize=16,
        fontweight="bold",
        ha="left",
        va="top",
    )
    fig.text(
        0.025,
        0.955,
        "Panel fixe de 2 000 communes · 26 scrutins · intervalles à 95 % pour KRT et R ; NLS est ponctuel",
        fontsize=9.5,
        color="#4B5563",
        ha="left",
    )
    level_upper = min(1.0, _finite_max(data["q975_krt"], data["q975_r_eipack"], data["mean_nls"]) + 0.06)
    contrast_values = data.loc[data["estimand"].eq("b_1_minus_b_2")]
    contrast_bound = _finite_absmax(
        contrast_values["q025_krt"],
        contrast_values["q975_krt"],
        contrast_values["q025_r_eipack"],
        contrast_values["q975_r_eipack"],
        contrast_values["mean_nls"],
    )
    contrast_bound = min(1.0, contrast_bound + 0.04)

    offsets = {"krt": -0.18, "r_eipack": 0.18, "nls": 0.0}
    for row, election_type in enumerate(("legislative", "presidential")):
        for column, estimand in enumerate(ESTIMANDS):
            ax = axes[row, column]
            subset = data.loc[
                data["election_type"].eq(election_type) & data["estimand"].eq(estimand)
            ].sort_values("year")
            for method in ("krt", "r_eipack", "nls"):
                style = METHODS[method]
                if subset[f"mean_{method}"].notna().sum() == 0:
                    continue
                x = subset["year"].to_numpy(dtype=float) + offsets[method]
                y = subset[f"mean_{method}"].to_numpy(dtype=float)
                if method == "nls":
                    ax.plot(
                        x,
                        y,
                        label=style["label"],
                        color=style["color"],
                        marker=style["marker"],
                        linestyle=style["linestyle"],
                        linewidth=1.2,
                        markersize=4.2,
                    )
                else:
                    low = subset[f"q025_{method}"].to_numpy(dtype=float)
                    high = subset[f"q975_{method}"].to_numpy(dtype=float)
                    ax.errorbar(
                        x,
                        y,
                        yerr=np.vstack([y - low, high - y]),
                        label=style["label"],
                        color=style["color"],
                        marker=style["marker"],
                        markerfacecolor="white" if method == "r_eipack" else style["color"],
                        linestyle=style["linestyle"],
                        linewidth=1.25,
                        markersize=4.4,
                        elinewidth=0.75,
                        capsize=1.8,
                        alpha=0.96,
                    )
            if estimand == "b_1_minus_b_2":
                ax.axhline(0, color="#111827", linewidth=0.8)
                ax.set_ylim(-contrast_bound, contrast_bound)
            else:
                ax.set_ylim(0, level_upper)
            if row == 0:
                ax.set_title(ESTIMAND_LABELS[estimand], loc="left", fontweight="bold")
            ax.set_ylabel(ELECTION_LABELS[election_type] if column == 0 else "")
            ax.set_xlabel("Année" if row == 1 else "")
            ax.spines[["top", "right"]].set_visible(False)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", bbox_to_anchor=(0.965, 0.985), ncol=3)
    fig.text(
        0.025,
        0.015,
        "KRT Python : beta-binomial hiérarchique. R ei/eiPack : EI classique de King, modèle non identique. NLS : benchmark déterministe sans intervalle.",
        fontsize=8.4,
        color="#4B5563",
    )
    fig.tight_layout(rect=(0.02, 0.045, 0.98, 0.89), h_pad=1.5, w_pad=1.4)
    return _save_figure(fig, figures / f"01_trajectoires_methodes_{scenario_id.lower()}")


def _plot_contrasts(comparison: pd.DataFrame, figures: Path) -> list[Path]:
    data = comparison.loc[comparison["estimand"].eq("b_1_minus_b_2")]
    bound = _finite_absmax(
        data["q025_krt"],
        data["q975_krt"],
        data["q025_r_eipack"],
        data["q975_r_eipack"],
        data["mean_nls"],
    ) + 0.04
    fig, axes = plt.subplots(2, 2, figsize=(14.8, 8.5), sharey=True)
    fig.suptitle("Contrastes H0A et H1 selon la méthode", fontsize=16, fontweight="bold", x=0.07, ha="left")
    fig.text(
        0.07,
        0.935,
        "β₁ − β₂ ; une valeur positive indique une probabilité estimée plus élevée chez les ouvriers et employés",
        fontsize=9.5,
        color="#4B5563",
        ha="left",
    )
    offsets = {"krt": -0.18, "r_eipack": 0.18, "nls": 0.0}
    for row, scenario_id in enumerate(SCENARIOS):
        for column, election_type in enumerate(("legislative", "presidential")):
            ax = axes[row, column]
            subset = data.loc[
                data["scenario_id"].eq(scenario_id)
                & data["election_type"].eq(election_type)
            ].sort_values("year")
            for method in ("krt", "r_eipack", "nls"):
                style = METHODS[method]
                if subset[f"mean_{method}"].notna().sum() == 0:
                    continue
                x = subset["year"].to_numpy(dtype=float) + offsets[method]
                y = subset[f"mean_{method}"].to_numpy(dtype=float)
                if method == "nls":
                    ax.plot(
                        x,
                        y,
                        color=style["color"],
                        marker=style["marker"],
                        linestyle=style["linestyle"],
                        linewidth=1.2,
                        markersize=4.2,
                        label=style["label"],
                    )
                else:
                    low = subset[f"q025_{method}"].to_numpy(dtype=float)
                    high = subset[f"q975_{method}"].to_numpy(dtype=float)
                    ax.errorbar(
                        x,
                        y,
                        yerr=np.vstack([y - low, high - y]),
                        color=style["color"],
                        marker=style["marker"],
                        markerfacecolor="white" if method == "r_eipack" else style["color"],
                        linestyle=style["linestyle"],
                        linewidth=1.25,
                        markersize=4.4,
                        elinewidth=0.75,
                        capsize=1.8,
                        label=style["label"],
                    )
            ax.axhline(0, color="#111827", linewidth=0.8)
            ax.set_ylim(-bound, bound)
            ax.set_title(ELECTION_LABELS[election_type], loc="left", fontweight="bold")
            short_label = "H0A — abstention" if scenario_id == "H0A" else "H1 — vote à gauche"
            ax.set_ylabel(f"{short_label}\nContraste β₁ − β₂" if column == 0 else "")
            ax.set_xlabel("Année" if row == 1 else "")
            ax.spines[["top", "right"]].set_visible(False)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", bbox_to_anchor=(0.965, 0.985), ncol=3)
    fig.text(
        0.07,
        0.015,
        "Intervalles à 95 % pour KRT et R. Les trajectoires NLS sont des estimations ponctuelles ; aucune incertitude NLS n’est inventée.",
        fontsize=8.4,
        color="#4B5563",
    )
    fig.tight_layout(rect=(0.055, 0.045, 0.98, 0.90), h_pad=2.1, w_pad=1.4)
    return _save_figure(fig, figures / "02_contrastes_h0a_h1_methodes")


def _plot_method_scatter(comparison: pd.DataFrame, figures: Path) -> list[Path]:
    pairings = (
        ("mean_krt", "mean_r_eipack", "KRT Python", "R ei/eiPack"),
        ("mean_krt", "mean_nls", "KRT Python", "NLS"),
        ("mean_r_eipack", "mean_nls", "R ei/eiPack", "NLS"),
    )
    estimand_style = {
        "b_1": ("#2F6B9A", "o"),
        "b_2": ("#D2A43B", "s"),
        "b_1_minus_b_2": ("#C45A78", "^"),
    }
    fig, axes = plt.subplots(2, 3, figsize=(15.6, 9.2))
    fig.suptitle("Accord des estimations agrégées entre méthodes", fontsize=16, fontweight="bold", x=0.06, ha="left")
    fig.text(
        0.06,
        0.94,
        "Chaque point est un scrutin × estimand ; la diagonale indique l’égalité des estimations",
        fontsize=9.5,
        color="#4B5563",
        ha="left",
    )
    for row, scenario_id in enumerate(SCENARIOS):
        scenario = comparison.loc[comparison["scenario_id"].eq(scenario_id)]
        values = scenario[[item for pairing in pairings for item in pairing[:2]]].to_numpy(dtype=float)
        lower = min(-0.05, float(np.nanmin(values)) - 0.04)
        upper = min(1.0, float(np.nanmax(values)) + 0.04)
        for column, (x_col, y_col, x_label, y_label) in enumerate(pairings):
            ax = axes[row, column]
            for estimand, (color, marker) in estimand_style.items():
                subset = scenario.loc[
                    scenario["estimand"].eq(estimand)
                    & scenario[x_col].notna()
                    & scenario[y_col].notna()
                ]
                ax.scatter(
                    subset[x_col],
                    subset[y_col],
                    s=32,
                    facecolor=color if estimand != "b_2" else "white",
                    edgecolor=color,
                    marker=marker,
                    linewidth=0.9,
                    alpha=0.9,
                    label=ESTIMAND_LABELS[estimand],
                )
            if scenario[[x_col, y_col]].dropna().empty:
                ax.text(
                    0.5,
                    0.5,
                    "Estimation R en attente",
                    transform=ax.transAxes,
                    ha="center",
                    va="center",
                    color="#6B7280",
                    fontsize=10,
                )
            ax.plot([lower, upper], [lower, upper], color="#111827", linewidth=0.9, linestyle="--")
            ax.set_xlim(lower, upper)
            ax.set_ylim(lower, upper)
            ax.set_aspect("equal", adjustable="box")
            ax.set_xlabel(x_label)
            ax.set_ylabel(y_label)
            ax.set_title(f"{scenario_id} · {x_label} vs {y_label}", loc="left", fontweight="bold")
            ax.spines[["top", "right"]].set_visible(False)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", bbox_to_anchor=(0.965, 0.99), ncol=3)
    fig.text(
        0.06,
        0.015,
        "La proximité de la diagonale mesure un accord descriptif, pas une équivalence mathématique des modèles.",
        fontsize=8.4,
        color="#4B5563",
    )
    fig.tight_layout(rect=(0.045, 0.045, 0.98, 0.90), h_pad=2.0, w_pad=1.6)
    return _save_figure(fig, figures / "03_scatter_accord_methodes")


def _plot_contrast_differences(comparison: pd.DataFrame, figures: Path) -> list[Path]:
    data = comparison.loc[comparison["estimand"].eq("b_1_minus_b_2")]
    bound = _finite_absmax(data["r_minus_krt"], data["nls_minus_krt"]) + 0.015
    fig, axes = plt.subplots(2, 2, figsize=(14.8, 8.2), sharey=True)
    fig.suptitle("Sensibilité du contraste à la méthode", fontsize=16, fontweight="bold", x=0.07, ha="left")
    fig.text(
        0.07,
        0.935,
        "Écart à KRT Python ; une valeur positive indique un contraste plus élevé que KRT",
        fontsize=9.5,
        color="#4B5563",
        ha="left",
    )
    series = (
        ("r_minus_krt", "R ei/eiPack − KRT", "#D0823B", "s", "--"),
        ("nls_minus_krt", "NLS − KRT", "#4B5563", "D", ":"),
    )
    for row, scenario_id in enumerate(SCENARIOS):
        for column, election_type in enumerate(("legislative", "presidential")):
            ax = axes[row, column]
            subset = data.loc[
                data["scenario_id"].eq(scenario_id)
                & data["election_type"].eq(election_type)
            ].sort_values("year")
            for field, label, color, marker, linestyle in series:
                ax.plot(
                    subset["year"],
                    subset[field],
                    color=color,
                    marker=marker,
                    markerfacecolor="white" if marker == "s" else color,
                    linestyle=linestyle,
                    linewidth=1.3,
                    markersize=4.5,
                    label=label,
                )
            ax.axhline(0, color="#111827", linewidth=0.8)
            ax.set_ylim(-bound, bound)
            ax.set_title(ELECTION_LABELS[election_type], loc="left", fontweight="bold")
            short_label = "H0A — abstention" if scenario_id == "H0A" else "H1 — vote à gauche"
            ax.set_ylabel(f"{short_label}\nÉcart au KRT" if column == 0 else "")
            ax.set_xlabel("Année" if row == 1 else "")
            ax.spines[["top", "right"]].set_visible(False)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", bbox_to_anchor=(0.96, 0.985), ncol=2)
    fig.text(
        0.07,
        0.015,
        "Les écarts reflètent à la fois la structure du modèle et la méthode d’estimation ; ils ne sont pas des erreurs de logiciel.",
        fontsize=8.4,
        color="#4B5563",
    )
    fig.tight_layout(rect=(0.055, 0.045, 0.98, 0.90), h_pad=2.0, w_pad=1.4)
    return _save_figure(fig, figures / "04_ecarts_contraste_par_methode")


def _plot_diagnostics(pair_diagnostics: pd.DataFrame, figures: Path) -> list[Path]:
    statuses = ("pass", "caveat", "fail")
    colors = {"pass": "#2F6B9A", "caveat": "#D2A43B", "fail": "#D0823B"}
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.8))
    fig.suptitle("Diagnostics des 52 ajustements KRT H0A–H1", fontsize=15, fontweight="bold", x=0.07, ha="left")
    diagnostics = (
        ("mcmc_status", "Diagnostic MCMC"),
        ("identification_status", "Identification écologique"),
    )
    for ax, (field, title) in zip(axes, diagnostics, strict=True):
        bottom = np.zeros(len(SCENARIOS))
        for status in statuses:
            counts = np.array(
                [
                    int(
                        (
                            pair_diagnostics["scenario_id"].eq(scenario_id)
                            & pair_diagnostics[field].eq(status)
                        ).sum()
                    )
                    for scenario_id in SCENARIOS
                ]
            )
            bars = ax.bar(
                SCENARIOS,
                counts,
                bottom=bottom,
                color=colors[status],
                edgecolor="white",
                linewidth=0.8,
                label=status,
            )
            for bar, value, base in zip(bars, counts, bottom, strict=True):
                if value:
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        base + value / 2,
                        str(value),
                        ha="center",
                        va="center",
                        fontsize=9,
                        color="white" if status != "caveat" else "#1F2937",
                        fontweight="bold",
                    )
            bottom += counts
        ax.set_ylim(0, 28)
        ax.set_ylabel("Nombre de couples élection–hypothèse")
        ax.set_title(title, loc="left", fontweight="bold")
        ax.spines[["top", "right"]].set_visible(False)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", bbox_to_anchor=(0.95, 0.98), ncol=3)
    fig.text(
        0.07,
        0.02,
        "Un ajustement terminé peut rester en caveat : convergence numérique et identification écologique sont évaluées séparément.",
        fontsize=8.4,
        color="#4B5563",
    )
    fig.tight_layout(rect=(0.05, 0.06, 0.98, 0.86), w_pad=2.0)
    return _save_figure(fig, figures / "05_diagnostics_krt_h0a_h1")


def _density_input_krt(krt_commune: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "scenario_id",
        "year",
        "unit_id",
        "b1_mean",
        "b2_mean",
        "b1_weight",
        "b2_weight",
    ]
    frame = krt_commune.loc[
        krt_commune["election_id"].isin(DENSITY_ELECTIONS), columns
    ].copy()
    frame["unit_id"] = frame["unit_id"].astype(str)
    return frame


def _density_input_r(
    r_commune: pd.DataFrame, krt_commune: pd.DataFrame
) -> pd.DataFrame:
    keys = ["panel_id", "election_id", "scenario_id", "unit_id"]
    values = r_commune.loc[
        r_commune["election_id"].isin(DENSITY_ELECTIONS),
        keys + ["year", "b1_mean", "b2_mean"],
    ].copy()
    if values.empty:
        return pd.DataFrame(
            columns=[
                "scenario_id",
                "year",
                "unit_id",
                "b1_mean",
                "b2_mean",
                "b1_weight",
                "b2_weight",
            ]
        )
    weights = krt_commune.loc[
        krt_commune["election_id"].isin(DENSITY_ELECTIONS),
        keys + ["b1_weight", "b2_weight"],
    ].copy()
    values["unit_id"] = values["unit_id"].astype(str)
    weights["unit_id"] = weights["unit_id"].astype(str)
    frame = values.merge(weights, on=keys, how="left", validate="one_to_one")
    if frame[["b1_weight", "b2_weight"]].isna().any().any():
        raise AssertionError("R density input could not be matched to KRT population weights")
    frame = frame[
        [
            "scenario_id",
            "year",
            "unit_id",
            "b1_mean",
            "b2_mean",
            "b1_weight",
            "b2_weight",
        ]
    ].copy()
    finite_columns = ["b1_mean", "b2_mean", "b1_weight", "b2_weight"]
    finite = np.isfinite(frame[finite_columns].to_numpy(dtype=float)).all(axis=1)
    return frame.loc[finite].copy()


def _plot_professor_density_family(
    krt_commune: pd.DataFrame,
    r_commune: pd.DataFrame,
    figures: Path,
) -> tuple[list[Path], pd.DataFrame]:
    """Reproduce the professor-requested 1962/1986/2022 density family."""

    method_inputs = {
        "krt": _density_input_krt(krt_commune),
        "r_eipack": _density_input_r(r_commune, krt_commune),
    }
    created: list[Path] = []
    metadata_rows: list[dict[str, object]] = []
    for method, raw in method_inputs.items():
        available = tuple(
            scenario_id
            for scenario_id in SCENARIOS
            if set(raw.loc[raw["scenario_id"].eq(scenario_id), "year"].unique())
            == {1962, 1986, 2022}
            and raw.loc[raw["scenario_id"].eq(scenario_id)]
            .groupby("year")
            .size()
            .ge(3)
            .all()
        )
        if not available:
            continue
        density_data = validate_density_data(raw, available)
        output_dir = figures / "densites_professeur" / method
        for scenario_id in available:
            scenario = density_data.loc[density_data["scenario_id"].eq(scenario_id)].copy()
            period_counts = scenario.groupby("year").size().to_dict()
            for weight_column in (None, "N_total"):
                paths, metadata = plot_joint_density_v2(
                    scenario,
                    scenario_id,
                    output_dir,
                    weight_column=weight_column,
                    grid_size=121,
                )
                created.extend(paths)
                metadata_rows.append(
                    {
                        "method": method,
                        **metadata,
                        **{f"n_communes_{year}": int(period_counts[year]) for year in (1962, 1986, 2022)},
                    }
                )
            paths, metadata = plot_marginal_density_v2(
                scenario,
                scenario_id,
                output_dir,
                grid_size=121,
            )
            created.extend(paths)
            metadata_rows.extend(
                {
                    "method": method,
                    **row,
                    **{f"n_communes_{year}": int(period_counts[year]) for year in (1962, 1986, 2022)},
                }
                for row in metadata
            )
    metadata = pd.DataFrame(metadata_rows)
    if metadata.empty:
        raise AssertionError("no professor density figure could be generated")
    return created, metadata


def _write_chart_map(path: Path, density_metadata: pd.DataFrame) -> None:
    rows = [
        {
            "figure": "01_trajectoires_methodes_h0a",
            "question": "Comment les probabilités et le contraste H0A évoluent-ils selon la méthode ?",
            "family": "Trend / Uncertainty & Benchmark",
            "grain": "scrutin × estimand × méthode",
            "takeaway_supported": "Comparer les trajectoires et l'incertitude sans attribuer d'intervalle au NLS.",
            "palette_policy": "hard two-root cap plus neutral",
        },
        {
            "figure": "01_trajectoires_methodes_h1",
            "question": "Comment les probabilités et le contraste H1 évoluent-ils selon la méthode ?",
            "family": "Trend / Uncertainty & Benchmark",
            "grain": "scrutin × estimand × méthode",
            "takeaway_supported": "Comparer les trajectoires et l'incertitude sans attribuer d'intervalle au NLS.",
            "palette_policy": "hard two-root cap plus neutral",
        },
        {
            "figure": "02_contrastes_h0a_h1_methodes",
            "question": "Les contrastes H0A/H1 changent-ils selon la méthode et le type de scrutin ?",
            "family": "Trend / Uncertainty & Benchmark",
            "grain": "scrutin × hypothèse × méthode",
            "takeaway_supported": "Comparer le signe, le niveau et les intervalles des contrastes.",
            "palette_policy": "hard two-root cap plus neutral",
        },
        {
            "figure": "03_scatter_accord_methodes",
            "question": "Quel est l'accord ponctuel entre KRT, R ei/eiPack et NLS ?",
            "family": "Relationship",
            "grain": "scrutin × estimand",
            "takeaway_supported": "Identifier accord global et écarts atypiques autour de la diagonale.",
            "palette_policy": "relaxed multi-category for estimands",
        },
        {
            "figure": "04_ecarts_contraste_par_methode",
            "question": "Quelle est la sensibilité du contraste à la méthode ?",
            "family": "Trend / Benchmark",
            "grain": "scrutin × hypothèse × comparaison de méthodes",
            "takeaway_supported": "Visualiser R−KRT et NLS−KRT avec une référence zéro.",
            "palette_policy": "hard two-root cap plus neutral",
        },
        {
            "figure": "05_diagnostics_krt_h0a_h1",
            "question": "Combien de fits KRT sont pass, caveat ou fail ?",
            "family": "Composition",
            "grain": "hypothèse × statut",
            "takeaway_supported": "Séparer convergence MCMC et identification écologique.",
            "palette_policy": "relaxed multi-category for ordered statuses",
        },
    ]
    density_scenarios = (
        density_metadata.groupby("method")["scenario_id"]
        .agg(lambda values: ", ".join(sorted(set(values))))
        .to_dict()
    )
    rows.extend(
        [
            {
                "figure": "densites_professeur/krt/joint_beta_*",
                "question": "Comment la distribution communale jointe de β₁ et β₂ se déplace-t-elle entre 1962, 1986 et 2022 ?",
                "family": "Distribution / Relationship",
                "grain": "commune × période × hypothèse; scénarios " + density_scenarios.get("krt", ""),
                "takeaway_supported": "Lire les noyaux de densité et régions HDR avec une bande commune entre périodes.",
                "palette_policy": "single-root preferred",
            },
            {
                "figure": "densites_professeur/krt/marginal_beta_*",
                "question": "Comment évoluent les densités marginales communales de β₁ et β₂ ?",
                "family": "Distribution",
                "grain": "commune × période × groupe social",
                "takeaway_supported": "Comparer 1962, 1986 et 2022 avec une largeur de lissage fixe.",
                "palette_policy": "relaxed multi-category for periods",
            },
            {
                "figure": "densites_professeur/r_eipack/*",
                "question": "Les densités communales R ei/eiPack présentent-elles la même structure descriptive ?",
                "family": "Distribution / Relationship",
                "grain": "commune × période × hypothèse; scénarios " + density_scenarios.get("r_eipack", "en attente"),
                "takeaway_supported": "Comparer la géométrie des estimations R sans supposer l’identité avec KRT.",
                "palette_policy": "single-root preferred",
            },
        ]
    )
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def _readme_text(
    summary: pd.DataFrame,
    density_metadata: pd.DataFrame,
    *,
    r_complete: bool,
    r_aggregate_rows: int,
    r_commune_rows: int,
) -> str:
    contrast_summary = summary.loc[summary["estimand"].eq("b_1_minus_b_2")].copy()
    display = contrast_summary[
        [
            "scenario_id",
            "comparison",
            "mean_absolute_difference",
            "max_absolute_difference",
            "pearson_correlation",
        ]
    ].copy()
    for column in ("mean_absolute_difference", "max_absolute_difference", "pearson_correlation"):
        display[column] = display[column].map(
            lambda value: "n.d." if pd.isna(value) else f"{value:.4f}"
        )
    markdown_rows = [
        "| Hypothèse | Comparaison | Écart absolu moyen | Écart absolu max | Corrélation |",
        "|---|---|---:|---:|---:|",
    ]
    markdown_rows.extend(
        "| {scenario_id} | {comparison} | {mean_absolute_difference} | {max_absolute_difference} | {pearson_correlation} |".format(
            **row
        )
        for row in display.to_dict("records")
    )
    summary_table = "\n".join(markdown_rows)
    r_status = (
        "R couvre H0A et H1 (52 couples)."
        if r_complete
        else (
            "R couvre actuellement H0A seulement (26 couples) ; le calcul H1 est lancé "
            "mais attend que la garde mémoire l'autorise. Le paquet devra ensuite être reconstruit."
        )
    )
    density_coverage = (
        density_metadata.groupby("method")["scenario_id"]
        .agg(lambda values: ", ".join(sorted(set(values))))
        .to_dict()
    )
    return f"""# H0A–H1 — KRT Python, R ei/eiPack et NLS

Ce dossier compare les résultats sur le panel longitudinal fixe de 2 000 communes et les 26 scrutins.

**Couverture R :** {r_status}

## Hypothèses

- **H0A** : abstention parmi les inscrits, ouvriers et employés (`β₁`) contre les autres CSP (`β₂`).
- **H1** : vote à gauche parmi les suffrages exprimés, même partition sociale.
- Le contraste est toujours `β₁ − β₂`.

## Tables Parquet

- `tables/h0a_h1_krt_aggregate.parquet` : 156 agrégats KRT, avec intervalles à 95 % et diagnostics.
- `tables/h0a_h1_krt_commune.parquet` : 104 000 lignes communales KRT.
- `tables/h0a_h1_nls_estimates.parquet` : 260 estimations NLS sources.
- `tables/h0a_h1_nls_aggregate.parquet` : 156 agrégats NLS harmonisés avec les estimands KRT/R.
- `tables/h0a_h1_r_eipack_aggregate.parquet` : {r_aggregate_rows} agrégats R `ei`/`eiPack`.
- `tables/h0a_h1_r_eipack_commune.parquet` : {r_commune_rows} lignes communales R.
- `tables/h0a_h1_method_comparison_aggregate.parquet` : jointure un-à-un des trois méthodes.
- `tables/h0a_h1_method_summary.parquet` : écarts, corrélations et couvertures d’intervalles.
- `tables/h0a_h1_pair_diagnostics.parquet` : un enregistrement par couple élection–hypothèse.
- `tables/h0a_h1_density_bandwidths.parquet` : paramètres de lissage et effectifs efficaces des densités.

## Figures

Les figures sont livrées en PNG et SVG dans `figures/`. Les législatives et présidentielles sont séparées afin d’éviter de relier artificiellement deux séries électorales différentes.

### Densités demandées par le professeur

Le sous-dossier `figures/densites_professeur/` reprend la famille du ZIP antérieur :

- densités jointes de `β₁` et `β₂` en 1962, 1986 et 2022, à poids égal entre communes ;
- mêmes densités pondérées par la population communale ;
- densités marginales de `β₁` et `β₂`, pondérées par l’effectif du groupe ;
- matrice ou largeur de lissage fixe entre les trois périodes pour permettre la comparaison.

Couverture : KRT = {density_coverage.get('krt', 'n.d.')} ; R ei/eiPack = {density_coverage.get('r_eipack', 'en attente')}.
Les densités R utilisent uniquement les communes où `β₁` et `β₂` sont tous deux finis ; l’effectif exact est affiché dans chaque panneau et enregistré dans la table des largeurs de lissage.
Le NLS ne produit pas de distribution communale : il apparaît comme estimation ponctuelle dans les figures de comparaison, mais aucune fausse densité NLS n’est construite.

## Résumé des contrastes

{summary_table}

## Caveats indispensables

- Le modèle R est l’EI classique de King (normale bivariée tronquée) via `ei` 1.3-3 / `eiPack` 0.2-2 ; il n’est pas mathématiquement identique au KRT beta-binomial Python.
- Le NLS est un benchmark déterministe ponctuel : aucune bande d’incertitude NLS n’est fabriquée.
- Les résultats restent des inférences écologiques ; ils ne démontrent pas des comportements individuels ni une relation causale.
- `mcmc_status` et `identification_status` doivent être lus séparément.
"""


def _write_manifest(
    output: Path,
    created_files: Iterable[Path],
    source_paths: Iterable[Path],
    row_counts: dict[str, int],
    r_complete: bool,
    density_metadata: pd.DataFrame,
) -> Path:
    manifest_path = output / "MANIFEST.json"
    payload = {
        "schema_version": "h0a_h1_method_outputs_v1",
        "created_at_utc": _utc_now(),
        "panel_id": PANEL_ID,
        "panel_size": 2000,
        "scenarios": list(SCENARIOS),
        "elections_per_scenario": 26,
        "methods": {
            "krt": "Python KRT beta-binomial hierarchical model",
            "r_eipack": "King classical EI via R ei 1.3-3 depending on eiPack 0.2-2",
            "nls": "Rosen NLS 2x2 unadjusted deterministic benchmark",
        },
        "mathematical_identity_krt_vs_r": False,
        "nls_has_uncertainty_interval": False,
        "professor_density_family": {
            "periods": [1962, 1986, 2022],
            "figures": ["joint_equal_communes", "joint_population_weighted", "marginal_group_weighted"],
            "coverage": {
                method: sorted(frame["scenario_id"].unique().tolist())
                for method, frame in density_metadata.groupby("method", sort=True)
            },
        },
        "row_counts": row_counts,
        "sources": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": file_sha256(path),
            }
            for path in source_paths
        ],
        "outputs": [
            {
                "path": path.relative_to(output).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
            for path in sorted(created_files)
        ],
        "validation": {
            "expected_aggregate_rows_per_complete_method": 156,
            "expected_commune_rows_per_complete_stochastic_method": 104000,
            "actual_r_aggregate_rows": row_counts["h0a_h1_r_eipack_aggregate.parquet"],
            "actual_r_commune_rows": row_counts["h0a_h1_r_eipack_commune.parquet"],
            "pair_rows": 52,
            "density_bandwidth_rows": len(density_metadata),
            "join_validation": "one_to_one",
            "status": "pass" if r_complete else "partial_r_h1_pending",
        },
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def build(output: Path = DEFAULT_OUTPUT, *, allow_partial_r: bool = False) -> dict[str, object]:
    output = output.resolve()
    tables = output / "tables"
    figures = output / "figures"
    tables.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)
    _style()

    krt_aggregate, krt_commune = _load_krt()
    nls_aggregate, nls_raw = _load_nls()
    r_aggregate, r_commune = _load_r_eipack(allow_partial=allow_partial_r)
    r_complete = len(r_aggregate) == 156 and len(r_commune) == 104_000
    comparison = _comparison(krt_aggregate, nls_aggregate, r_aggregate)
    summary = _method_summary(comparison)
    diagnostics = _pair_diagnostics(krt_aggregate, nls_aggregate, r_aggregate)
    density_created, density_metadata = _plot_professor_density_family(
        krt_commune, r_commune, figures
    )

    table_frames = {
        "h0a_h1_krt_aggregate.parquet": krt_aggregate,
        "h0a_h1_krt_commune.parquet": krt_commune,
        "h0a_h1_nls_estimates.parquet": nls_raw,
        "h0a_h1_nls_aggregate.parquet": nls_aggregate,
        "h0a_h1_r_eipack_aggregate.parquet": r_aggregate,
        "h0a_h1_r_eipack_commune.parquet": r_commune,
        "h0a_h1_method_comparison_aggregate.parquet": comparison,
        "h0a_h1_method_summary.parquet": summary,
        "h0a_h1_pair_diagnostics.parquet": diagnostics,
        "h0a_h1_density_bandwidths.parquet": density_metadata,
    }
    created: list[Path] = list(density_created)
    for name, frame in table_frames.items():
        path = tables / name
        frame.to_parquet(path, index=False)
        created.append(path)
    summary_csv = tables / "h0a_h1_method_summary.csv"
    summary.to_csv(summary_csv, index=False, encoding="utf-8-sig")
    created.append(summary_csv)

    created.extend(_plot_scenario_trajectories(comparison, "H0A", figures))
    created.extend(_plot_scenario_trajectories(comparison, "H1", figures))
    created.extend(_plot_contrasts(comparison, figures))
    created.extend(_plot_method_scatter(comparison, figures))
    created.extend(_plot_contrast_differences(comparison, figures))
    created.extend(_plot_diagnostics(diagnostics, figures))

    chart_map = figures / "CHART_MAP.csv"
    _write_chart_map(chart_map, density_metadata)
    created.append(chart_map)
    readme = output / "README.md"
    readme.write_text(
        _readme_text(
            summary,
            density_metadata,
            r_complete=r_complete,
            r_aggregate_rows=len(r_aggregate),
            r_commune_rows=len(r_commune),
        ),
        encoding="utf-8",
    )
    created.append(readme)
    manifest = _write_manifest(
        output,
        created,
        (KRT_AGGREGATE, KRT_COMMUNE, NLS_RESULTS, R_AGGREGATE, R_COMMUNE),
        {name: len(frame) for name, frame in table_frames.items()},
        r_complete,
        density_metadata,
    )
    return {
        "status": "complete" if r_complete else "partial_r_h1_pending",
        "output": str(output),
        "tables": len(table_frames),
        "figure_files": len([path for path in created if path.suffix in {".png", ".svg"}]),
        "manifest": str(manifest),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build H0A/H1 Parquet tables and KRT/R eiPack/NLS comparison figures."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--allow-partial-r", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            build(args.output, allow_partial_r=args.allow_partial_r),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
