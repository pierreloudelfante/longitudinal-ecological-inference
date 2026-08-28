from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .paths import DOCS_DIR, FIGURE_DIR, OUTPUT_DIR, ensure_runtime_dirs
from .spec_registry import ELECTION_BY_ID, SCENARIO_BY_ID


PILOT_ELECTIONS = ("leg_1962_r1", "leg_1986_r1", "leg_2022_r1")
SCENARIO_ORDER = ("H0A", "H1", "H5", "H6", "H7")
REPORT_PATH = DOCS_DIR / "RESULTS_ILLUSTRATED_1962_1986_2022.md"
REPORT_DATA_PATH = OUTPUT_DIR / "illustrated_report_estimates.csv"
REPORT_FIGURE_DIR = FIGURE_DIR / "illustrated_report"

MODEL_ORDER = ("king_truncated_normal", "krt_beta_binomial")
MODEL_LABELS = {
    "king_truncated_normal": "King — normale tronquée",
    "krt_beta_binomial": "KRT — King99 bêta-binomial",
}
MODEL_STYLES = {
    "king_truncated_normal": {"color": "#2B6CB0", "marker": "o", "filled": True},
    "krt_beta_binomial": {"color": "#D97706", "marker": "D", "filled": False},
}
CSP_LABELS = {
    "agri": "agriculteurs",
    "indp": "indépendants",
    "cadr": "cadres",
    "pint": "professions intermédiaires",
    "empl": "employés",
    "ouvr": "ouvriers",
}
SCENARIO_LABELS = {
    "H0A": "Abstention — ouvriers et employés vs autres CSP",
    "H0B": "Abstention — ouvriers vs autres CSP",
    "H0C": "Abstention — employés vs autres CSP",
    "H1": "Vote à gauche — ouvriers et employés vs autres CSP",
    "H2": "Vote à gauche — ouvriers vs autres CSP",
    "H3": "Vote à gauche — employés vs autres CSP",
    "H4": "Vote à droite — agriculteurs et indépendants vs salariés",
    "H5": "Vote au centre — cadres vs autres CSP",
    "H6": "Vote FN/RN — ouvriers vs autres CSP",
    "H7": "Vote FN/RN — employés vs autres CSP",
}
DENOMINATOR_LABELS = {
    "registered": "inscrits",
    "expressed": "suffrages exprimés",
}


def _components_label(components: Iterable[str]) -> str:
    labels = [CSP_LABELS.get(component, component) for component in components]
    if len(labels) == 1:
        return labels[0]
    return " + ".join(labels)


def _social_group_label(scenario_id: str, beta_parameter: str) -> tuple[str, str]:
    groups = list(SCENARIO_BY_ID[scenario_id].social_groups.items())
    index = 0 if beta_parameter == "b_1" else 1
    key, components = groups[index]
    return key, _components_label(components)


def _required_columns(frame: pd.DataFrame, columns: set[str], name: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{name}: colonnes manquantes: {missing}")


def build_comparison_table(
    selection: pd.DataFrame,
    joint: pd.DataFrame,
    *,
    scenario_order: Iterable[str] = SCENARIO_ORDER,
) -> pd.DataFrame:
    """Summarise the exact density views used in the illustrated report.

    The main estimate is the unweighted mean of commune posterior means. The
    quartiles describe dispersion between communes and are not posterior
    credible intervals. For common King/KRT views, both models must use the
    exact same set of commune identifiers.
    """

    _required_columns(
        selection,
        {
            "election_id",
            "scenario_id",
            "selection_scope",
            "model_key",
            "run_id",
            "comparison_key",
            "n_communes_requested",
            "n_communes_selected",
            "draws",
            "tune",
            "chains",
            "diagnostic_status",
        },
        "pilot_density_selection",
    )
    _required_columns(
        joint,
        {
            "run_id",
            "comparison_key",
            "comparison_scope",
            "unit_id",
            "b1_mean",
            "b2_mean",
            "b1_weight",
            "b2_weight",
        },
        "density_joint_data",
    )

    selected_scenarios = tuple(scenario_order)
    chosen = selection.loc[
        selection["election_id"].isin(PILOT_ELECTIONS)
        & selection["scenario_id"].isin(selected_scenarios)
    ].copy()
    duplicated = chosen.duplicated(["election_id", "scenario_id", "model_key"], keep=False)
    if duplicated.any():
        keys = chosen.loc[duplicated, ["election_id", "scenario_id", "model_key"]]
        raise ValueError(f"Sélection de densité dupliquée: {keys.to_dict('records')}")

    # Enforce exact King/KRT intersections before computing any summary.
    for (election_id, scenario_id), group in chosen.groupby(
        ["election_id", "scenario_id"], sort=True
    ):
        if set(group["selection_scope"]) != {"largest_common_intersection"}:
            continue
        if set(group["model_key"]) != set(MODEL_ORDER):
            raise ValueError(f"Intersection incomplète: {election_id}/{scenario_id}")
        unit_sets: list[set[str]] = []
        for row in group.itertuples(index=False):
            part = joint.loc[
                joint["run_id"].astype(str).eq(str(row.run_id))
                & joint["comparison_key"].astype(str).eq(str(row.comparison_key))
                & joint["comparison_scope"].eq("common_intersection")
            ]
            unit_sets.append(set(part["unit_id"].astype(str)))
        if not unit_sets[0] or unit_sets[0] != unit_sets[1]:
            raise ValueError(f"Intersection King/KRT non exacte: {election_id}/{scenario_id}")

    rows: list[dict[str, object]] = []
    for selected in chosen.itertuples(index=False):
        election = ELECTION_BY_ID[str(selected.election_id)]
        scenario = SCENARIO_BY_ID[str(selected.scenario_id)]
        scope = (
            "common_intersection"
            if selected.selection_scope == "largest_common_intersection"
            else "native"
        )
        part = joint.loc[
            joint["run_id"].astype(str).eq(str(selected.run_id))
            & joint["comparison_key"].astype(str).eq(str(selected.comparison_key))
            & joint["comparison_scope"].eq(scope)
        ].copy()
        n_units = int(part["unit_id"].astype(str).nunique())
        if n_units != int(selected.n_communes_selected):
            raise ValueError(
                f"Effectif incohérent pour {selected.run_id}: "
                f"{n_units} != {selected.n_communes_selected}"
            )
        if part["unit_id"].astype(str).duplicated().any():
            raise ValueError(f"Communes dupliquées dans la vue {selected.run_id}/{scope}")

        for beta_parameter, value_column, weight_column in (
            ("b_1", "b1_mean", "b1_weight"),
            ("b_2", "b2_mean", "b2_weight"),
        ):
            values = pd.to_numeric(part[value_column], errors="coerce")
            weights = pd.to_numeric(part[weight_column], errors="coerce")
            if values.isna().any() or not values.between(0, 1).all():
                raise ValueError(f"β non fini ou hors [0,1]: {selected.run_id}/{beta_parameter}")
            if weights.isna().any() or (weights < 0).any() or float(weights.sum()) <= 0:
                raise ValueError(f"Poids invalides: {selected.run_id}/{beta_parameter}")
            social_group, social_group_label = _social_group_label(
                str(selected.scenario_id), beta_parameter
            )
            rows.append(
                {
                    "election_id": election.election_id,
                    "election_type": election.election_type,
                    "year": election.year,
                    "round": election.round,
                    "scenario_id": scenario.scenario_id,
                    "hypothesis_label": SCENARIO_LABELS[scenario.scenario_id],
                    "target_vote": scenario.vote_categories[0],
                    "denominator": scenario.denominator,
                    "model_key": selected.model_key,
                    "model_label": MODEL_LABELS[str(selected.model_key)],
                    "run_id": selected.run_id,
                    "comparison_key": selected.comparison_key,
                    "selection_scope": selected.selection_scope,
                    "n_communes_requested": int(selected.n_communes_requested),
                    "n_communes_selected": n_units,
                    "draws": int(selected.draws),
                    "tune": int(selected.tune),
                    "chains": int(selected.chains),
                    "diagnostic_status": selected.diagnostic_status,
                    "beta_parameter": beta_parameter,
                    "social_group": social_group,
                    "social_group_label": social_group_label,
                    "estimate_basis": "mean_of_commune_posterior_means",
                    "mean_equal_commune": float(values.mean()),
                    "sd_between_communes": float(values.std(ddof=1)),
                    "p25_between_communes": float(values.quantile(0.25)),
                    "median_between_communes": float(values.median()),
                    "p75_between_communes": float(values.quantile(0.75)),
                    "mean_social_weighted": float(np.average(values, weights=weights)),
                }
            )

    result = pd.DataFrame(rows)
    return result.sort_values(
        ["scenario_id", "year", "model_key", "beta_parameter"]
    ).reset_index(drop=True)


def _save_figure(fig: Any, base: Path) -> None:
    import matplotlib.pyplot as plt

    base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(base.with_suffix(".png"), dpi=200, bbox_inches="tight", facecolor="white")
    fig.savefig(base.with_suffix(".svg"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_interannual_comparisons(
    data: pd.DataFrame,
    *,
    scenario_order: Iterable[str] = SCENARIO_ORDER,
    figure_dir: Path = REPORT_FIGURE_DIR,
) -> list[Path]:
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    selected_scenarios = tuple(scenario_order)
    figure_dir.mkdir(parents=True, exist_ok=True)
    for pattern in ("comparison_interannuelle__*.png", "comparison_interannuelle__*.svg"):
        for old in figure_dir.glob(pattern):
            old.unlink()

    generated: list[Path] = []
    for scenario_id in selected_scenarios:
        scenario_data = data.loc[data["scenario_id"].eq(scenario_id)].copy()
        if scenario_data.empty:
            continue
        years = sorted(scenario_data["year"].astype(int).unique())
        positions = {year: index for index, year in enumerate(years)}
        fig, axes = plt.subplots(1, 2, figsize=(12.4, max(5.2, 1.15 * len(years) + 2.7)))
        for ax, beta_parameter in zip(axes, ("b_1", "b_2")):
            beta = scenario_data.loc[scenario_data["beta_parameter"].eq(beta_parameter)]
            group_label = str(beta["social_group_label"].iloc[0])
            for model_index, model_key in enumerate(MODEL_ORDER):
                model = beta.loc[beta["model_key"].eq(model_key)]
                if model.empty:
                    continue
                style = MODEL_STYLES[model_key]
                offset = -0.11 if model_index == 0 else 0.11
                for row in model.itertuples(index=False):
                    y = positions[int(row.year)] + offset
                    ax.hlines(
                        y,
                        row.p25_between_communes,
                        row.p75_between_communes,
                        color=style["color"],
                        linewidth=3.0,
                        alpha=0.72,
                    )
                    ax.scatter(
                        row.mean_equal_commune,
                        y,
                        s=65,
                        marker=style["marker"],
                        facecolor=style["color"] if style["filled"] else "white",
                        edgecolor=style["color"],
                        linewidth=1.7,
                        zorder=3,
                    )
                    value = float(row.mean_equal_commune)
                    align_right = value > 0.91
                    ax.annotate(
                        f"{value:.3f}",
                        (value, y),
                        xytext=(-7 if align_right else 7, 0),
                        textcoords="offset points",
                        ha="right" if align_right else "left",
                        va="center",
                        fontsize=8.5,
                        color="#1F2937",
                    )
            year_labels = []
            for year in years:
                n_values = sorted(
                    beta.loc[beta["year"].eq(year), "n_communes_selected"]
                    .astype(int)
                    .unique()
                )
                n_label = "/".join(f"{value:,}".replace(",", " ") for value in n_values)
                year_labels.append(f"{year}\nn={n_label}")
            ax.set_yticks(range(len(years)), year_labels)
            ax.invert_yaxis()
            # Preserve a truthful [0,1] scale while leaving room for markers at
            # the mathematical boundaries and their direct labels.
            ax.set_xlim(-0.035, 1.035)
            ax.set_xticks(np.linspace(0, 1, 6))
            ax.set_xlabel(f"Moyenne communale de P({scenario_data['target_vote'].iloc[0]})")
            beta_symbol = "β₁" if beta_parameter == "b_1" else "β₂"
            ax.set_title(f"{beta_symbol} — {group_label}", fontsize=11.5, loc="left")
            ax.grid(axis="x", color="#D1D5DB", linewidth=0.8, alpha=0.65)
            ax.grid(axis="y", visible=False)
            ax.spines[["top", "right"]].set_visible(False)
            ax.spines[["left", "bottom"]].set_color("#9CA3AF")

        legend_handles = [
            Line2D(
                [0],
                [0],
                color=MODEL_STYLES[key]["color"],
                marker=MODEL_STYLES[key]["marker"],
                markerfacecolor=(
                    MODEL_STYLES[key]["color"] if MODEL_STYLES[key]["filled"] else "white"
                ),
                markeredgecolor=MODEL_STYLES[key]["color"],
                linewidth=2.4,
                label=MODEL_LABELS[key],
            )
            for key in MODEL_ORDER
            if key in set(scenario_data["model_key"])
        ]
        fig.suptitle(
            f"{scenario_id} — comparaison des β communaux par année",
            x=0.08,
            y=0.985,
            ha="left",
            fontsize=15,
            fontweight="bold",
            color="#111827",
        )
        fig.text(
            0.08,
            0.925,
            "Point = moyenne non pondérée des moyennes postérieures communales ; barre = P25–P75 entre communes. "
            "Calibrations PyEI 20 draws / 20 tune / 1 chaîne — NON SUBSTANTIELLES.",
            ha="left",
            va="top",
            fontsize=9.3,
            color="#4B5563",
        )
        fig.legend(
            handles=legend_handles,
            loc="upper center",
            bbox_to_anchor=(0.5, 0.885),
            ncol=max(1, len(legend_handles)),
            frameon=False,
            fontsize=9.3,
        )
        denominator = DENOMINATOR_LABELS.get(
            str(scenario_data["denominator"].iloc[0]), str(scenario_data["denominator"].iloc[0])
        )
        fig.text(
            0.08,
            0.018,
            f"Champ : législatives, tour 1 ; dénominateur : {denominator}. "
            "Les années sont des coupes discrètes ; aucune trajectoire continue n’est estimée.",
            ha="left",
            fontsize=8.5,
            color="#4B5563",
        )
        fig.subplots_adjust(left=0.10, right=0.98, bottom=0.14, top=0.79, wspace=0.27)
        base = figure_dir / f"comparison_interannuelle__{scenario_id}"
        _save_figure(fig, base)
        generated.append(base.with_suffix(".svg"))
    return generated


def _markdown_table(headers: list[str], rows: list[list[object]]) -> str:
    def cell(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(cell(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def _scenario_comparison_table(data: pd.DataFrame, scenario_id: str) -> str:
    scenario = data.loc[data["scenario_id"].eq(scenario_id)]
    rows: list[list[object]] = []
    for (year, model_key), group in scenario.groupby(["year", "model_key"], sort=True):
        by_beta = group.set_index("beta_parameter")
        b1 = by_beta.loc["b_1"]
        b2 = by_beta.loc["b_2"]
        rows.append(
            [
                int(year),
                MODEL_LABELS[str(model_key)],
                f"{int(b1['n_communes_selected']):,}".replace(",", " "),
                f"{float(b1['mean_equal_commune']):.3f}",
                f"{float(b2['mean_equal_commune']):.3f}",
                str(b1["diagnostic_status"]),
            ]
        )
    b1_label = str(scenario.loc[scenario["beta_parameter"].eq("b_1"), "social_group_label"].iloc[0])
    b2_label = str(scenario.loc[scenario["beta_parameter"].eq("b_2"), "social_group_label"].iloc[0])
    return _markdown_table(
        ["Année", "Modèle", "Communes", f"β₁ {b1_label}", f"β₂ {b2_label}", "Diagnostic"],
        rows,
    )


def _coverage_table(selection: pd.DataFrame) -> str:
    rows: list[list[object]] = []
    chosen = selection.loc[
        selection["election_id"].isin(PILOT_ELECTIONS)
        & selection["scenario_id"].isin(SCENARIO_ORDER)
    ]
    for (election_id, scenario_id), group in chosen.groupby(
        ["election_id", "scenario_id"], sort=True
    ):
        models = ", ".join(MODEL_LABELS[str(value)] for value in group["model_key"])
        n_requested = "/".join(
            str(int(value)) for value in sorted(group["n_communes_requested"].unique())
        )
        n_selected = "/".join(
            str(int(value)) for value in sorted(group["n_communes_selected"].unique())
        )
        scope = str(group["selection_scope"].iloc[0]).replace("largest_", "")
        mcmc = "/".join(
            sorted({f"{int(row.draws)}/{int(row.tune)}/{int(row.chains)}" for row in group.itertuples()})
        )
        diagnostics = "/".join(sorted(group["diagnostic_status"].astype(str).unique()))
        rows.append(
            [
                ELECTION_BY_ID[str(election_id)].year,
                scenario_id,
                scope,
                models,
                n_requested,
                n_selected,
                mcmc,
                diagnostics,
            ]
        )
    return _markdown_table(
        ["Année", "Hypothèse", "Vue", "Modèles", "Palier", "Communes", "draws/tune/chaînes", "Diagnostic"],
        rows,
    )


def _density_sections(selection: pd.DataFrame) -> str:
    sections: list[str] = []
    chosen = selection.loc[
        selection["election_id"].isin(PILOT_ELECTIONS)
        & selection["scenario_id"].isin(SCENARIO_ORDER)
    ]
    for election_id in PILOT_ELECTIONS:
        year = ELECTION_BY_ID[election_id].year
        sections.extend(
            [
                f"## {year} — distributions communales",
                "",
                "Chaque panneau montre la densité des moyennes postérieures communales : une commune compte une fois. "
                "La hauteur d’une densité n’est pas une probabilité ; la surface sous chaque courbe vaut un.",
                "",
            ]
        )
        election = chosen.loc[chosen["election_id"].eq(election_id)]
        for scenario_id in SCENARIO_ORDER:
            group = election.loc[election["scenario_id"].eq(scenario_id)]
            if group.empty:
                continue
            n_requested = int(group["n_communes_requested"].max())
            n_selected = "/".join(
                str(int(value)) for value in sorted(group["n_communes_selected"].unique())
            )
            models = ", ".join(MODEL_LABELS[str(value)] for value in group["model_key"])
            scope = str(group["selection_scope"].iloc[0])
            scope_text = (
                "intersection exacte King/KRT"
                if scope == "largest_common_intersection"
                else "vue native KRT, faute de vue King valide"
            )
            filename = f"density_overlay__{election_id}__{scenario_id}__n{n_requested}.svg"
            sections.extend(
                [
                    f"### {scenario_id} — {SCENARIO_LABELS[scenario_id]}",
                    "",
                    f"Vue : {scope_text} ; palier demandé `{n_requested}` ; communes représentées `{n_selected}` ; "
                    f"modèles : {models}. Le diagnostic PyEI est `fail`, donc la figure documente la calibration, pas un résultat final.",
                    "",
                    f"![{year} — {scenario_id} — densités communales](../figures/densities/curated/{filename})",
                    "",
                ]
            )
    return "\n".join(sections)


def write_illustrated_report(data: pd.DataFrame, selection: pd.DataFrame) -> Path:
    interpretation = {
        "H0A": (
            "Dans ces calibrations, les deux modèles placent la moyenne communale d’abstention "
            "plus haut en 2022 qu’en 1986 pour les deux groupes. Le niveau de 1962 et l’amplitude "
            "des écarts dépendent toutefois du modèle ; ce constat reste descriptif."
        ),
        "H1": (
            "Pour β₁ (ouvriers + employés), les deux modèles donnent une moyenne plus faible en "
            "2022 qu’en 1962. Pour β₂, King et KRT ne décrivent pas la même direction entre ces "
            "deux dates : aucune conclusion robuste ne peut être tirée."
        ),
        "H5": (
            "La comparaison temporelle n’est pas homogène : King est absent en 1962, l’intersection "
            "1986 ne contient que 687 communes et celle de 2022 seulement 15. Cette figure sert "
            "principalement à rendre visible cette fragilité."
        ),
        "H6": (
            "Les deux calibrations placent les moyennes β₁ et β₂ plus haut en 2022 qu’en 1986. "
            "Les effectifs comparés diffèrent (473 contre 2 485 communes) et les diagnostics échouent ; "
            "il ne s’agit donc pas encore d’une estimation validée de l’évolution du vote FN/RN."
        ),
        "H7": (
            "Le point 1986 repose sur 21 communes et King/KRT y divergent fortement, surtout pour β₁. "
            "La comparaison 1986–2022 est trop instable pour être interprétée comme une évolution."
        ),
    }

    scenario_sections: list[str] = []
    for scenario_id in SCENARIO_ORDER:
        if data.loc[data["scenario_id"].eq(scenario_id)].empty:
            continue
        scenario_sections.extend(
            [
                f"### {scenario_id} — {SCENARIO_LABELS[scenario_id]}",
                "",
                interpretation[scenario_id],
                "",
                f"![Comparaison interannuelle — {scenario_id}](../figures/illustrated_report/comparison_interannuelle__{scenario_id}.svg)",
                "",
                _scenario_comparison_table(data, scenario_id),
                "",
            ]
        )

    definitions = []
    for scenario_id in SCENARIO_ORDER:
        scenario = SCENARIO_BY_ID[scenario_id]
        group1 = _components_label(list(scenario.social_groups.values())[0])
        group2 = _components_label(list(scenario.social_groups.values())[1])
        years = "1962, 1986, 2022" if scenario_id in {"H0A", "H1", "H5"} else "1986, 2022"
        definitions.append(
            [
                scenario_id,
                scenario.vote_categories[0],
                group1,
                group2,
                DENOMINATOR_LABELS.get(scenario.denominator, scenario.denominator),
                years,
            ]
        )

    report = f"""# Résultats illustrés — législatives 1962, 1986 et 2022

## Synthèse technique

Ce rapport rassemble **18 figures directement visibles dans le Markdown** : cinq comparaisons interannuelles et treize densités King/KRT, réparties entre les législatives de 1962, 1986 et 2022 (premier tour). H0A, H1 et H5 sont comparées aux trois dates ; H6 et H7 seulement en 1986 et 2022, car FN/RN n’est pas défini en 1962 dans le registre.

Le résultat le plus important est une limite : **tous les ajustements PyEI présentés ici sont des calibrations 20 draws / 20 tune / 1 chaîne avec diagnostic `fail`**. Les graphiques vérifient la chaîne données → traces → β communaux → densités → comparaison annuelle, mais ne constituent pas des estimations substantielles des comportements individuels. Les constats ci-dessous sont descriptifs et ne sont ni causaux ni validés pour publication.

La comparaison est la plus proche du plan pour H0A et H1, qui atteignent le palier demandé de 3 000 aux trois dates avec des intersections King/KRT de 2 813 à 2 963 communes. H5 et H7 restent les points faibles : H5-2022 ne compare que 15 communes et H7-1986 seulement 21.

## Ce que montrent les comparaisons entre années

Les années sont traitées comme des coupes discrètes. Les figures utilisent des points, et non des lignes, afin de ne pas suggérer une trajectoire continue avec seulement deux ou trois dates. Le point est la moyenne non pondérée des moyennes postérieures communales ; la barre P25–P75 décrit l’hétérogénéité entre communes, **pas** l’incertitude postérieure.

{chr(10).join(scenario_sections)}
## Périmètre et définitions

{_markdown_table(["Hypothèse", "Vote cible", "β₁ — groupe cible", "β₂ — complément", "Dénominateur", "Années"], definitions)}

Les groupes sociaux sont construits à partir des six CSP actives. Les marges politiques sont validées avant fermeture par plus forts restes. Une commune absente ou dégénérée est exclue à la date concernée sans remplacement.

### Couverture exacte des figures

{_coverage_table(selection)}

## Formalisme et traduction algorithmique

Pour une année `t`, une hypothèse `h`, un modèle `m`, une commune `i` et un groupe social `g`, `β̂[g,i,t,h,m]` désigne la moyenne postérieure communale extraite directement de `b_1` ou `b_2`. Les densités représentent la distribution de ces `β̂`, à poids égal entre communes.

La comparaison annuelle trace :

`β̄[g,t,h,m] = (1 / |I[t,h]|) × Σ(i ∈ I[t,h]) β̂[g,i,t,h,m]`

où `I[t,h]` est l’intersection exacte des communes King/KRT lorsque les deux modèles existent. Pour H5-1962, aucune vue King valide n’existe : la vue KRT native est conservée et signalée. L’intervalle graphique est `[P25(β̂), P75(β̂)]` entre communes.

La correspondance code-formalisme est directe :

- extraction et export des `b_1`/`b_2` communaux : `code_longitudinal/beta_outputs.py`, fonction `build_commune_beta_estimates` ;
- construction des intersections et densités : `code_longitudinal/extract_latent_densities.py`, fonctions `_with_scopes`, `_select_largest_plot_views` et `_plot_curated_overlays` ;
- calcul de `β̄`, quartiles et contrôle des identifiants : `code_longitudinal/build_illustrated_report.py`, fonction `build_comparison_table` ;
- tracé interannuel sans interpolation : même fichier, fonction `plot_interannual_comparisons` ;
- génération du présent document : même fichier, fonction `write_illustrated_report`.

Le détail avec numéros de lignes est maintenu dans [`METHODOLOGY_CODE_MAP.md`](METHODOLOGY_CODE_MAP.md). La table exacte qui alimente les cinq comparaisons est [`outputs/illustrated_report_estimates.csv`](../outputs/illustrated_report_estimates.csv).

{_density_sections(selection)}
## Limites, incertitude et robustesse

- Les diagnostics PyEI échouent : une chaîne ne permet pas de calculer un R-hat valide et 20 tirages ne permettent pas une ESS de production.
- Les barres P25–P75 résument les différences entre communes ; elles ne remplacent pas un intervalle de crédibilité ou une analyse d’incertitude interannuelle.
- Les effectifs varient selon la date et l’hypothèse à cause des absences et lignes dégénérées. Les communes ne sont jamais remplacées.
- H5-1962 est une vue KRT native, donc sans comparaison King/KRT. H5-2022 (`n=15`) et H7-1986 (`n=21`) sont des smoke tests particulièrement fragiles.
- L’inférence écologique estime des associations agrégées sous hypothèses de modèle ; elle n’observe pas les choix individuels et ne démontre pas de causalité.
- Trois dates ne suffisent pas à documenter la série 1962–2022 prévue dans le plan. Elles valident uniquement le format de restitution longitudinale.

## Suite recommandée

1. Relancer H0A et H1 en production (`4 × 1 000` draws, `1 000` tune, `target_accept=0,99`) sur les plus grands paliers autorisés par les garde-fous.
2. Réparer ou redéfinir les cas H5-2022 et H7-1986 avant toute comparaison temporelle.
3. Ajouter progressivement les autres législatives au même schéma, puis séparer un rapport présidentiel.
4. Ne convertir les observations descriptives en résultats que lorsque divergences, R-hat, ESS et intersections communes satisfont les critères configurés.

## Questions encore ouvertes

- Les contrastes visibles persistent-ils avec quatre chaînes et une ESS suffisante ?
- Restent-ils stables en pondération par effectifs sociaux plutôt qu’à poids communal égal ?
- Sont-ils robustes à l’ajout séparé de VBBM, revenu/capital, immigration et région Nord-Est/Sud-Est ?
- Les changements de périmètre communal expliquent-ils une part des différences entre années malgré l’absence de remplacement ?

## Sources internes

- `outputs/pilot_density_selection.csv` : choix des runs, intersections et effectifs ;
- `outputs/density_joint_data.csv` : β communaux joints et poids sociaux ;
- `outputs/illustrated_report_estimates.csv` : agrégats et quartiles exactement tracés ;
- `outputs/model_diagnostics.csv` : diagnostics des ajustements ;
- `figures/densities/curated/` : treize superpositions de densités ;
- `figures/illustrated_report/` : cinq comparaisons interannuelles.
"""
    REPORT_PATH.write_text(report, encoding="utf-8")
    return REPORT_PATH


def build_illustrated_report() -> dict[str, int | str]:
    ensure_runtime_dirs()
    selection = pd.read_csv(OUTPUT_DIR / "pilot_density_selection.csv", low_memory=False)
    joint = pd.read_csv(
        OUTPUT_DIR / "density_joint_data.csv", dtype={"unit_id": "string"}, low_memory=False
    )
    data = build_comparison_table(selection, joint)
    data.to_csv(REPORT_DATA_PATH, index=False, encoding="utf-8-sig")
    figures = plot_interannual_comparisons(data)
    report = write_illustrated_report(data, selection)
    return {
        "comparison_rows": len(data),
        "comparison_figures": len(figures),
        "report_path": str(report),
    }


if __name__ == "__main__":
    print(build_illustrated_report())
