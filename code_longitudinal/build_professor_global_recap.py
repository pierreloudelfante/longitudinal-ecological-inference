from __future__ import annotations

from pathlib import Path

import pandas as pd

from .build_illustrated_report import (
    DENOMINATOR_LABELS,
    MODEL_LABELS,
    SCENARIO_LABELS,
    _components_label,
    _scenario_comparison_table,
    build_comparison_table,
    plot_interannual_comparisons,
)
from .paths import DOCS_DIR, FIGURE_DIR, OUTPUT_DIR, ensure_runtime_dirs
from .spec_registry import SCENARIO_BY_ID


CANONICAL_SCENARIOS = ("H0A", "H0B", "H0C", "H1", "H2", "H3", "H4", "H5")
REPORT_PATH = DOCS_DIR / "PROFESSOR_GLOBAL_RECAP_1962_1986_2022.md"
REPORT_DATA_PATH = OUTPUT_DIR / "professor_canonical_comparisons.csv"
REPORT_FIGURE_DIR = FIGURE_DIR / "professor_recap"


def _row_count(name: str) -> int:
    parquet = OUTPUT_DIR / f"{name}.parquet"
    if parquet.exists():
        try:
            import pyarrow.parquet as pq

            return int(pq.ParquetFile(parquet).metadata.num_rows)
        except Exception:
            return int(len(pd.read_parquet(parquet)))
    csv_path = OUTPUT_DIR / f"{name}.csv"
    if not csv_path.exists():
        return 0
    with csv_path.open(encoding="utf-8-sig", errors="replace") as stream:
        return max(sum(1 for _ in stream) - 1, 0)


def _markdown_table(headers: list[str], rows: list[list[object]]) -> str:
    def cell(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(cell(value) for value in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(cell(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def _delta_summary(data: pd.DataFrame, scenario_id: str) -> str:
    part = data.loc[data["scenario_id"].eq(scenario_id)]
    sentences: list[str] = []
    for beta_parameter, symbol in (("b_1", "β₁"), ("b_2", "β₂")):
        beta = part.loc[part["beta_parameter"].eq(beta_parameter)]
        deltas: list[str] = []
        for model_key in ("king_truncated_normal", "krt_beta_binomial"):
            model = beta.loc[beta["model_key"].eq(model_key)].set_index("year")
            if {1962, 2022}.issubset(model.index):
                delta = float(model.loc[2022, "mean_equal_commune"] - model.loc[1962, "mean_equal_commune"])
                short = "King" if model_key == "king_truncated_normal" else "KRT"
                deltas.append(f"{short} {delta:+.3f}")
        if deltas:
            sentences.append(f"{symbol} : " + ", ".join(deltas))
    if not sentences:
        return "La comparaison 1962–2022 n’est pas homogène pour les deux modèles."
    return (
        "Écart descriptif de la coupe 2022 à la coupe 1962 sur la moyenne communale : "
        + " ; ".join(sentences)
        + ". Ces écarts ne sont ni une trajectoire continue ni un effet causal."
    )


def _canonical_sections(data: pd.DataFrame) -> str:
    sections: list[str] = []
    for scenario_id in CANONICAL_SCENARIOS:
        part = data.loc[data["scenario_id"].eq(scenario_id)]
        if part.empty:
            continue
        scenario = SCENARIO_BY_ID[scenario_id]
        denominator = DENOMINATOR_LABELS.get(scenario.denominator, scenario.denominator)
        limitation = (
            "H5 n’est pas strictement comparable : King est inapplicable en 1962 et la vue commune 2022 reste à 15 communes."
            if scenario_id == "H5"
            else "Les deux modèles utilisent l’intersection exacte au palier demandé n=3 000 pour les trois dates."
        )
        sections.extend(
            [
                f"### {scenario_id} — {SCENARIO_LABELS[scenario_id]}",
                "",
                f"Dénominateur : **{denominator}**. {_delta_summary(data, scenario_id)} {limitation} "
                "Tous les points restent des calibrations PyEI 20/20/1 avec diagnostic `fail`.",
                "",
                f"![Comparaison canonique 1962–1986–2022 — {scenario_id}](../figures/professor_recap/comparison_interannuelle__{scenario_id}.svg)",
                "",
                _scenario_comparison_table(data, scenario_id),
                "",
            ]
        )
    return "\n".join(sections)


def _definition_table() -> str:
    rows: list[list[object]] = []
    for scenario_id in ("H0A", "H0B", "H0C", "H1", "H2", "H3", "H4", "H5", "H6", "H7"):
        scenario = SCENARIO_BY_ID[scenario_id]
        groups = list(scenario.social_groups.values())
        rows.append(
            [
                scenario_id,
                scenario.vote_categories[0],
                _components_label(groups[0]),
                _components_label(groups[1]),
                DENOMINATOR_LABELS.get(scenario.denominator, scenario.denominator),
                "1962/1986/2022" if scenario.min_year == 1962 else "1986/2022",
            ]
        )
    rows.extend(
        [
            ["RXC1", "5 blocs politiques", "3 groupes sociaux", "—", "suffrages exprimés", "1962/1986/2022"],
            ["RXC2", "5 blocs politiques", "6 CSP", "—", "suffrages exprimés", "1962/1986/2022"],
        ]
    )
    return _markdown_table(
        ["Scénario", "Vote cible", "Groupe cible", "Complément", "Dénominateur", "Périodes pilotes"],
        rows,
    )


def _output_inventory() -> str:
    rows = [
        ["longitudinal_estimates", _row_count("longitudinal_estimates"), "estimations agrégées avec clés et diagnostic"],
        ["model_diagnostics", _row_count("model_diagnostics"), "convergence, rang, ESS/R-hat/divergences et erreurs"],
        ["commune_latent_summaries", _row_count("commune_latent_summaries"), "résumés communaux larges b₁/b₂"],
        ["commune_beta_estimates", _row_count("commune_beta_estimates"), "format long des bêtas, quantiles et groupes"],
        ["beta_trace_index", _row_count("beta_trace_index"), "index SHA-256 des traces NetCDF"],
        ["beta_density_data", _row_count("beta_density_data"), "points reproductibles des densités"],
        ["density_marginal_data", _row_count("density_marginal_data"), "vues marginales natives et communes"],
        ["density_joint_data", _row_count("density_joint_data"), "vues jointes et intersections King/KRT"],
        ["nls_coefficients", _row_count("nls_coefficients"), "coefficients NLS RXC et robustesses"],
        ["nls_start_diagnostics", _row_count("nls_start_diagnostics"), "audit des 20 départs déterministes"],
        ["excluded_units", _row_count("excluded_units"), "communes exclues, étape et raison"],
        ["run_registry", _row_count("run_registry"), "runs exécutés et combinaisons planifiées"],
        ["all_elections_partition_integrity", _row_count("all_elections_partition_integrity"), "292 partitions admissibles auditées"],
        ["pilot_model_coverage", _row_count("pilot_model_coverage"), "56 couples modèle–scénario explicitement suivis"],
        ["pilot_density_selection", _row_count("pilot_density_selection"), "runs alimentant 28 densités principales"],
        ["professor_canonical_comparisons", _row_count("professor_canonical_comparisons"), "valeurs exactes des 8 comparaisons à trois périodes"],
        ["validation_checks", _row_count("validation_checks"), "contrôles machine-lisibles de livraison"],
    ]
    return _markdown_table(["Sortie", "Lignes", "Rôle"], rows)


def _comparison_figure() -> str:
    matches = sorted((FIGURE_DIR / "densities" / "comparisons").glob("leg_2022_r1__H4__king_vs_krt__n3000__*.svg"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one 2022/H4 comparison figure, found {len(matches)}")
    return matches[0].relative_to(FIGURE_DIR).as_posix()


def write_global_recap(data: pd.DataFrame) -> Path:
    comparison_path = _comparison_figure()
    figure_total = len(list(FIGURE_DIR.rglob("*.svg")))
    report = f"""# Récapitulatif global pour le professeur — législatives 1962, 1986 et 2022

## Synthèse technique

Le pipeline pilote est complet sur trois coupes législatives choisies pour leur rôle analytique : **1962** (début de série), **1986** (recomposition sous scrutin proportionnel) et **2022** (point récent). Les 34 partitions admissibles ferment exactement ; les cinq hypothèses ajoutées H0B/H0C/H2/H3/H4 atteignent n=3 000 pour King et KRT aux trois dates. Sur le registre pilote complet, **52 des 56 couples modèle–scénario atteignent n=3 000**, trois restent limités par les ressources et King-H5-1962 est structurellement inapplicable.

Le dossier conserve **{_row_count('commune_beta_estimates'):,} lignes de bêtas communaux**, **{_row_count('beta_trace_index')} traces NetCDF indexées** et **{figure_total} figures SVG**. RXC1/RXC2 NLS passent en 1986 et 2022 ; en 1962, les deux convergent mais échouent au diagnostic de rang à cause d’un bloc centre presque toujours nul.

La limite centrale doit rester visible : les PyEI du pilote utilisent **20 draws, 20 tune et une chaîne**. Les figures valident les données, l’extraction de b₁/b₂, les intersections, la montée à n=3 000 et le format de restitution ; elles ne constituent pas encore des estimations de production ni des comportements individuels observés.

## Les huit comparaisons canoniques entre les trois périodes

Les années sont des coupes discrètes. Chaque point est la moyenne non pondérée des moyennes postérieures communales ; chaque barre est P25–P75 entre communes, pas un intervalle de crédibilité. Aucun segment ne relie les dates afin de ne pas suggérer une trajectoire continue avec seulement trois observations temporelles.

{_canonical_sections(data)}
## Périmètre, groupes et dénominateurs

H0A/H0B/H0C étudient l’abstention sur les **inscrits**, avec `abstention = inscrits − votants`. H1–H7 et RXC1/RXC2 utilisent les **suffrages exprimés**. H6/H7 ne sont pas définis en 1962, faute de bloc FN/RN explicitement enregistré à cette date.

{_definition_table()}

Le panel principal est un tirage fixe de 3 000 communes dans l’univers 2022. Les communes historiquement absentes ne sont ni imputées ni remplacées. Les effectifs affichés dans les figures sont donc les effectifs réellement comparables après filtres.

## Exemples commentés de chaque famille graphique

### 1. Balance du panel — distribution

Cette figure vérifie que la taille du corps électoral du panel ne s’écarte pas fortement de l’univers 2022. Elle documente la sélection du panel ; elle ne mesure aucun comportement électoral.

![Exemple de balance — log1p inscrits](../figures/panel_balance/continuous__log1p_inscrits.svg)

### 2. Densité principale — comparaison de distributions

La vue principale superpose King et KRT sur l’intersection exacte des communes. Chaque commune compte une fois ; la courbe porte sur les moyennes postérieures communales, pas sur l’empilement des draws.

![Exemple de densité principale — H4 2022](../figures/densities/curated/density_overlay__leg_2022_r1__H4__n3000.svg)

### 3. Densité marginale — un modèle à la fois

Cette variante sépare les distributions de b₁ et b₂ pour un modèle donné. Elle sert à contrôler la forme propre à King avant la comparaison entre modèles.

![Exemple de densité marginale — H4 King 2022](../figures/densities/marginal/leg_2022_r1__H4__king_truncated_normal__common__n3000.svg)

### 4. Relation jointe — b₁ contre b₂

Le nuage communal examine la relation entre les deux probabilités latentes estimées. Avec plusieurs milliers de communes, le scatter est suffisamment dense pour montrer dispersion, concentration et valeurs extrêmes.

![Exemple de relation jointe — H4 King 2022](../figures/densities/joint/leg_2022_r1__H4__king_truncated_normal__common__n3000.svg)

### 5. Comparaison exacte King/KRT — même population

Cette figure impose les mêmes identifiants communaux aux deux modèles. Elle répond à une question de sensibilité au modèle ; une divergence visible ne doit pas être attribuée à une différence de composition communale.

![Exemple d’intersection King/KRT — H4 2022](../figures/{comparison_path})

### 6. Vue longitudinale disponible — écart entre groupes

Les figures longitudinales couvrent les runs disponibles par type d’élection. Elles servent à repérer les scénarios et périodes calculés ; les lignes ne transforment pas les calibrations en série de production.

![Exemple longitudinal — H1 King, législatives](../figures/longitudinal/gap__H1__king_truncated_normal__legislative.svg)

### 7. Diagnostic NLS 2022 — matrice groupe × vote

La matrice RXC2 traduit directement les coefficients softmax en probabilités par CSP et bloc politique. Elle se lit avec la qualité d’ajustement observé–prédit et le diagnostic de rang, pas isolément.

![Exemple NLS — matrice RXC2 2022](../figures/election_2022/nls_probability_matrix__RXC2.svg)

### 8. Comparaison interannuelle — points et dispersion

Le dot-and-interval est le format canonique pour trois dates discrètes : moyenne communale au point, P25–P75 entre communes sur la barre, King et KRT distingués par couleur et forme.

![Exemple interannuel — H0A](../figures/professor_recap/comparison_interannuelle__H0A.svg)

## Inventaire global des sorties analytiques

{_output_inventory()}

Les tables volumineuses existent en Parquet pour l’efficacité et, lorsque nécessaire, en CSV pour inspection. Les runs physiques restent immuables dans `outputs/runs/`; le registre relie chaque `run_id`, `run_key`, configuration, empreinte d’entrée et statut.

## Méthode et correspondance avec le code

Pour la commune i, le modèle 2×2 vérifie `yᵢ = xᵢβ₁ᵢ + (1−xᵢ)β₂ᵢ`. Les tirages b₁/b₂ sont lus directement dans les traces, résumés commune par commune, puis comparés sur l’intersection exacte des identifiants King/KRT. Les densités principales donnent le même poids à chaque commune.

- registre des scénarios et dénominateurs : `code_longitudinal/spec_registry.py` ;
- validation et fermeture des partitions : `prepare_inputs.py` ;
- King/KRT, traces et extraction communale : `run_2x2_batch.py` ;
- table longue des bêtas et index NetCDF : `beta_outputs.py` ;
- intersections et densités : `extract_latent_densities.py` ;
- NLS multi-départs et sandwich : `nls.py` ;
- comparaisons canoniques : `build_illustrated_report.py` et `build_professor_global_recap.py` ;
- contrôles de livraison : `validate_outputs.py`.

La correspondance formelle détaillée et les repères de ligne sont dans [`METHODOLOGY_CODE_MAP.md`](METHODOLOGY_CODE_MAP.md). Le catalogue de toutes les figures est [`FIGURE_CATALOG.md`](FIGURE_CATALOG.md).

## Contrôles, limites et robustesse

- Les tests automatisés couvrent panel, identifiants, partitions, extraction b₁/b₂, intersection exacte, bornes [0,1], NLS, reprise et déterminisme.
- Les 240 partitions 2×2 admissibles passent. Parmi 52 partitions RXC, 30 passent et 22 sont refusées parce que l’écart brut dépasse 0,01 voix ; aucune fermeture forcée ne les masque.
- Les diagnostics PyEI restent `fail` pour interprétation substantielle : une chaîne et 20 draws ne permettent ni R-hat inter-chaînes ni ESS de production.
- Les barres P25–P75 mesurent l’hétérogénéité entre communes, pas l’incertitude d’un changement temporel.
- Le panel rétrospectif est défini dans l’univers 2022 : il décrit un suivi de survivants communaux.
- L’inférence écologique relie des marges agrégées sous hypothèses de modèle ; elle n’observe pas les choix individuels et n’établit pas de causalité.

## Suite recommandée pour un résultat professoral substantiel

1. Produire d’abord H0A, H1 et un sous-ensemble discriminant H0B/H2/H4 en `4 chaînes × 1 000 draws`, avec 1 000 tune et `target_accept=0,99`.
2. N’étendre la production aux 26 scrutins qu’après diagnostics R-hat, ESS et divergences satisfaisants sur ces comparaisons canoniques.
3. Présenter séparément législatives et présidentielles, puis ajouter les robustesses une covariable à la fois.
4. Ne pas utiliser H5-1962, H5-2022 ou H7-1986 pour une conclusion temporelle sans résoudre leurs limites structurelles ou de taille commune.

## Questions encore ouvertes

- Les directions visibles survivent-elles au passage `4 × 1 000` et à une ESS suffisante ?
- Les écarts King/KRT diminuent-ils avec davantage de draws ou révèlent-ils une sensibilité structurelle au modèle ?
- Les comparaisons restent-elles stables en pondérant par les effectifs sociaux ?
- Quelle part des différences temporelles tient aux absences historiques du panel fixé en 2022 ?
"""
    REPORT_PATH.write_text(report, encoding="utf-8")
    return REPORT_PATH


def build_professor_global_recap() -> dict[str, int | str]:
    ensure_runtime_dirs()
    selection = pd.read_csv(OUTPUT_DIR / "pilot_density_selection.csv", low_memory=False)
    joint = pd.read_csv(
        OUTPUT_DIR / "density_joint_data.csv", dtype={"unit_id": "string"}, low_memory=False
    )
    data = build_comparison_table(selection, joint, scenario_order=CANONICAL_SCENARIOS)
    data.to_csv(REPORT_DATA_PATH, index=False, encoding="utf-8-sig")
    figures = plot_interannual_comparisons(
        data,
        scenario_order=CANONICAL_SCENARIOS,
        figure_dir=REPORT_FIGURE_DIR,
    )
    report = write_global_recap(data)
    return {
        "comparison_rows": len(data),
        "comparison_figures": len(figures),
        "report_path": str(report),
    }


if __name__ == "__main__":
    print(build_professor_global_recap())
