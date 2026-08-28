from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde

from .paths import DOCS_DIR, FIGURE_DIR, OUTPUT_DIR, ROOT, RUNS_DIR, ensure_runtime_dirs
from .spec_registry import SCENARIO_BY_ID


AUDIT_PATH = OUTPUT_DIR / "priority_production_diagnostics.csv"
BEST_RUNS_PATH = OUTPUT_DIR / "priority_best_runs.csv"
ESTIMATES_PATH = OUTPUT_DIR / "priority_best_estimates.csv"
JOINT_BETA_PATH = OUTPUT_DIR / "priority_joint_beta_data.csv"
REPORT_PATH = DOCS_DIR / "PRIORITY_RESULTS_FOR_PROFESSOR.md"
CHART_MAP_PATH = DOCS_DIR / "PRIORITY_CHART_MAP.md"
FIGURE_PATH = FIGURE_DIR / "priority_production"
ZIP_PATH = ROOT / "deliverables" / "longitudinal_priority_results_clear.zip"
SHA_PATH = ZIP_PATH.with_suffix(".zip.sha256")

BLUE = "#315C8C"
GOLD = "#C6922B"
INK = "#20262E"
GREY = "#AAB2BD"
MODEL_KEY = "krt_beta_binomial"

SCENARIO_LABELS = {
    "H0A": "Abstention — ouvriers et employés vs autres CSP",
    "H1": "Vote à gauche — ouvriers et employés vs autres CSP",
    "H2": "Vote à gauche — ouvriers vs autres CSP",
    "H4": "Vote à droite — agriculteurs et indépendants vs salariés",
}

BETA_AXIS_LABELS = {
    "H0A": ("β₁ — ouvriers + employés", "β₂ — autres CSP"),
    "H1": ("β₁ — ouvriers + employés", "β₂ — autres CSP"),
    "H2": ("β₁ — ouvriers", "β₂ — autres CSP"),
    "H4": ("β₁ — agriculteurs + indépendants", "β₂ — salariés"),
}

JOINT_CMAP = LinearSegmentedColormap.from_list(
    "priority_joint_beta",
    ["#F7F9FB", "#D7E2EE", "#7D9DBC", BLUE, "#173A5E"],
)


def _num(value: object, default: float = np.nan) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _classification(row: pd.Series) -> str:
    if row["diagnostic_verdict"] == "pass":
        return "validé"
    if (
        _num(row.get("max_rhat")) <= 1.01
        and _num(row.get("min_ess_bulk")) >= 400
        and _num(row.get("min_ess_tail")) >= 400
        and _num(row.get("divergences")) == 0
        and _num(row.get("max_tree_depth_hits")) == 0
        and _num(row.get("min_bfmi")) >= 0.20
    ):
        return "avec réserve BFMI"
    return "exploratoire"


def select_best_runs() -> pd.DataFrame:
    audit = pd.read_csv(AUDIT_PATH)
    audit = audit.loc[
        audit["model_key"].eq(MODEL_KEY)
        & pd.to_numeric(audit["sample_size"], errors="coerce").eq(500)
        & audit["fit_status"].isin(["success", "skipped_existing_success"])
    ].copy()
    audit["pass_rank"] = audit["diagnostic_verdict"].eq("pass").astype(int)
    audit["draw_rank"] = pd.to_numeric(audit["draws"], errors="coerce").fillna(0)
    audit["bfmi_rank"] = pd.to_numeric(audit["min_bfmi"], errors="coerce").fillna(-1)
    audit = audit.sort_values(
        ["election_id", "scenario_id", "pass_rank", "draw_rank", "bfmi_rank"]
    ).drop_duplicates(["election_id", "scenario_id"], keep="last")
    audit["classification"] = audit.apply(_classification, axis=1)
    audit = audit.sort_values(["scenario_id", "election_id"]).drop(
        columns=["pass_rank", "draw_rank", "bfmi_rank"]
    )
    audit.to_csv(BEST_RUNS_PATH, index=False, encoding="utf-8-sig")
    return audit


def collect_estimates(best: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for row in best.itertuples():
        path = RUNS_DIR / str(row.run_id) / "longitudinal_estimates.csv"
        frame = pd.read_csv(path)
        frame["classification"] = row.classification
        frame["mcmc_draws"] = int(float(row.draws))
        frame["mcmc_tune"] = int(float(row.tune))
        frame["max_rhat"] = _num(row.max_rhat)
        frame["min_ess_bulk"] = _num(row.min_ess_bulk)
        frame["min_bfmi"] = _num(row.min_bfmi)
        frames.append(frame)
    estimates = pd.concat(frames, ignore_index=True)
    estimates.to_csv(ESTIMATES_PATH, index=False, encoding="utf-8-sig")
    return estimates


def collect_joint_beta_data(best: pd.DataFrame) -> pd.DataFrame:
    """Collect the commune-level posterior means used by the joint-density figures."""
    frames: list[pd.DataFrame] = []
    for row in best.itertuples():
        path = RUNS_DIR / str(row.run_id) / "commune_latent_summaries.parquet"
        latent = pd.read_parquet(path)
        frame = latent[
            [
                "run_id",
                "election_id",
                "scenario_id",
                "model_key",
                "unit_id",
                "sample_rank",
                "b1_mean",
                "b2_mean",
                "b1_weight",
                "b2_weight",
            ]
        ].copy()
        frame["classification"] = row.classification
        frame["year"] = frame["election_id"].str.extract(r"(\d{4})").astype(int)
        frame["sample_size"] = int(float(row.sample_size))
        frames.append(frame)
    joint = pd.concat(frames, ignore_index=True)
    joint.to_csv(JOINT_BETA_PATH, index=False, encoding="utf-8-sig")
    return joint


def _save(fig: plt.Figure, stem: str) -> tuple[Path, Path]:
    FIGURE_PATH.mkdir(parents=True, exist_ok=True)
    png = FIGURE_PATH / f"{stem}.png"
    svg = FIGURE_PATH / f"{stem}.svg"
    fig.savefig(png, dpi=180, bbox_inches="tight", facecolor="white")
    fig.savefig(svg, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return png, svg


def plot_canonical(estimates: pd.DataFrame, scenario_id: str) -> tuple[Path, Path]:
    scenario = SCENARIO_BY_ID[scenario_id]
    target_vote = scenario.vote_categories[0]
    data = estimates.loc[
        estimates["scenario_id"].eq(scenario_id)
        & estimates["vote_category"].eq(target_vote)
    ].copy()
    groups = list(scenario.social_groups)
    panel_labels = [label.split("—", 1)[1].strip() for label in BETA_AXIS_LABELS[scenario_id]]
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.2), sharey=True)
    for axis, group, color, panel_label in zip(
        axes, groups, (BLUE, GOLD), panel_labels, strict=True
    ):
        subset = data.loc[data["social_group"].eq(group)].sort_values("year")
        x = np.arange(len(subset))
        y = subset["estimate"].to_numpy(float)
        lower = subset["lower"].to_numpy(float)
        upper = subset["upper"].to_numpy(float)
        axis.errorbar(
            x,
            y,
            yerr=np.vstack([y - lower, upper - y]),
            fmt="o",
            ms=7,
            color=color,
            ecolor=color,
            capsize=4,
            lw=1.8,
        )
        axis.set_xticks(x, subset["year"].astype(int))
        axis.set_title(panel_label, color=INK, fontsize=11)
        axis.grid(axis="y", color="#E2E6EA", lw=0.8)
        axis.spines[["top", "right"]].set_visible(False)
        axis.set_ylim(0, 1)
    axes[0].set_ylabel(f"Probabilité estimée : {target_vote}")
    fig.suptitle(f"{scenario_id} — comparaison canonique 1962 / 1986 / 2022", color=INK, fontsize=14)
    fig.text(
        0.5,
        0.01,
        "Points : moyenne postérieure; barres : intervalle crédible à 95 %. "
        "Panel tiré fixe; n analytique=500/494/500.",
        ha="center",
        fontsize=9,
        color="#59636E",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.92))
    return _save(fig, f"canonical_{scenario_id}")


def plot_diagnostics(best: pd.DataFrame) -> tuple[Path, Path]:
    data = best.copy()
    fig, ax = plt.subplots(figsize=(9.5, 5.4))
    colors = data["classification"].map(
        {"validé": BLUE, "avec réserve BFMI": GOLD, "exploratoire": GREY}
    )
    ax.scatter(data["max_rhat"], data["min_ess_bulk"], c=colors, s=58, edgecolor=INK, linewidth=0.5)
    for row in data.itertuples():
        ax.annotate(f"{row.scenario_id}-{str(row.election_id)[4:8]}", (row.max_rhat, row.min_ess_bulk), xytext=(4, 4), textcoords="offset points", fontsize=8)
    ax.axvline(1.01, color=INK, ls="--", lw=1, label="seuil R-hat = 1,01")
    ax.axhline(400, color=INK, ls=":", lw=1, label="seuil ESS = 400")
    ax.set_xlabel("R-hat maximal")
    ax.set_ylabel("ESS bulk minimal")
    ax.set_title("Diagnostics MCMC des meilleurs runs KRT", color=INK, fontsize=14)
    ax.grid(color="#E2E6EA", lw=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    return _save(fig, "diagnostics_overview")


def plot_density_demo(best: pd.DataFrame) -> tuple[Path, Path]:
    row = best.loc[best["election_id"].eq("leg_2022_r1") & best["scenario_id"].eq("H0A")].iloc[0]
    latent = pd.read_parquet(RUNS_DIR / str(row["run_id"]) / "commune_latent_summaries.parquet")
    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    ax.hist(latent["b1_mean"], bins=28, density=True, alpha=0.55, color=BLUE, edgecolor="white", label="groupe cible")
    ax.hist(latent["b2_mean"], bins=28, density=True, alpha=0.50, color=GOLD, edgecolor="white", label="complément")
    ax.set_xlabel("Moyenne postérieure communale de l’abstention")
    ax.set_ylabel("Densité")
    ax.set_title("H0A en 2022 — distribution entre communes", color=INK, fontsize=14)
    ax.text(0.0, -0.16, "Chaque commune compte une fois; la hauteur est une densité, pas une probabilité.", transform=ax.transAxes, fontsize=9, color="#59636E")
    ax.grid(axis="y", color="#E2E6EA", lw=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False)
    fig.tight_layout()
    return _save(fig, "density_demo_H0A_2022")


def _joint_kde(points: pd.DataFrame, axis: np.ndarray) -> np.ndarray:
    values = np.vstack(
        [points["b1_mean"].to_numpy(dtype=float), points["b2_mean"].to_numpy(dtype=float)]
    )
    xx, yy = np.meshgrid(axis, axis)
    try:
        density = gaussian_kde(values)(np.vstack([xx.ravel(), yy.ravel()]))
        return density.reshape(xx.shape)
    except np.linalg.LinAlgError:
        edges = np.linspace(0, 1, len(axis) + 1)
        density, _, _ = np.histogram2d(values[0], values[1], bins=(edges, edges), density=True)
        return density.T


def plot_joint_density_periods(joint: pd.DataFrame, scenario_id: str) -> tuple[Path, Path]:
    """Plot the joint empirical density of commune-level posterior beta means."""
    data = joint.loc[joint["scenario_id"].eq(scenario_id)].copy()
    years = (1962, 1986, 2022)
    axis = np.linspace(0, 1, 121)
    xx, yy = np.meshgrid(axis, axis)
    densities = {
        year: _joint_kde(data.loc[data["year"].eq(year)], axis)
        for year in years
    }
    maximum = max(float(np.nanmax(density)) for density in densities.values())
    norm = Normalize(vmin=0, vmax=maximum)
    x_label, y_label = BETA_AXIS_LABELS[scenario_id]

    fig, axes = plt.subplots(
        1,
        3,
        figsize=(13.4, 4.8),
        sharex=True,
        sharey=True,
        constrained_layout=True,
    )
    mesh = None
    for ax, year in zip(axes, years, strict=True):
        points = data.loc[data["year"].eq(year)]
        density = densities[year]
        mesh = ax.pcolormesh(xx, yy, density, cmap=JOINT_CMAP, norm=norm, shading="auto")
        positive = density[np.isfinite(density) & (density > 0)]
        if positive.size:
            levels = np.unique(np.quantile(positive, [0.70, 0.85, 0.95]))
            if levels.size:
                ax.contour(xx, yy, density, levels=levels, colors=INK, linewidths=0.75, alpha=0.8)
        ax.scatter(
            points["b1_mean"],
            points["b2_mean"],
            s=5,
            facecolors="white",
            edgecolors="none",
            alpha=0.25,
            rasterized=True,
        )
        ax.plot([0, 1], [0, 1], linestyle="--", color="#4F5964", linewidth=1.1)
        status = str(points["classification"].iloc[0])
        ax.set_title(f"{year} — {status}\nn={len(points)} communes", fontsize=10.5, color=INK)
        ax.set(
            xlim=(0, 1),
            ylim=(0, 1),
            xlabel=x_label,
            ylabel=y_label,
        )
        ax.set_aspect("equal", adjustable="box")
        ax.grid(False)
        ax.spines[["top", "right"]].set_visible(False)
    if mesh is not None:
        colorbar = fig.colorbar(mesh, ax=axes, fraction=0.03, pad=0.02)
        colorbar.set_label("Densité KDE — échelle commune")
    fig.suptitle(
        f"{scenario_id} — densité jointe des deux β entre périodes\n{SCENARIO_LABELS[scenario_id]}",
        fontsize=13.5,
        color=INK,
    )
    fig.supxlabel(
        "Chaque point représente la moyenne postérieure d’une commune; contours calculés séparément par période.",
        fontsize=9,
        color="#59636E",
    )
    return _save(fig, f"joint_beta_{scenario_id}_periods")


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    shown = frame.loc[:, columns].copy().fillna("")
    rows = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for values in shown.itertuples(index=False, name=None):
        rows.append("| " + " | ".join(str(value) for value in values) + " |")
    return "\n".join(rows)


def write_report(best: pd.DataFrame, estimates: pd.DataFrame) -> None:
    summary = best[["election_id", "scenario_id", "classification", "draws", "max_rhat", "min_ess_bulk", "min_ess_tail", "divergences", "min_bfmi"]].copy()
    summary["year"] = summary["election_id"].str.extract(r"(\d{4})")
    for column in ("max_rhat", "min_ess_bulk", "min_ess_tail", "min_bfmi"):
        summary[column] = pd.to_numeric(summary[column], errors="coerce").map(lambda value: f"{value:.3f}" if pd.notna(value) else "")
    validated = int(best["classification"].eq("validé").sum())
    caveat = int(best["classification"].eq("avec réserve BFMI").sum())
    report = f"""# Résultats longitudinaux prioritaires — note pour le professeur

## Résumé

Les quatre hypothèses principales H0A, H1, H2 et H4 ont été estimées pour les législatives de 1962, 1986 et 2022 avec le modèle KRT bêta-binomial sur un sous-panel tiré fixe de 500 communes. Après exclusion des lignes sans marges exploitables, les effectifs analytiques sont de 500 communes en 1962, 494 en 1986 et 500 en 2022. Les runs utilisent quatre chaînes, au moins 1 000 itérations de réglage et 1 000 tirages conservés par chaîne, avec `target_accept≥0,99`.

Le bilan final est **{validated}/12 couples strictement validés**, plus **{caveat} avec réserve mineure BFMI**. Les comparaisons H0A et H1 sont strictement validées aux trois dates; elles constituent les comparaisons canoniques recommandées. Les autres sorties sont conservées pour transparence mais les cas exploratoires ne doivent pas soutenir seuls une conclusion.

## Hypothèses testées

- **H0A** — abstention des ouvriers et employés comparée aux autres CSP, dénominateur inscrits.
- **H1** — vote à gauche des ouvriers et employés comparé aux autres CSP, dénominateur suffrages exprimés.
- **H2** — vote à gauche des ouvriers comparé aux autres CSP, dénominateur suffrages exprimés.
- **H4** — vote à droite des agriculteurs et indépendants comparé aux salariés, dénominateur suffrages exprimés.

## Diagnostics des meilleurs runs

{_markdown_table(summary, ['year','scenario_id','classification','draws','max_rhat','min_ess_bulk','min_ess_tail','divergences','min_bfmi'])}

![Vue des diagnostics](../figures/priority_production/diagnostics_overview.png)

## Comparaisons canoniques entre périodes

Les années sont traitées comme trois coupes discrètes. Les points montrent les moyennes postérieures et les barres les intervalles crédibles à 95 %; aucune ligne ne suggère une trajectoire continue.

### H0A — abstention

![Comparaison canonique H0A](../figures/priority_production/canonical_H0A.png)

### H1 — vote à gauche

![Comparaison canonique H1](../figures/priority_production/canonical_H1.png)

## Densités jointes des deux β entre périodes

Ces figures reprennent le type de représentation historique du dossier. Chaque panneau montre la densité empirique jointe des **moyennes postérieures communales** de β₁ et β₂. Les axes et l’échelle de couleur sont identiques entre 1962, 1986 et 2022; les panneaux indiquent leurs effectifs analytiques respectifs (500, 494 et 500). La diagonale représente β₁=β₂; un nuage situé sous la diagonale correspond à β₁>β₂.

### H0A — comparaison validée aux trois périodes

La comparaison de forme et de position de la densité est autorisée aux trois dates, puisque les trois runs sont validés.

![Densité jointe H0A entre périodes](../figures/priority_production/joint_beta_H0A_periods.png)

### H1 — comparaison validée aux trois périodes

La comparaison de forme et de position de la densité est autorisée aux trois dates, puisque les trois runs sont validés.

![Densité jointe H1 entre périodes](../figures/priority_production/joint_beta_H1_periods.png)

### H2 — comparaison partiellement diagnostiquée

La figure est fournie pour transparence : 1986 est validé, 1962 porte une réserve BFMI et 2022 reste exploratoire. Elle ne doit donc pas soutenir seule une conclusion longitudinale.

![Densité jointe H2 entre périodes](../figures/priority_production/joint_beta_H2_periods.png)

### H4 — démonstration exploratoire

Les trois panneaux H4 sont exploratoires. Ils reproduisent le graphique demandé mais ne constituent pas une preuve comparative validée.

![Densité jointe H4 entre périodes](../figures/priority_production/joint_beta_H4_periods.png)

## Démonstration d’une distribution marginale communale

La figure suivante montre la distribution des moyennes postérieures communales. Elle décrit l’hétérogénéité entre communes et ne doit pas être lue comme une distribution d’individus observés.

![Densité communale H0A 2022](../figures/priority_production/density_demo_H0A_2022.png)

## Sorties produites

- `outputs/priority_best_runs.csv` : un meilleur run par hypothèse et période;
- `outputs/priority_best_estimates.csv` : estimations, intervalles, effectifs et statut;
- `outputs/priority_joint_beta_data.csv` : couples communaux (β₁, β₂) utilisés par les densités jointes;
- `outputs/priority_production_diagnostics.csv` : audit complet de tous les essais;
- `outputs/runs/<run_id>/trace.nc` : traces complètes conservées localement;
- `figures/priority_production/` : figures PNG et SVG;
- `docs/PRIORITY_CHART_MAP.md` : source et question de chaque figure.

## Limites

- Il s’agit d’inférence écologique : les comportements individuels ne sont pas observés directement.
- Le sous-panel tiré de 500 communes réduit le temps de calcul et reste identique entre dates; six communes sont sans marges analytiques exploitables en 1986, d’où `n=494` pour cette période. Il ne s’agit pas de l’univers communal complet.
- Les runs classés « exploratoire » sont fournis pour audit, pas pour une conclusion isolée.
- King est conservé comme calibration historique, mais n’a pas été relancé en production car son coût aurait été disproportionné par rapport au gain attendu.
"""
    REPORT_PATH.write_text(report, encoding="utf-8")


def write_chart_map() -> None:
    CHART_MAP_PATH.write_text(
        """# Carte des figures prioritaires

| Figure | Question | Forme | Source | Lecture autorisée |
| --- | --- | --- | --- | --- |
| `diagnostics_overview` | Quels runs passent R-hat/ESS ? | nuage diagnostique | `priority_best_runs.csv` | statut de convergence |
| `canonical_H0A` | Comment l'abstention estimée diffère-t-elle entre 1962/1986/2022 ? | points + intervalles, deux panneaux | `priority_best_estimates.csv` | comparaison de coupes discrètes |
| `canonical_H1` | Comment le vote à gauche estimé diffère-t-il entre les trois dates ? | points + intervalles, deux panneaux | `priority_best_estimates.csv` | comparaison de coupes discrètes |
| `joint_beta_H0A_periods` | Comment la densité jointe (β₁, β₂) diffère-t-elle entre les trois dates ? | KDE bidimensionnelle, trois panneaux | `priority_joint_beta_data.csv` | comparaison validée des densités communales |
| `joint_beta_H1_periods` | Comment la densité jointe (β₁, β₂) diffère-t-elle entre les trois dates ? | KDE bidimensionnelle, trois panneaux | `priority_joint_beta_data.csv` | comparaison validée des densités communales |
| `joint_beta_H2_periods` | Comment la densité jointe (β₁, β₂) diffère-t-elle entre les trois dates ? | KDE bidimensionnelle, trois panneaux | `priority_joint_beta_data.csv` | lecture avec réserve/exploratoire selon le panneau |
| `joint_beta_H4_periods` | Comment la densité jointe (β₁, β₂) diffère-t-elle entre les trois dates ? | KDE bidimensionnelle, trois panneaux | `priority_joint_beta_data.csv` | démonstration exploratoire uniquement |
| `density_demo_H0A_2022` | Quelle hétérogénéité entre communes ? | histogrammes de densité | résumé latent du run sélectionné | distribution de moyennes communales |
""",
        encoding="utf-8",
    )


def build_zip(best: pd.DataFrame) -> None:
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    files = [
        REPORT_PATH,
        CHART_MAP_PATH,
        BEST_RUNS_PATH,
        ESTIMATES_PATH,
        JOINT_BETA_PATH,
        AUDIT_PATH,
    ]
    files.extend(sorted(FIGURE_PATH.glob("*")))
    for run_id in best["run_id"].astype(str):
        run_dir = RUNS_DIR / run_id
        files.extend(
            path
            for name in ("manifest.json", "model_diagnostics.csv", "longitudinal_estimates.csv", "commune_latent_summaries.parquet")
            if (path := run_dir / name).exists()
        )
    readme = """# Paquet clair — résultats longitudinaux prioritaires

Commencer par `docs/PRIORITY_RESULTS_FOR_PROFESSOR.md`.

Le ZIP contient les résumés, diagnostics, figures et manifestes des meilleurs runs. Les fichiers `trace.nc`, beaucoup plus volumineux, restent dans `outputs/runs/<run_id>/` du dossier de travail et sont référencés par les identifiants de `outputs/priority_best_runs.csv`.
"""
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("README.md", readme)
        for path in dict.fromkeys(files):
            archive.write(path, path.relative_to(ROOT).as_posix())
    digest = hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest()
    SHA_PATH.write_text(f"{digest}  {ZIP_PATH.name}\n", encoding="ascii")


def main() -> None:
    ensure_runtime_dirs()
    best = select_best_runs()
    estimates = collect_estimates(best)
    joint = collect_joint_beta_data(best)
    plot_diagnostics(best)
    plot_canonical(estimates, "H0A")
    plot_canonical(estimates, "H1")
    plot_density_demo(best)
    for scenario_id in SCENARIO_LABELS:
        plot_joint_density_periods(joint, scenario_id)
    write_chart_map()
    write_report(best, estimates)
    build_zip(best)
    print(json.dumps({"validated": int(best["classification"].eq("validé").sum()), "total": len(best), "report": str(REPORT_PATH), "zip": str(ZIP_PATH)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
