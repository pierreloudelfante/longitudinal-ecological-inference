from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .paths import ROOT
from .spec_registry import ELECTIONS, SCENARIO_BY_ID, scenario_is_allowed


SOURCE_ROOT = ROOT / "outputs" / "longitudinal_2000_v1" / "production"
CANDIDATE_ROOT = SOURCE_ROOT / "all_2x2_candidate"
OUTPUT_ROOT = ROOT / "work" / "python_longitudinal_outputs_current_20260827"
SCENARIOS = ("H0A", "H1", "H0B", "H0C", "H2", "H3", "H4", "H5", "H6", "H7")
EXPECTED = {scenario: (16 if scenario in {"H6", "H7"} else 26) for scenario in SCENARIOS}
LABELS = {
    "H0A": "ouvriers-employes x abstention",
    "H1": "ouvriers-employes x gauche",
    "H0B": "ouvriers x abstention",
    "H0C": "employes x abstention",
    "H2": "ouvriers x gauche",
    "H3": "employes x gauche",
    "H4": "agriculteurs-independants x droite",
    "H5": "cadres x centre",
    "H6": "ouvriers x FN-RN",
    "H7": "employes x FN-RN",
}
FAMILY_COLORS = {"legislative": "#2F5DA8", "presidential": "#C03A7A"}
FAMILY_LABELS = {"legislative": "Legislatives", "presidential": "Presidentielles"}
ESTIMAND_ORDER = ("b_1", "b_2", "b_1_minus_b_2")
ESTIMAND_LABELS = {
    "b_1": r"$\beta_1$ — groupe cible",
    "b_2": r"$\beta_2$ — groupe complementaire",
    "b_1_minus_b_2": r"$\beta_1-\beta_2$ — contraste",
}


def _expected_elections(scenario_id: str):
    scenario = SCENARIO_BY_ID[scenario_id]
    return tuple(item for item in ELECTIONS if scenario_is_allowed(scenario, item))


def _configure_complete_time_axis(axis: plt.Axes, scenario_id: str) -> None:
    years = sorted({item.year for item in _expected_elections(scenario_id)})
    axis.set_xlim(min(years) - 1.5, max(years) + 1.5)
    axis.set_xticks(years)
    axis.tick_params(axis="x", labelrotation=45, labelsize=8)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _save_figure(fig: plt.Figure, directory: Path, stem: str) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = [directory / f"{stem}.png", directory / f"{stem}.svg"]
    fig.savefig(paths[0], dpi=190, bbox_inches="tight", facecolor="white")
    fig.savefig(paths[1], bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return paths


def _election_family(values: pd.Series) -> pd.Series:
    return np.where(values.astype(str).str.startswith("leg_"), "legislative", "presidential")


def _nls_estimands(nls: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    keys = ["panel_id", "election_id", "year", "round", "scenario_id"]
    for key, group in nls.groupby(keys, sort=False):
        contrast = group.loc[group["estimand_type"].eq("group_contrast")]
        if len(contrast) != 1:
            continue
        target_vote = contrast.iloc[0]["vote_category"]
        contrast_group = str(contrast.iloc[0]["social_group"])
        if "_minus_" not in contrast_group:
            continue
        target_group, complement_group = contrast_group.split("_minus_", maxsplit=1)
        target = group.loc[
            group["estimand_type"].eq("cell_probability")
            & group["social_group"].eq(target_group)
            & group["vote_category"].eq(target_vote)
        ]
        complement = group.loc[
            group["estimand_type"].eq("cell_probability")
            & group["social_group"].eq(complement_group)
            & group["vote_category"].eq(target_vote)
        ]
        if len(target) != 1 or len(complement) != 1:
            continue
        base = dict(zip(keys, key))
        for estimand, source in (
            ("b_1", target.iloc[0]),
            ("b_2", complement.iloc[0]),
            ("b_1_minus_b_2", contrast.iloc[0]),
        ):
            rows.append(
                {
                    **base,
                    "estimand": estimand,
                    "nls_estimate": float(source["estimate"]),
                    "nls_diagnostic_status": source.get("diagnostic_status"),
                    "nls_fit_status": source.get("fit_status"),
                    "nls_objective": source.get("objective"),
                    "nls_boundary_estimate": source.get("boundary_estimate"),
                }
            )
    return pd.DataFrame(rows)


def _trajectory_figure(
    aggregate: pd.DataFrame,
    scenario_id: str,
    completed: int,
    expected: int,
) -> plt.Figure:
    frame = aggregate.copy()
    frame["family"] = _election_family(frame["election_id"])
    fig, axes = plt.subplots(3, 1, figsize=(12.5, 12.0), sharex=False)
    for axis, estimand in zip(axes, ESTIMAND_ORDER):
        subset = frame.loc[frame["estimand"].eq(estimand)]
        for family in ("legislative", "presidential"):
            values = subset.loc[subset["family"].eq(family)].sort_values(["year", "round"])
            if values.empty:
                continue
            axis.errorbar(
                values["year"],
                values["mean"],
                yerr=np.vstack(
                    [values["mean"] - values["q025"], values["q975"] - values["mean"]]
                ),
                color=FAMILY_COLORS[family],
                marker="o" if family == "legislative" else "s",
                markersize=4.5,
                linestyle="-" if completed == expected else "none",
                linewidth=1.6,
                capsize=2.2,
                label=FAMILY_LABELS[family],
            )
        if estimand == "b_1_minus_b_2":
            axis.axhline(0, color="#374151", linestyle="--", linewidth=1)
            axis.set_ylim(-1, 1)
        else:
            axis.set_ylim(0, 1)
        axis.set_ylabel("Probabilite")
        axis.set_title(ESTIMAND_LABELS[estimand], loc="left", fontsize=11)
        axis.grid(axis="y", color="#E5E7EB", linewidth=0.8)
        axis.spines[["top", "right"]].set_visible(False)
        _configure_complete_time_axis(axis, scenario_id)
    handles, labels = axes[0].get_legend_handles_labels()
    if handles:
        axes[0].legend(handles, labels, frameon=False, ncol=2, loc="upper right")
    axes[-1].set_xlabel("Annee du scrutin")
    status = "complet" if completed == expected else "partiel"
    fig.suptitle(
        f"{scenario_id} — trajectoires longitudinales KRT Python",
        fontsize=15,
        fontweight="bold",
        y=0.988,
    )
    fig.text(
        0.5,
        0.955,
        f"{LABELS[scenario_id]}; {completed}/{expected} scrutins ({status}); "
        "intervalles posterieurs 95 %; familles electorales separees",
        ha="center",
        fontsize=9.5,
        color="#4B5563",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.915))
    return fig


def _comparison_figure(
    comparison: pd.DataFrame,
    scenario_id: str,
    completed: int,
    expected: int,
) -> plt.Figure:
    frame = comparison.copy()
    frame["family"] = _election_family(frame["election_id"])
    fig, axes = plt.subplots(3, 1, figsize=(12.5, 12.0), sharex=False)
    for axis, estimand in zip(axes, ESTIMAND_ORDER):
        subset = frame.loc[frame["estimand"].eq(estimand)]
        for family in ("legislative", "presidential"):
            values = subset.loc[subset["family"].eq(family)].sort_values(["year", "round"])
            if values.empty:
                continue
            color = FAMILY_COLORS[family]
            axis.plot(
                values["year"], values["mean"], color=color, linewidth=1.8,
                linestyle="-" if completed == expected else "none",
                marker="o", markersize=4, label=f"KRT — {FAMILY_LABELS[family]}",
            )
            axis.plot(
                values["year"], values["nls_estimate"], color=color, linewidth=1.4,
                linestyle="--" if completed == expected else "none", marker="x", markersize=4,
                label=f"NLS — {FAMILY_LABELS[family]}",
            )
        if estimand == "b_1_minus_b_2":
            axis.axhline(0, color="#374151", linestyle=":", linewidth=1)
            axis.set_ylim(-1, 1)
        else:
            axis.set_ylim(0, 1)
        axis.set_ylabel("Estimation")
        axis.set_title(ESTIMAND_LABELS[estimand], loc="left", fontsize=11)
        axis.grid(axis="y", color="#E5E7EB", linewidth=0.8)
        axis.spines[["top", "right"]].set_visible(False)
        _configure_complete_time_axis(axis, scenario_id)
    handles, labels = axes[0].get_legend_handles_labels()
    if handles:
        unique = dict(zip(labels, handles))
        axes[0].legend(unique.values(), unique.keys(), frameon=False, ncol=2, fontsize=8.5)
    axes[-1].set_xlabel("Annee du scrutin")
    fig.suptitle(
        f"{scenario_id} — comparaison longitudinale KRT Python et NLS",
        fontsize=15,
        fontweight="bold",
        y=0.988,
    )
    fig.text(
        0.5,
        0.955,
        f"{completed}/{expected} scrutins KRT disponibles; NLS ponctuel, sans pseudo-intervalle",
        ha="center",
        fontsize=9.5,
        color="#4B5563",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.915))
    return fig


def _diagnostic_figure(selection: pd.DataFrame, scenario_id: str) -> plt.Figure:
    frame = selection.copy()
    frame["family"] = _election_family(frame["election_id"])
    frame["year"] = frame["election_id"].str.extract(r"_(\d{4})_").astype(int)
    status_order = ("pass", "caveat", "fail")
    colors = {"pass": "#2F5DA8", "caveat": "#C99700", "fail": "#C03A7A"}
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.8), sharey=True)
    for axis, family in zip(axes, ("legislative", "presidential")):
        values = frame.loc[frame["family"].eq(family)].sort_values("year")
        expected_years = [
            item.year
            for item in _expected_elections(scenario_id)
            if item.election_type == family
        ]
        completed_years = set(values["year"].astype(int))
        missing_years = [year for year in expected_years if year not in completed_years]
        for level, column, offset, marker in (
            ("MCMC", "mcmc_status", 0.12, "o"),
            ("Identification", "identification_status", -0.12, "s"),
        ):
            for status in status_order:
                subset = values.loc[values[column].eq(status)]
                axis.scatter(
                    subset["year"],
                    np.full(len(subset), 1 if level == "MCMC" else 0) + offset,
                    color=colors[status],
                    marker=marker,
                    s=42,
                    label=status if family == "legislative" and level == "MCMC" else None,
                )
        if missing_years:
            axis.scatter(
                missing_years,
                np.full(len(missing_years), -0.34),
                color="#9CA3AF",
                marker="x",
                s=30,
                label="non calcule" if family == "legislative" else None,
            )
        axis.set_title(FAMILY_LABELS[family])
        axis.set_yticks([0, 1], ["Identification", "MCMC"])
        axis.set_xlabel("Annee")
        axis.set_ylim(-0.5, 1.5)
        axis.set_xlim(min(expected_years) - 1.5, max(expected_years) + 1.5)
        axis.set_xticks(expected_years)
        axis.tick_params(axis="x", labelrotation=45, labelsize=8)
        axis.grid(axis="x", color="#E5E7EB", linewidth=0.8)
        axis.spines[["top", "right", "left"]].set_visible(False)
    handles, labels = axes[0].get_legend_handles_labels()
    axes[0].legend(handles, labels, frameon=False, ncol=3, loc="upper left")
    fig.suptitle(
        f"{scenario_id} — diagnostics disponibles par scrutin",
        fontsize=14,
        fontweight="bold",
    )
    fig.text(
        0.5,
        0.91,
        "Les diagnostics imparfaits sont conserves comme reserves et ne suppriment pas les sorties.",
        ha="center",
        fontsize=9.2,
        color="#4B5563",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    return fig


def main() -> None:
    commune = pd.read_parquet(CANDIDATE_ROOT / "longitudinal_krt_commune_240_candidate.parquet")
    aggregate = pd.read_parquet(CANDIDATE_ROOT / "longitudinal_krt_aggregate_240_candidate.parquet")
    selection = pd.read_csv(CANDIDATE_ROOT / "krt_240_candidate_selection.csv")
    nls_source = pd.read_parquet(
        SOURCE_ROOT / "rxc_nls_panel_extension_v11" / "longitudinal_nls_292_candidate.parquet"
    )
    nls = nls_source.loc[nls_source["scenario_id"].isin(SCENARIOS)].copy()
    nls_estimands = _nls_estimands(nls)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[dict[str, object]] = []
    coverage_rows: list[dict[str, object]] = []
    for scenario_id in SCENARIOS:
        scenario_dir = OUTPUT_ROOT / scenario_id
        tables_dir = scenario_dir / "tables"
        figures_dir = scenario_dir / "figures"
        tables_dir.mkdir(parents=True, exist_ok=True)
        figures_dir.mkdir(parents=True, exist_ok=True)

        scenario_commune = commune.loc[commune["scenario_id"].eq(scenario_id)].copy()
        scenario_aggregate = aggregate.loc[aggregate["scenario_id"].eq(scenario_id)].copy()
        scenario_selection = selection.loc[selection["scenario_id"].eq(scenario_id)].copy()
        scenario_nls = nls.loc[nls["scenario_id"].eq(scenario_id)].copy()
        scenario_nls_estimands = nls_estimands.loc[
            nls_estimands["scenario_id"].eq(scenario_id)
        ].copy()
        comparison = scenario_aggregate.merge(
            scenario_nls_estimands,
            on=["panel_id", "election_id", "year", "round", "scenario_id", "estimand"],
            how="left",
            validate="one_to_one",
        )
        if comparison["nls_estimate"].isna().any():
            raise AssertionError(f"{scenario_id} has unmatched KRT/NLS estimands")

        tables = {
            "krt_commune.parquet": scenario_commune,
            "krt_aggregate.parquet": scenario_aggregate,
            "krt_selection.parquet": scenario_selection,
            "nls_all_cells.parquet": scenario_nls,
            "krt_nls_comparison.parquet": comparison,
        }
        for name, frame in tables.items():
            frame.to_parquet(tables_dir / name, index=False)

        completed = len(scenario_selection)
        expected = EXPECTED[scenario_id]
        figure_paths: list[Path] = []
        figure_paths += _save_figure(
            _trajectory_figure(scenario_aggregate, scenario_id, completed, expected),
            figures_dir,
            f"{scenario_id}_krt_longitudinal_all_years",
        )
        figure_paths += _save_figure(
            _comparison_figure(comparison, scenario_id, completed, expected),
            figures_dir,
            f"{scenario_id}_krt_vs_nls_longitudinal_all_years",
        )
        figure_paths += _save_figure(
            _diagnostic_figure(scenario_selection, scenario_id),
            figures_dir,
            f"{scenario_id}_diagnostics_by_election",
        )

        files = sorted([path for path in tables_dir.iterdir() if path.is_file()] + figure_paths)
        scenario_manifest = {
            "schema_version": "python_longitudinal_scenario_outputs_v1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "scenario_id": scenario_id,
            "description": LABELS[scenario_id],
            "status": "complete" if completed == expected else "partial",
            "expected_pairs": expected,
            "completed_pairs": completed,
            "diagnostics_policy": "retain pass, caveat, and fail with explicit status",
            "commune_rows": len(scenario_commune),
            "aggregate_rows": len(scenario_aggregate),
            "nls_rows": len(scenario_nls),
            "comparison_rows": len(comparison),
            "files": [
                {
                    "path": path.relative_to(OUTPUT_ROOT).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
                for path in files
            ],
        }
        manifest_path = scenario_dir / "MANIFEST.json"
        manifest_path.write_text(
            json.dumps(scenario_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        manifest_rows.extend(
            {"scenario_id": scenario_id, **entry} for entry in scenario_manifest["files"]
        )
        coverage_rows.append(
            {
                "scenario_id": scenario_id,
                "description": LABELS[scenario_id],
                "expected_pairs": expected,
                "completed_pairs": completed,
                "missing_pairs": expected - completed,
                "status": scenario_manifest["status"],
                "mcmc_pass": int(scenario_selection["mcmc_status"].eq("pass").sum()),
                "mcmc_caveat": int(scenario_selection["mcmc_status"].eq("caveat").sum()),
                "mcmc_fail": int(scenario_selection["mcmc_status"].eq("fail").sum()),
            }
        )

    file_manifest = pd.DataFrame(manifest_rows)
    coverage = pd.DataFrame(coverage_rows)
    file_manifest.to_parquet(OUTPUT_ROOT / "FILE_MANIFEST.parquet", index=False)
    coverage.to_parquet(OUTPUT_ROOT / "COVERAGE.parquet", index=False)
    coverage.to_csv(OUTPUT_ROOT / "COVERAGE.csv", index=False)
    root_manifest = {
        "schema_version": "python_longitudinal_outputs_current_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "partial",
        "source_candidate_manifest": (
            CANDIDATE_ROOT / "krt_240_candidate_manifest.json"
        ).relative_to(ROOT).as_posix(),
        "selected_pairs": int(coverage["completed_pairs"].sum()),
        "expected_pairs": int(coverage["expected_pairs"].sum()),
        "complete_scenarios": coverage.loc[coverage["status"].eq("complete"), "scenario_id"].tolist(),
        "partial_scenarios": coverage.loc[coverage["status"].eq("partial"), "scenario_id"].tolist(),
        "diagnostics_policy": "diagnostic imperfections are retained and labeled",
        "output_root": OUTPUT_ROOT.relative_to(ROOT).as_posix(),
    }
    (OUTPUT_ROOT / "MANIFEST.json").write_text(
        json.dumps(root_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(root_manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
