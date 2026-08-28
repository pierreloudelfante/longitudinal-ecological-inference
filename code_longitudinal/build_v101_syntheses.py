from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .finalize_longitudinal import _build_krt_aggregate, _build_krt_commune
from .identification_v2 import tomography_bounds
from .paths import PANEL_DIR, ROOT, RUNS_DIR
from .prepare_inputs import x_columns, y_columns
from .release_v1_0_1_audit import build_data_dictionary, rebuild_commune_metadata
from .spec_registry import SCENARIO_BY_ID
from .utils import file_sha256


RELEASE_ROOT = ROOT / "work" / "longitudinal_2000_v1.0.1_H0A_H1_candidate"
RESULT_DIR = RELEASE_ROOT / "01_resultats_python"
SYNTHESIS_DIR = RELEASE_ROOT / "02_syntheses"
AUDIT_DIR = RELEASE_ROOT / "03_panel_et_audit"
FIGURE_DIR = RELEASE_ROOT / "04_figures_essentielles"
COMPARISON_DIR = RELEASE_ROOT / "02_comparaison_python_r"
CANONICAL_PANEL_ID = "longitudinal_2000_v1__strict_nested_3000__seed_20260803"


def _ensure_dirs() -> None:
    for path in (RESULT_DIR, SYNTHESIS_DIR, AUDIT_DIR, FIGURE_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _selected_runs() -> list[tuple[Path, dict[str, Any]]]:
    selection = pd.read_csv(SYNTHESIS_DIR / "canonical_run_selection.csv", dtype="string")
    if len(selection) != 52 or selection[["election_id", "scenario_id"]].duplicated().any():
        raise AssertionError("canonical selection must contain exactly 52 unique KRT pairs")
    runs: list[tuple[Path, dict[str, Any]]] = []
    for row in selection.itertuples(index=False):
        run_dir = RUNS_DIR / row.run_id
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(manifest_path)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "success":
            raise AssertionError(f"selected KRT run is not successful: {row.run_id}")
        params = manifest.get("parameters", {})
        if params.get("election_id") != row.election_id or params.get("scenario_id") != row.scenario_id:
            raise AssertionError(f"selected run metadata mismatch: {row.run_id}")
        runs.append((run_dir, manifest))
    return runs


def refresh_canonical_krt_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    _ensure_dirs()
    panel_path = PANEL_DIR / "longitudinal_2000_v1.parquet"
    if file_sha256(panel_path) != "bde70c71660fce29610d7931461d8db6181dba874514a1866b63cf16a81cec4a":
        raise AssertionError("canonical panel hash changed")
    panel = pd.read_parquet(panel_path)
    panel["unit_id"] = panel["unit_id"].astype("string")
    runs = _selected_runs()
    commune = _build_krt_commune(runs, panel)
    aggregate = _build_krt_aggregate(runs)
    commune["panel_id"] = CANONICAL_PANEL_ID
    aggregate["panel_id"] = CANONICAL_PANEL_ID
    if len(commune) != 104000 or commune[["election_id", "scenario_id", "unit_id"]].duplicated().any():
        raise AssertionError("canonical KRT commune table must have 104,000 unique pair-unit rows")
    if len(aggregate) != 156 or aggregate[["election_id", "scenario_id", "estimand"]].duplicated().any():
        raise AssertionError("canonical KRT aggregate table must have 156 unique rows")
    commune.to_parquet(RESULT_DIR / "longitudinal_krt_commune.parquet", index=False)
    aggregate.to_parquet(RESULT_DIR / "longitudinal_krt_aggregate.parquet", index=False)
    provenance = pd.read_csv(AUDIT_DIR / "COVARIATE_PROVENANCE.csv")
    commune = rebuild_commune_metadata(provenance)
    commune["panel_id"] = CANONICAL_PANEL_ID
    commune.to_parquet(RESULT_DIR / "longitudinal_krt_commune.parquet", index=False)
    return commune, aggregate


def build_krt_nls_comparison() -> pd.DataFrame:
    krt = pd.read_parquet(RESULT_DIR / "longitudinal_krt_aggregate.parquet")
    nls = pd.read_parquet(RESULT_DIR / "longitudinal_nls.parquet")
    krt = krt.loc[
        krt["scenario_id"].isin(["H0A", "H1"]) & krt["estimand"].eq("b_1_minus_b_2")
    ].copy()
    nls_rows: list[dict[str, Any]] = []
    for (election_id, scenario_id), part in nls.loc[nls["scenario_id"].isin(["H0A", "H1"])].groupby(
        ["election_id", "scenario_id"], sort=False
    ):
        scenario = SCENARIO_BY_ID[scenario_id]
        target_vote = scenario.vote_categories[0]
        cells = part.loc[
            part["estimand_type"].eq("cell_probability") & part["vote_category"].eq(target_vote)
        ].set_index("social_group")
        if not {"target_group", "complement_group"}.issubset(cells.index):
            raise AssertionError(f"missing NLS 2x2 cells for {election_id}/{scenario_id}")
        nls_rows.append(
            {
                "election_id": election_id,
                "scenario_id": scenario_id,
                "nls_run_id": str(cells.iloc[0]["run_id"]),
                "nls_target_vote": target_vote,
                "nls_beta1": float(cells.loc["target_group", "estimate"]),
                "nls_beta2": float(cells.loc["complement_group", "estimate"]),
                "nls_contrast": float(
                    cells.loc["target_group", "estimate"] - cells.loc["complement_group", "estimate"]
                ),
                "nls_diagnostic_status": str(cells.iloc[0]["diagnostic_status"]),
            }
        )
    nls_contrast = pd.DataFrame(nls_rows)
    result = krt.rename(
        columns={
            "run_id": "krt_run_id",
            "mean": "krt_contrast_mean",
            "q025": "krt_contrast_q025",
            "q975": "krt_contrast_q975",
        }
    ).merge(nls_contrast, on=["election_id", "scenario_id"], how="left", validate="one_to_one")
    result["nls_minus_krt"] = result["nls_contrast"] - result["krt_contrast_mean"]
    result["nls_inside_krt_interval"] = result["nls_contrast"].between(
        result["krt_contrast_q025"], result["krt_contrast_q975"]
    )
    columns = [
        "panel_id", "election_id", "year", "scenario_id", "krt_run_id", "nls_run_id",
        "nls_target_vote", "krt_contrast_mean", "krt_contrast_q025", "krt_contrast_q975",
        "nls_beta1", "nls_beta2", "nls_contrast", "nls_minus_krt", "nls_inside_krt_interval",
        "mcmc_status", "identification_status", "nls_diagnostic_status",
    ]
    result = result.loc[:, columns].sort_values(["scenario_id", "year", "election_id"])
    if len(result) != 52:
        raise AssertionError("KRT-NLS comparison must contain exactly 52 election-scenario rows")
    result.to_csv(SYNTHESIS_DIR / "krt_nls_comparison_h0a_h1.csv", index=False, encoding="utf-8-sig")
    _plot_krt_nls(result)
    return result


def _plot_krt_nls(result: pd.DataFrame) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(15, 10), constrained_layout=True)
    colors = {"H0A": "#4c78a8", "H1": "#e45756"}
    for axis, scenario_id in zip(axes, ("H0A", "H1")):
        part = result.loc[result["scenario_id"].eq(scenario_id)].copy().reset_index(drop=True)
        x = np.arange(len(part))
        axis.errorbar(
            x,
            part["krt_contrast_mean"],
            yerr=np.vstack(
                [
                    part["krt_contrast_mean"] - part["krt_contrast_q025"],
                    part["krt_contrast_q975"] - part["krt_contrast_mean"],
                ]
            ),
            fmt="o",
            ms=4,
            color=colors[scenario_id],
            capsize=2,
            label="KRT (IC crédible 95 %)",
        )
        axis.scatter(x, part["nls_contrast"], marker="x", color="#222222", s=30, label="NLS (point)")
        axis.axhline(0, color="#777777", lw=0.8)
        labels = [f"{int(row.year)} {'L' if str(row.election_id).startswith('leg_') else 'P'}" for row in part.itertuples()]
        axis.set_xticks(x, labels, rotation=60, ha="right")
        axis.set_ylabel("Contraste β₁ − β₂")
        axis.set_title(f"{scenario_id} — comparaison KRT et NLS par scrutin")
        axis.legend(loc="best", frameon=False)
    fig.suptitle("KRT–NLS : points NLS sans pseudo-intervalle postérieur", fontsize=14)
    fig.savefig(FIGURE_DIR / "krt_nls_comparison_h0a_h1.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def build_nls_replication_summary() -> pd.DataFrame:
    path = COMPARISON_DIR / "nls_python_r_comparison.parquet"
    comparison = pd.read_parquet(path)
    pairs = comparison[["election_id", "scenario_id"]].drop_duplicates()
    maximum = float(comparison["difference_r_minus_python"].abs().max())
    result = pd.DataFrame(
        [
            {
                "n_election_scenario_pairs": int(len(pairs)),
                "n_cell_estimates": int(len(comparison)),
                "maximum_absolute_difference": maximum,
                "acceptance_threshold": 1e-6,
                "replication_status": "pass" if maximum <= 1e-6 and len(pairs) == 270 else "fail",
                "scope": "270 existing NLS pairs; 22 RxC deferred to v1.1",
            }
        ]
    )
    if result.iloc[0]["replication_status"] != "pass":
        raise AssertionError("NLS R/Python replication does not satisfy the release criterion")
    result.to_csv(SYNTHESIS_DIR / "nls_python_r_replication_summary.csv", index=False, encoding="utf-8-sig")
    return result


def _canonical_model_ready(election_id: str, scenario_id: str) -> pd.DataFrame:
    selection = pd.read_csv(SYNTHESIS_DIR / "canonical_run_selection.csv", dtype="string")
    row = selection.loc[
        selection["election_id"].eq(election_id) & selection["scenario_id"].eq(scenario_id)
    ]
    if len(row) != 1:
        raise AssertionError(f"missing canonical run for {election_id}/{scenario_id}")
    manifest = json.loads((RUNS_DIR / row.iloc[0]["run_id"] / "manifest.json").read_text(encoding="utf-8"))
    prep = manifest.get("preparation_manifest", {})
    path = Path(str(prep.get("output", "")))
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_parquet(path)


def build_2022_identification_scatter() -> None:
    fig, axes = plt.subplots(2, 2, figsize=(13, 10), constrained_layout=True)
    for row, scenario_id in enumerate(("H0A", "H1")):
        frame = _canonical_model_ready("leg_2022_r1", scenario_id)
        scenario = SCENARIO_BY_ID[scenario_id]
        x = frame[x_columns(scenario)[0]].to_numpy(dtype=float)
        y = frame[y_columns(scenario)[0]].to_numpy(dtype=float) / frame["N_g"].to_numpy(dtype=float)
        bounds = tomography_bounds(x, y)
        width = np.maximum(bounds["b1_width"], bounds["b2_width"])
        scatter = axes[row, 0].scatter(x, y, c=width, cmap="magma", s=9, alpha=0.7, rasterized=True)
        fig.colorbar(scatter, ax=axes[row, 0], label="Largeur maximale des bornes")
        axes[row, 0].set_title(f"{scenario_id} 2022 — couleur = largeur des bornes")
        scatter2 = axes[row, 1].scatter(x, y, c=x, cmap="viridis", s=9, alpha=0.7, rasterized=True)
        fig.colorbar(scatter2, ax=axes[row, 1], label="Part du groupe cible")
        axes[row, 1].set_title(f"{scenario_id} 2022 — couleur = part du groupe cible")
        for axis in axes[row]:
            axis.set_xlabel("Part ouvriers + employés")
            axis.set_ylabel("Part électorale cible observée")
            axis.set_xlim(-0.02, 1.02)
            axis.set_ylim(-0.02, 1.02)
    fig.suptitle("Nuages bruts 2022 — identification écologique, distincte de la convergence MCMC", fontsize=14)
    fig.savefig(FIGURE_DIR / "raw_scatter_2022_bounds_and_target_share.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def update_dictionary() -> pd.DataFrame:
    extras = [
        AUDIT_DIR / "coverage_by_election_department.csv",
        AUDIT_DIR / "department54_pre1988_rows.csv",
        AUDIT_DIR / "rxc_ineligible_audit.csv",
        AUDIT_DIR / "HARMONISATION_POLITIQUE.csv",
        AUDIT_DIR / "COVARIATE_PROVENANCE.csv",
        AUDIT_DIR / "foreign_share_source_validation.csv",
        SYNTHESIS_DIR / "canonical_run_selection.csv",
        SYNTHESIS_DIR / "h1_panel_sensitivity.csv",
        SYNTHESIS_DIR / "h1_panel_sensitivity_nls_diagnostics.csv",
        SYNTHESIS_DIR / "targeted_mcmc_reruns.csv",
        SYNTHESIS_DIR / "krt_nls_comparison_h0a_h1.csv",
        SYNTHESIS_DIR / "nls_python_r_replication_summary.csv",
    ]
    return build_data_dictionary([path for path in extras if path.exists()])


def main() -> None:
    parser = argparse.ArgumentParser(description="Build v1.0.1 canonical syntheses and essential figures.")
    parser.add_argument("stage", choices=("refresh-krt", "comparisons", "figures", "dictionary", "all"))
    args = parser.parse_args()
    if args.stage in {"refresh-krt", "all"}:
        commune, aggregate = refresh_canonical_krt_tables()
        print(json.dumps({"commune_rows": len(commune), "aggregate_rows": len(aggregate)}))
    if args.stage in {"comparisons", "all"}:
        print(build_krt_nls_comparison().to_json(orient="records"))
        print(build_nls_replication_summary().to_json(orient="records"))
    if args.stage in {"figures", "all"}:
        build_2022_identification_scatter()
        print(json.dumps({"figure": "raw_scatter_2022_bounds_and_target_share.png"}))
    if args.stage in {"dictionary", "all"}:
        print(json.dumps({"dictionary_rows": len(update_dictionary())}))


if __name__ == "__main__":
    main()
