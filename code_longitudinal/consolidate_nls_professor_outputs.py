"""Consolidate the twelve priority NLS fits and build professor-facing figures."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .paths import FIGURE_DIR, OUTPUT_DIR, ensure_runtime_dirs


NLS_DIR = OUTPUT_DIR / "v2" / "nls_priority"
DATA_DIR = OUTPUT_DIR / "v2" / "priority_3000_final"
FIG_DIR = FIGURE_DIR / "v2" / "priority_3000_final"

ESTIMATES_PATH = DATA_DIR / "nls_estimates_3000_v1.csv"
CONTRASTS_PATH = DATA_DIR / "nls_contrasts_3000_v1.csv"
DIAGNOSTICS_PATH = DATA_DIR / "nls_model_diagnostics_3000_v1.csv"
COMPARISON_PATH = DATA_DIR / "nls_krt_comparison_3000_v1.csv"
MANIFEST_PATH = DATA_DIR / "nls_summary_manifest_3000_v1.json"
CONTRAST_FIGURE = FIG_DIR / "nls_contrasts_3000_v1.png"
COMPARISON_FIGURE = FIG_DIR / "nls_krt_comparison_3000_v1.png"

SCENARIO_DEFINITIONS = {
    "H0A": {
        "event": "abstention",
        "group_1": "target_group",
        "group_2": "complement_group",
        "group_1_label": "ouvriers + employés",
        "group_2_label": "autres CSP",
        "event_label": "abstention parmi les inscrits",
    },
    "H1": {
        "event": "gauche",
        "group_1": "target_group",
        "group_2": "complement_group",
        "group_1_label": "ouvriers + employés",
        "group_2_label": "autres CSP",
        "event_label": "vote à gauche parmi les exprimés",
    },
    "H2": {
        "event": "gauche",
        "group_1": "target_group",
        "group_2": "complement_group",
        "group_1_label": "ouvriers",
        "group_2_label": "autres CSP",
        "event_label": "vote à gauche parmi les exprimés",
    },
    "H4": {
        "event": "droite",
        "group_1": "agri_indp",
        "group_2": "salaries",
        "group_1_label": "agriculteurs + indépendants",
        "group_2_label": "salariés",
        "event_label": "vote à droite parmi les exprimés",
    },
}


def _year(election_id: str) -> int:
    return int(election_id.split("_")[1])


def _attempt_dir(row: object) -> Path:
    attempt_id = Path(str(getattr(row, "attempt_manifest"))).parent.name
    return NLS_DIR / "runs" / str(getattr(row, "run_key"))[:16] / "attempts" / attempt_id


def _load_sources() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    progress = pd.read_csv(NLS_DIR / "progress.csv")
    expected = {
        (scenario, year)
        for scenario in SCENARIO_DEFINITIONS
        for year in (1962, 1986, 2022)
    }
    observed = {
        (str(row.scenario_id), _year(str(row.election_id)))
        for row in progress.itertuples()
    }
    if observed != expected or len(progress) != 12:
        raise AssertionError(f"unexpected NLS coverage: {sorted(observed)}")
    if not progress["status"].eq("success").all():
        raise AssertionError("not all NLS fits succeeded")
    if not progress["diagnostic_status"].eq("pass").all():
        raise AssertionError("not all NLS fits have pass diagnostics")
    if not progress["n_communes"].eq(3000).all():
        raise AssertionError("NLS fits do not all use exactly 3 000 communes")

    estimates_parts: list[pd.DataFrame] = []
    diagnostics_parts: list[pd.DataFrame] = []
    start_parts: list[pd.DataFrame] = []
    settings: dict[str, object] | None = None
    for row in progress.itertuples():
        attempt_dir = _attempt_dir(row)
        required = [
            attempt_dir / "estimates.csv",
            attempt_dir / "model_diagnostics.csv",
            attempt_dir / "start_diagnostics.csv",
            attempt_dir / "manifest.json",
        ]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise FileNotFoundError(f"missing NLS artifacts: {missing}")

        manifest = json.loads(required[3].read_text(encoding="utf-8"))
        current_settings = manifest["nls_settings"]
        if settings is None:
            settings = current_settings
        elif settings != current_settings:
            raise AssertionError("NLS settings differ across the twelve fits")

        estimates = pd.read_csv(required[0])
        estimates.insert(4, "year", _year(str(row.election_id)))
        estimates_parts.append(estimates)

        diagnostic = pd.read_csv(required[1])
        diagnostic.insert(3, "year", _year(str(row.election_id)))
        diagnostics_parts.append(diagnostic)

        starts = pd.read_csv(required[2])
        starts.insert(2, "election_id", str(row.election_id))
        starts.insert(3, "scenario_id", str(row.scenario_id))
        starts.insert(4, "year", _year(str(row.election_id)))
        start_parts.append(starts)

    assert settings is not None
    return (
        pd.concat(estimates_parts, ignore_index=True),
        pd.concat(diagnostics_parts, ignore_index=True),
        pd.concat(start_parts, ignore_index=True),
        settings,
    )


def _contrasts(estimates: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (scenario, year), frame in estimates.groupby(["scenario_id", "year"], sort=True):
        definition = SCENARIO_DEFINITIONS[str(scenario)]
        event = frame.loc[frame["vote_category"].eq(definition["event"])]
        group_1 = event.loc[event["social_group"].eq(definition["group_1"]), "estimate"]
        group_2 = event.loc[event["social_group"].eq(definition["group_2"]), "estimate"]
        if len(group_1) != 1 or len(group_2) != 1:
            raise AssertionError(f"NLS estimand rows not unique for {scenario}-{year}")
        estimate_1 = float(group_1.iloc[0])
        estimate_2 = float(group_2.iloc[0])
        rows.append(
            {
                "scenario_id": scenario,
                "year": int(year),
                "event": definition["event"],
                "event_label": definition["event_label"],
                "group_1": definition["group_1"],
                "group_1_label": definition["group_1_label"],
                "group_1_estimate": estimate_1,
                "group_2": definition["group_2"],
                "group_2_label": definition["group_2_label"],
                "group_2_estimate": estimate_2,
                "contrast_group_1_minus_group_2": estimate_1 - estimate_2,
                "n_communes": int(event["n_communes"].iloc[0]),
                "N_total": int(event["N_total"].iloc[0]),
                "diagnostic_status": str(event["diagnostic_status"].iloc[0]),
            }
        )
    result = pd.DataFrame(rows).sort_values(["scenario_id", "year"]).reset_index(drop=True)
    if len(result) != 12:
        raise AssertionError("expected twelve NLS contrasts")
    return result


def _diagnostics(diagnostics: pd.DataFrame, starts: pd.DataFrame) -> pd.DataFrame:
    start_summary = (
        starts.groupby(["election_id", "scenario_id", "year"], as_index=False)
        .agg(
            n_starts=("start_index", "size"),
            n_successful_starts=("success", "sum"),
            max_abs_coefficient_difference_from_best=(
                "max_abs_coefficient_difference_from_best",
                "max",
            ),
            max_abs_prediction_difference_from_best=(
                "max_abs_prediction_difference_from_best",
                "max",
            ),
        )
    )
    columns = [
        "election_id",
        "scenario_id",
        "year",
        "n_communes",
        "N_total",
        "elapsed_seconds",
        "objective_sse_unweighted",
        "optimizer_success",
        "nfev",
        "optimality",
        "n_parameters",
        "diagnostic_status",
        "sandwich_rank_meat",
        "sandwich_rank_info",
        "sandwich_condition_meat",
        "sandwich_condition_info",
        "bread_rank",
        "bread_condition",
    ]
    result = diagnostics[columns].merge(
        start_summary,
        on=["election_id", "scenario_id", "year"],
        validate="one_to_one",
    )
    if not result["optimizer_success"].all() or not result["diagnostic_status"].eq("pass").all():
        raise AssertionError("NLS diagnostic consolidation failed")
    if not result["n_starts"].eq(result["n_successful_starts"]).all():
        raise AssertionError("at least one NLS multi-start optimization failed")
    return result.sort_values(["scenario_id", "year"]).reset_index(drop=True)


def _comparison(contrasts: pd.DataFrame) -> pd.DataFrame:
    krt = pd.read_csv(DATA_DIR / "within_period_contrasts_3000_v1.csv")
    krt = krt.loc[krt["scenario_id"].isin(["H0A", "H1"]), [
        "scenario_id", "year", "estimate", "lower", "upper"
    ]].rename(
        columns={
            "estimate": "krt_estimate",
            "lower": "krt_lower_95",
            "upper": "krt_upper_95",
        }
    )
    nls = contrasts.loc[contrasts["scenario_id"].isin(["H0A", "H1"]), [
        "scenario_id", "year", "contrast_group_1_minus_group_2"
    ]].rename(columns={"contrast_group_1_minus_group_2": "nls_estimate"})
    result = krt.merge(nls, on=["scenario_id", "year"], validate="one_to_one")
    result["nls_minus_krt"] = result["nls_estimate"] - result["krt_estimate"]
    result["same_sign"] = np.sign(result["nls_estimate"]) == np.sign(result["krt_estimate"])
    return result.sort_values(["scenario_id", "year"]).reset_index(drop=True)


def _plot_contrasts(contrasts: pd.DataFrame) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    blue = "#315C8C"
    open_blue = "#EAF0F6"
    ink = "#20262E"
    grid = "#DCE3EA"
    years = [1962, 1986, 2022]
    fig, axes = plt.subplots(2, 2, figsize=(11.6, 7.4), sharey=True)
    for axis, scenario in zip(axes.flat, SCENARIO_DEFINITIONS):
        frame = contrasts.loc[contrasts["scenario_id"].eq(scenario)].set_index("year")
        values = 100 * frame.loc[years, "contrast_group_1_minus_group_2"].to_numpy(float)
        positions = np.arange(len(years))
        bars = axis.bar(
            positions,
            values,
            width=0.58,
            color=[blue if value >= 0 else open_blue for value in values],
            edgecolor=blue,
            linewidth=1.1,
        )
        for bar, value in zip(bars, values):
            if value < 0:
                bar.set_hatch("//")
            offset = 0.7 if value >= 0 else -0.9
            axis.text(
                bar.get_x() + bar.get_width() / 2,
                value + offset,
                f"{value:+.1f}",
                ha="center",
                va="bottom" if value >= 0 else "top",
                fontsize=9,
                color=ink,
            )
        definition = SCENARIO_DEFINITIONS[scenario]
        axis.set_title(
            f"{scenario} - {definition['group_1_label']} vs {definition['group_2_label']}",
            fontsize=10.5,
            color=ink,
            pad=8,
        )
        axis.set_xticks(positions, years)
        axis.axhline(0, color=ink, linewidth=0.8)
        axis.grid(axis="y", color=grid, linewidth=0.7)
        axis.set_axisbelow(True)
        axis.spines[["top", "right"]].set_visible(False)
        axis.set_ylim(-12, 12)
    axes[0, 0].set_ylabel("Contraste NLS (points)")
    axes[1, 0].set_ylabel("Contraste NLS (points)")
    fig.suptitle("Contrastes NLS", fontsize=15, color=ink, y=0.98)
    fig.tight_layout(rect=(0.04, 0.04, 0.98, 0.91))
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(CONTRAST_FIGURE, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _plot_comparison(comparison: pd.DataFrame) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    blue = "#315C8C"
    gold = "#D69E2E"
    ink = "#20262E"
    grid = "#DCE3EA"
    years = [1962, 1986, 2022]
    positions = np.arange(len(years))
    fig, axes = plt.subplots(1, 2, figsize=(11.6, 4.8), sharey=True)
    for axis, scenario in zip(axes, ("H0A", "H1")):
        frame = comparison.loc[comparison["scenario_id"].eq(scenario)].set_index("year").loc[years]
        krt = 100 * frame["krt_estimate"].to_numpy(float)
        lower = 100 * frame["krt_lower_95"].to_numpy(float)
        upper = 100 * frame["krt_upper_95"].to_numpy(float)
        nls = 100 * frame["nls_estimate"].to_numpy(float)
        axis.errorbar(
            positions - 0.07,
            krt,
            yerr=np.vstack([krt - lower, upper - krt]),
            fmt="o",
            color=blue,
            ecolor=blue,
            capsize=4,
            linewidth=1.4,
            markersize=6,
            label="KRT (ICr 95 %)",
        )
        axis.scatter(
            positions + 0.07,
            nls,
            marker="D",
            s=45,
            facecolor="white",
            edgecolor=gold,
            linewidth=1.7,
            label="NLS (point)",
            zorder=3,
        )
        for x, value in zip(positions + 0.07, nls):
            axis.text(x, value + 1.0, f"{value:+.1f}", ha="center", fontsize=8.5, color=gold)
        axis.set_title(f"{scenario} - contraste groupe 1 moins groupe 2", fontsize=11, color=ink)
        axis.set_xticks(positions, years)
        axis.axhline(0, color=ink, linewidth=0.8)
        axis.grid(axis="y", color=grid, linewidth=0.7)
        axis.set_axisbelow(True)
        axis.spines[["top", "right"]].set_visible(False)
        axis.set_ylim(-17, 23)
    axes[0].set_ylabel("Contraste (points de pourcentage)")
    axes[0].legend(frameon=False, loc="upper left")
    fig.suptitle("Contrastes KRT et NLS", fontsize=15, color=ink, y=0.98)
    fig.tight_layout(rect=(0.04, 0.04, 0.98, 0.90))
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(COMPARISON_FIGURE, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def consolidate_nls_professor_outputs() -> dict[str, object]:
    ensure_runtime_dirs()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    estimates, diagnostics_source, starts, settings = _load_sources()
    contrasts = _contrasts(estimates)
    diagnostics = _diagnostics(diagnostics_source, starts)
    comparison = _comparison(contrasts)

    estimate_columns = [
        "election_id", "scenario_id", "year", "model_key", "social_group",
        "vote_category", "estimate", "n_communes", "N_total", "diagnostic_status",
    ]
    estimates[estimate_columns].sort_values(
        ["scenario_id", "year", "social_group", "vote_category"]
    ).to_csv(ESTIMATES_PATH, index=False, float_format="%.12g")
    contrasts.to_csv(CONTRASTS_PATH, index=False, float_format="%.12g")
    diagnostics.to_csv(DIAGNOSTICS_PATH, index=False, float_format="%.12g")
    comparison.to_csv(COMPARISON_PATH, index=False, float_format="%.12g")

    manifest = {
        "schema_version": "nls_professor_summary_v1.0",
        "status": "success",
        "scope": "H0A, H1, H2 and H4 for 1962, 1986 and 2022",
        "model_key": "rosen_nls_2x2_unadjusted",
        "panel": {
            "version": "panel_3000_common_1962_1986_2022_v2",
            "n_communes": 3000,
            "sha256": "d70810a1add048d4823274e182f3adf8735d6f881bd32564a550c78988e8cd3f",
        },
        "fit_count": 12,
        "fit_status_counts": {"success": 12},
        "diagnostic_status_counts": {"pass": 12},
        "nls_settings": settings,
        "uncertainty_note": (
            "The professor summary reports NLS point estimates. No confidence interval "
            "for the group contrast is claimed from these exported artifacts."
        ),
        "outputs": [
            ESTIMATES_PATH.name,
            CONTRASTS_PATH.name,
            DIAGNOSTICS_PATH.name,
            COMPARISON_PATH.name,
            CONTRAST_FIGURE.name,
            COMPARISON_FIGURE.name,
        ],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _plot_contrasts(contrasts)
    _plot_comparison(comparison)

    return {
        "fits": 12,
        "diagnostics_pass": int(diagnostics["diagnostic_status"].eq("pass").sum()),
        "same_sign_krt_nls": int(comparison["same_sign"].sum()),
        "outputs": [str(path) for path in (
            ESTIMATES_PATH,
            CONTRASTS_PATH,
            DIAGNOSTICS_PATH,
            COMPARISON_PATH,
            MANIFEST_PATH,
            CONTRAST_FIGURE,
            COMPARISON_FIGURE,
        )],
    }


if __name__ == "__main__":
    print(json.dumps(consolidate_nls_professor_outputs(), ensure_ascii=False, indent=2))
