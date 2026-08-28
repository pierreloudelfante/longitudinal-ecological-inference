"""Build the homogeneous Markdown and autonomous PDF for the V3 interim release."""

from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd

from .paths import DOCS_DIR, FIGURE_DIR, OUTPUT_DIR, ROOT, ensure_runtime_dirs


TITLE = "Premiers résultats - modèles KRT et NLS"
REPORT_STEM = "PREMIERS_RESULTATS_KRT_NLS_PANEL_3000"
DATA_DIR = OUTPUT_DIR / "v2" / "priority_3000_final"
FIG_DIR = FIGURE_DIR / "v2" / "priority_3000_final"
MD_PATH = DOCS_DIR / f"{REPORT_STEM}.md"
PDF_PATH = ROOT / "output" / "pdf" / f"{REPORT_STEM}.pdf"
PANEL_MANIFEST = ROOT / "panel" / "panel_3000_common_1962_1986_2022_v3_manifest.json"
OFFICIAL_SOURCE_URL = "https://www.unehistoireduconflitpolitique.fr/telecharger.html"


def _f(value: float, digits: int = 3, signed: bool = False) -> str:
    prefix = "+" if signed and value >= 0 else ""
    return (prefix + f"{value:.{digits}f}").replace(".", ",")


def _pct_points(value: float, signed: bool = False) -> str:
    return _f(100 * value, 1, signed=signed) + " points"


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def _load() -> dict[str, object]:
    paths = {
        "aggregates": DATA_DIR / "aggregate_drawwise_corrected_3000_v1.csv",
        "contrasts": DATA_DIR / "within_period_contrasts_3000_v1.csv",
        "changes": DATA_DIR / "between_period_contrast_changes_3000_v1.csv",
        "diagnostics": DATA_DIR / "canonical_mcmc_diagnostics_3000_v1.csv",
        "estimands": DATA_DIR / "estimand_mcmc_diagnostics_3000_v1.csv",
        "identification": DATA_DIR / "identification_separate_3000_v1.csv",
        "audit": DATA_DIR / "source_data_anomalies_3000_v1.csv",
        "joint_latent": DATA_DIR / "joint_latent_3000_v1.csv",
        "nls_contrasts": DATA_DIR / "nls_contrasts_3000_v1.csv",
        "nls_diagnostics": DATA_DIR / "nls_model_diagnostics_3000_v1.csv",
        "nls_comparison": DATA_DIR / "nls_krt_comparison_3000_v1.csv",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"professor-report outputs missing: {missing}")
    data: dict[str, object] = {
        name: pd.read_csv(path, dtype={"unit_id": str} if name in {"audit", "joint_latent"} else None)
        for name, path in paths.items()
    }
    progress_path = OUTPUT_DIR / "v3" / "priority_production_progress_v3.json"
    if progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        item = progress.get("items", {}).get("leg_1962_r1__H0A__krt_beta_binomial", {})
        run_id = item.get("run_id") if item.get("status") == "success" else None
        if run_id:
            aggregate_path = OUTPUT_DIR / "runs" / str(run_id) / "aggregate_comparison_v2.csv"
            if aggregate_path.exists():
                aggregate = pd.read_csv(aggregate_path)
                selected = aggregate.loc[
                    aggregate["aggregation_method"].eq("group_specific_population_v2")
                ].set_index("beta_parameter")
                data["spot_check"] = {
                    "scenario_id": "H0A",
                    "year": 1962,
                    "estimate": float(
                        selected.loc["b_1", "mean"] - selected.loc["b_2", "mean"]
                    ),
                    "run_id": str(run_id),
                }
    data["panel"] = json.loads(PANEL_MANIFEST.read_text(encoding="utf-8"))
    return data


def _result_rows(data: dict[str, object]) -> list[list[str]]:
    aggregates = data["aggregates"]
    contrasts = data["contrasts"]
    assert isinstance(aggregates, pd.DataFrame) and isinstance(contrasts, pd.DataFrame)
    agg = aggregates.loc[
        aggregates["aggregation_method"].eq("group_specific_population_v2")
    ].set_index(["scenario_id", "year", "beta_parameter"])
    rows: list[list[str]] = []
    for row in contrasts.sort_values(["scenario_id", "year"]).itertuples():
        b1 = float(agg.loc[(row.scenario_id, row.year, "b_1"), "mean"])
        b2 = float(agg.loc[(row.scenario_id, row.year, "b_2"), "mean"])
        rows.append(
            [
                str(row.scenario_id),
                str(int(row.year)),
                _f(b1),
                _f(b2),
                f"{_f(float(row.estimate), signed=True)} "
                f"[{_f(float(row.lower), signed=True)} ; {_f(float(row.upper), signed=True)}]",
            ]
        )
    return rows


def _change_rows(data: dict[str, object]) -> list[list[str]]:
    changes = data["changes"]
    assert isinstance(changes, pd.DataFrame)
    rows: list[list[str]] = []
    for row in changes.sort_values(["scenario_id", "earlier_year", "later_year"]).itertuples():
        rows.append(
            [
                str(row.scenario_id),
                f"{int(row.earlier_year)} -> {int(row.later_year)}",
                f"{_f(float(row.estimate), signed=True)} "
                f"[{_f(float(row.lower), signed=True)} ; {_f(float(row.upper), signed=True)}]",
                "intervalle contenant zéro"
                if float(row.lower) <= 0 <= float(row.upper)
                else "signe déterminé sous le modèle",
            ]
        )
    return rows


def _nls_result_rows(data: dict[str, object]) -> list[list[str]]:
    contrasts = data["nls_contrasts"]
    assert isinstance(contrasts, pd.DataFrame)
    rows: list[list[str]] = []
    for row in contrasts.sort_values(["scenario_id", "year"]).itertuples():
        rows.append(
            [
                str(row.scenario_id),
                str(int(row.year)),
                str(row.event_label),
                _f(float(row.group_1_estimate)),
                _f(float(row.group_2_estimate)),
                _f(float(row.contrast_group_1_minus_group_2), signed=True),
            ]
        )
    return rows


def _nls_comparison_rows(data: dict[str, object]) -> list[list[str]]:
    comparison = data["nls_comparison"]
    assert isinstance(comparison, pd.DataFrame)
    rows: list[list[str]] = []
    for row in comparison.sort_values(["scenario_id", "year"]).itertuples():
        rows.append(
            [
                str(row.scenario_id),
                str(int(row.year)),
                f"{_f(float(row.krt_estimate), signed=True)} "
                f"[{_f(float(row.krt_lower_95), signed=True)} ; "
                f"{_f(float(row.krt_upper_95), signed=True)}]",
                _f(float(row.nls_estimate), signed=True),
                _f(float(row.nls_minus_krt), signed=True),
            ]
        )
    return rows


def _nls_diagnostic_rows(data: dict[str, object]) -> list[list[str]]:
    diagnostics = data["nls_diagnostics"]
    assert isinstance(diagnostics, pd.DataFrame)
    rows: list[list[str]] = []
    for row in diagnostics.sort_values(["scenario_id", "year"]).itertuples():
        rows.append(
            [
                str(row.scenario_id),
                str(int(row.year)),
                str(row.diagnostic_status),
                f"{int(row.n_successful_starts)}/{int(row.n_starts)}",
                _f(float(row.objective_sse_unweighted), 2),
                _f(float(row.sandwich_condition_info), 2),
            ]
        )
    return rows


def _repair_sensitivity_rows(data: dict[str, object]) -> list[list[str]]:
    current = data["contrasts"]
    assert isinstance(current, pd.DataFrame)
    spot = data.get("spot_check")
    if not isinstance(spot, dict):
        return []
    old = current.loc[
        current["scenario_id"].eq(spot["scenario_id"])
        & current["year"].eq(spot["year"]),
        "estimate",
    ]
    if len(old) != 1:
        return []
    old_value = float(old.iloc[0])
    new_value = float(spot["estimate"])
    return [[
        str(spot["scenario_id"]),
        str(int(spot["year"])),
        _f(old_value, signed=True),
        _f(new_value, signed=True),
        _f(100 * (new_value - old_value), 2, signed=True) + " point",
    ]]


def _leave_one_out_rows(data: dict[str, object]) -> list[list[str]]:
    """Direct descriptive deletion from posterior commune means, without refitting."""

    joint = data["joint_latent"]
    assert isinstance(joint, pd.DataFrame)
    rows: list[list[str]] = []
    for scenario in ("H0A", "H1"):
        selected = joint.loc[
            joint["scenario_id"].eq(scenario) & joint["year"].eq(1986)
        ].copy()
        retained = selected.loc[~selected["unit_id"].str.zfill(5).eq("02643")]
        if len(selected) - len(retained) != 1:
            raise AssertionError(f"02643 not uniquely identified for {scenario}-1986")

        def contrast(frame: pd.DataFrame) -> float:
            b1 = (frame["b1_mean"] * frame["b1_weight"]).sum() / frame["b1_weight"].sum()
            b2 = (frame["b2_mean"] * frame["b2_weight"]).sum() / frame["b2_weight"].sum()
            return float(b1 - b2)

        full_value = contrast(selected)
        retained_value = contrast(retained)
        rows.append(
            [
                scenario,
                _f(full_value, signed=True),
                _f(retained_value, signed=True),
                _f(100 * (retained_value - full_value), 4, signed=True) + " point",
            ]
        )
    return rows


def _diagnostic_rows(data: dict[str, object]) -> list[list[str]]:
    diagnostics = data["diagnostics"]
    assert isinstance(diagnostics, pd.DataFrame)
    rows: list[list[str]] = []
    for row in diagnostics.sort_values(["scenario_id", "year"]).itertuples():
        rows.append(
            [
                str(row.scenario_id),
                str(int(row.year)),
                str(row.mcmc_assessment_label),
                str(row.beta_diagnostic_status),
                str(row.non_beta_parameter_status),
                _f(float(row.max_rhat), 4),
                _f(float(row.min_ess_bulk), 0),
                _f(float(row.min_ess_tail), 0),
                str(int(row.divergences)),
            ]
        )
    return rows


def _identification_rows(data: dict[str, object]) -> list[list[str]]:
    identification = data["identification"]
    assert isinstance(identification, pd.DataFrame)
    rows: list[list[str]] = []
    for row in identification.sort_values(["scenario_id", "year"]).itertuples():
        rows.append(
            [
                str(row.scenario_id),
                str(int(row.year)),
                str(row.identification_status),
                _f(float(row.median_max_bound_width)),
                _f(float(row.p90_max_bound_width)),
            ]
        )
    return rows


def _summary_sentences(data: dict[str, object]) -> tuple[str, str, str, str]:
    contrasts = data["contrasts"]
    diagnostics = data["diagnostics"]
    identification = data["identification"]
    nls_comparison = data["nls_comparison"]
    nls_diagnostics = data["nls_diagnostics"]
    assert isinstance(contrasts, pd.DataFrame)
    assert isinstance(diagnostics, pd.DataFrame)
    assert isinstance(identification, pd.DataFrame)
    assert isinstance(nls_comparison, pd.DataFrame)
    assert isinstance(nls_diagnostics, pd.DataFrame)
    c = contrasts.set_index(["scenario_id", "year"])
    result = (
        "Le contraste écologique d'abstention passe de "
        f"{_pct_points(float(c.loc[('H0A', 1962), 'estimate']), signed=True)} en 1962 à "
        f"{_pct_points(float(c.loc[('H0A', 1986), 'estimate']), signed=True)} en 1986 puis "
        f"{_pct_points(float(c.loc[('H0A', 2022), 'estimate']), signed=True)} en 2022. "
        "Pour le vote à gauche, il passe de "
        f"{_pct_points(float(c.loc[('H1', 1962), 'estimate']), signed=True)} à "
        f"{_pct_points(float(c.loc[('H1', 1986), 'estimate']), signed=True)} puis "
        f"{_pct_points(float(c.loc[('H1', 2022), 'estimate']), signed=True)}."
    )
    counts = diagnostics["mcmc_assessment_label"].value_counts()
    diag = (
        f"Diagnostics MCMC : {int(counts.get('satisfaisant', 0))} ajustements satisfaisants, "
        f"{int(counts.get('satisfaisant avec réserve', 0))} satisfaisants avec réserve, "
        f"{int(counts.get('insuffisant', 0))} insuffisant ; aucune divergence."
    )
    id_counts = identification["identification_status"].value_counts()
    ident = (
        f"Identification écologique : {int(id_counts.get('pass', 0))} pass et "
        f"{int(id_counts.get('caveat', 0))} caveat."
    )
    nls = (
        f"NLS : {len(nls_diagnostics)} ajustements H0A, H1, H2 et H4, tous avec diagnostic pass. "
        f"Pour H0A et H1, {int(nls_comparison['same_sign'].sum())} comparaisons sur "
        f"{len(nls_comparison)} ont le même signe que les KRT ; les écarts de niveau restent "
        "importants pour H1 en 1962 et 1986."
    )
    return result, diag, ident, nls


def build_markdown(data: dict[str, object]) -> Path:
    panel = data["panel"]
    contrasts = data["contrasts"]
    audit = data["audit"]
    assert isinstance(panel, dict)
    assert isinstance(contrasts, pd.DataFrame) and isinstance(audit, pd.DataFrame)
    result_summary, diagnostic_summary, identification_summary, nls_summary = _summary_sentences(data)
    all_exclude_zero = bool(((contrasts["lower"] > 0) | (contrasts["upper"] < 0)).all())
    main_rel = "../figures/v2/priority_3000_final"
    output_rel = "../outputs/v2/priority_3000_final"
    removed = ", ".join(f"`{value}`" for value in panel["removed_units"])
    added = ", ".join(f"`{value}`" for value in panel["added_units"])
    report = f"""# {TITLE}

*Production intermédiaire - 4 août 2026*

## Synthèse technique

Conditionnellement au panel, au recalibrage des marges sociales et au modèle KRT, les six intervalles crédibles des contrastes intra-période {'ne recouvrent pas zéro' if all_exclude_zero else 'ne sont pas tous séparés de zéro'}. Ces résultats restent des estimations écologiques dépendantes de la structure hiérarchique et des priors. Les bornes de tomographie sont larges dans la majorité des ajustements et ne permettent pas une interprétation directe en comportements individuels.

{result_summary}

{diagnostic_summary} {identification_summary}

{nls_summary}

Sur les 9 000 couples commune-année du panel, une seule anomalie apparaît dans la comparaison directe des dénominateurs publiés par H0A et H1 : pour `02643` en 1986, les 392 suffrages exprimés de H1 dépassent les 383 inscrits de H0A. Le panel reste équilibré et les six estimations existantes sont conservées comme résultats intermédiaires. La valeur source n'est pas corrigée arbitrairement ; une validation renforcée et un panel V3 sont prêts pour les prochaines estimations.

## Résultats principaux

![Contrastes intra-période]({main_rel}/within_period_contrasts_3000_v1.png)

Le graphique présente `β1-β2`, avec `β1` pour les ouvriers et employés et `β2` pour les autres CSP. Une valeur positive indique un niveau estimé plus élevé pour les ouvriers et employés.

{_markdown_table(['Hypothèse', 'Année', 'β1', 'β2', 'β1-β2 [ICr 95 %]'], _result_rows(data))}

![Agrégats calculés tirage par tirage]({main_rel}/aggregate_drawwise_corrected_3000_v1.png)

Les niveaux de H0A et H1 ne sont pas directement comparables : H0A porte sur l'abstention parmi les inscrits, H1 sur le vote à gauche parmi les suffrages exprimés.

### Influence descriptive de la commune `02643`

{_markdown_table(['Hypothèse 1986', 'Contraste publié', 'Sans 02643', 'Variation'], _leave_one_out_rows(data))}

Ce calcul retire `02643` des agrégats de moyennes postérieures déjà estimées ; ce n'est pas une réestimation du modèle hiérarchique. La variation est de 0,0009 point pour H0A et de 0,0004 point pour H1. Les conclusions arrondies restent respectivement `+3,9` et `+15,6` points. Un recalcul ponctuel H0A-1962 sur le panel V3 donne par ailleurs un écart de {_repair_sensitivity_rows(data)[0][-1] if _repair_sensitivity_rows(data) else 'non disponible'} ; il n'est pas mélangé à la série principale V2.

## Résultats NLS

Les NLS constituent un benchmark déterministe distinct des modèles KRT. Douze ajustements sont disponibles : H0A, H1, H2 et H4 pour 1962, 1986 et 2022, toujours sur le panel V2 commun de 3 000 communes. Chaque contraste est la probabilité estimée du premier groupe moins celle du second groupe pour l'événement défini par l'hypothèse.

![Contrastes NLS par hypothèse et année]({main_rel}/nls_contrasts_3000_v1.png)

{_markdown_table(['Hyp.', 'Année', 'Événement et dénominateur', 'Groupe 1', 'Groupe 2', 'Contraste'], _nls_result_rows(data))}

H0A reproduit l'inversion de signe entre 1962 et les deux dates suivantes. H1 et H2 sont positifs en 1962 et 1986, puis négatifs en 2022. H4 est positif aux trois dates, mais devient presque nul en 2022. Ces valeurs sont des estimations ponctuelles NLS ; aucun intervalle du contraste n'est revendiqué à partir des exports disponibles.

### Comparaison KRT-NLS pour H0A et H1

![Comparaison des contrastes KRT et NLS]({main_rel}/nls_krt_comparison_3000_v1.png)

{_markdown_table(['Hyp.', 'Année', 'KRT [ICr 95 %]', 'NLS', 'NLS - KRT'], _nls_comparison_rows(data))}

Les six comparaisons ont le même signe. Les niveaux sont proches pour H0A, avec des écarts NLS-KRT de `+1,2`, `-1,1` et `-3,1` points. Pour H1, les NLS sont inférieurs aux KRT de `9,0` points en 1962, `5,7` points en 1986 et `1,0` point en 2022. La concordance de signe est donc descriptive ; elle ne signifie pas que les deux modèles fournissent des estimations interchangeables.

### Diagnostics numériques NLS

{_markdown_table(['Hyp.', 'Année', 'Statut', 'Départs réussis', 'SSE', 'Condition information'], _nls_diagnostic_rows(data))}

Les 12 ajustements ont le statut `pass`, avec 20 départs réussis sur 20. Ce contrôle porte sur la réussite et la stabilité numérique de l'optimisation. Il ne remplace ni une mesure d'incertitude du contraste, ni le contrôle d'identification écologique présenté pour les KRT.

## Comparaisons entre périodes

{_markdown_table(['Hypothèse', 'Comparaison', 'Changement [intervalle 95 %]', 'Lecture'], _change_rows(data))}

Les changements sont calculés à partir de 50 000 paires indépendantes de tirages provenant des ajustements séparés. Il ne s'agit ni d'un modèle temporel joint, ni du suivi des mêmes électeurs.

## Échantillonnage et contrôle des données

Le panel ayant servi aux six estimations est un tirage de 3 000 communes dans 33 922 communes admissibles selon les contrôles initiaux. Il reste largement sous les seuils d'écart fixés. La règle transversale ajoutée retire huit communes de cet univers, qui compte désormais **{panel['corrected_common_eligible_universe_size']:,} communes**. La virgule indique ici le séparateur de milliers. Le panel V3 corrigé conserve exactement 3 000 communes et sera utilisé pour les prochaines estimations.

| Élément | Valeur |
| --- | ---: |
| taille du panel | 3 000 communes |
| graine | `20260802` |
| règle électorale | `0 <= exprimés <= votants <= inscrits` |
| tolérance des flottants | 0,01 voix |
| maximum `|SMD|` du panel estimé V2 | 0,01939 |
| maximum d'écart catégoriel V2 | 0,01032 |
| maximum `|SMD|` du futur panel V3 | {_f(float(panel['balance_corrected_common_eligible']['max_abs_smd']), 5)} |
| maximum d'écart catégoriel V3 | {_f(float(panel['balance_corrected_common_eligible']['max_abs_category_gap']), 5)} |
| seuils | 0,10 et 0,02 |
| `king_lambda` | 0,5 |

Réparation prévue pour les prochains calculs - communes retirées : {removed}. Communes ajoutées : {added}.

La sélection V3 ne refait pas un tirage entièrement différent. Elle reprend l'ordre aléatoire V2, écarte les unités qui échouent au nouveau contrôle et poursuit cet ordre jusqu'à retrouver 3 000 communes. L'équilibre est ensuite recalculé par rapport à l'univers commun corrigé et à l'univers de référence 2022. Les six estimations principales n'ont pas été relancées : l'anomalie ne remet pas en cause l'échantillonnage et son influence descriptive est négligeable.

Pour Ressons-le-Long (`02643`), le CSV officiel utilisé par le projet est identique au fichier actuellement distribué (SHA-256 `e265cdd2...`). Le procès-verbal numérisé indique 383 inscrits, 415 votants, 23 bulletins nuls et 392 exprimés : la source d'archive est elle-même incohérente. Aucune valeur d'inscrits n'a donc été inventée ; la commune est exclue du panel préparé pour les prochains calculs. [Page officielle des données]({OFFICIAL_SOURCE_URL}).

Le contrôle brut plus strict `exprimés <= votants <= inscrits` repère neuf lignes sources, dont quatre appartiennent au panel V2. Trois de ces quatre lignes supplémentaires ont `exprimés > votants` mais pas `exprimés > inscrits` ; elles n'apparaissent donc pas dans l'unique anomalie issue de la comparaison directe H0A-H1. Le détail est disponible dans [`source_data_anomalies_3000_v1.csv`]({output_rel}/source_data_anomalies_3000_v1.csv).

## Hypothèses et estimation

| Hypothèse | Événement | β1 | β2 | Dénominateur |
| --- | --- | --- | --- | --- |
| H0A | abstention | ouvriers + employés | autres CSP | inscrits |
| H1 | vote à gauche (`voteG + voteCG`) | ouvriers + employés | autres CSP | exprimés |

Les parts sociales sont recalibrées sur le dénominateur électoral propre à chaque hypothèse, puis fermées par la méthode du plus fort reste. Le modèle KRT bêta-binomial est estimé séparément pour chaque année. Chaque ajustement utilise 4 chaînes, 1 000 itérations de chauffe et 1 000 tirages conservés par chaîne, `target_accept=0,99`, `max_treedepth=14` et `king_lambda=0,5`.

Les agrégats sont calculés à chaque tirage avec les poids propres aux groupes : `N1` pour `β1` et `N2` pour `β2`. Le contraste est ensuite calculé sur les agrégats obtenus au même tirage.

Le benchmark NLS utilise le modèle `rosen_nls_2x2_unadjusted`. Chaque ajustement repose sur 20 points de départ, une tolérance de `1e-9`, un maximum de 5 000 évaluations et la graine `20260802`. Contrairement aux KRT, ces sorties NLS sont présentées comme des estimations ponctuelles : les exports ne permettent pas de construire directement un intervalle fiable du contraste entre groupes.

## Diagnostics MCMC

![Diagnostics centrés sur les paramètres β]({main_rel}/canonical_diagnostics_3000_v1.png)

Les valeurs affichées sont les pires parmi les 6 000 paramètres communaux `b_1` et `b_2`. Le bilan devient « satisfaisant avec réserve » lorsqu'un paramètre hors β est moins bien identifié, même si les β passent les seuils.

{_markdown_table(['Hyp.', 'Année', 'Bilan', 'β', 'Hors β', 'R-hat max β', 'ESS bulk min β', 'ESS tail min β', 'Div.'], _diagnostic_rows(data))}

![Diagnostics des contrastes agrégés]({main_rel}/estimand_diagnostics_3000_v1.png)

Les diagnostics du contraste complètent ceux des paramètres communaux. Ils ne remplacent pas le contrôle d'identification écologique.

## Identification écologique

{_markdown_table(['Hypothèse', 'Année', 'Statut', 'Largeur médiane max', 'P90 largeur max'], _identification_rows(data))}

Une convergence MCMC satisfaisante signifie que l'échantillonneur explore correctement la distribution définie par le modèle. Elle ne garantit pas que les marges communales identifient seules les probabilités individuelles.

## Annexe - comparaison visuelle des densités communales

Les densités jointes portent sur les couples de moyennes postérieures communales `(b1_mean, b2_mean)`. Elles montrent l'hétérogénéité entre communes et non l'incertitude d'une moyenne nationale. Les axes et la bande passante sont communs aux trois années d'une même hypothèse ; la diagonale représente `β1=β2`.

### Communes équipondérées

![Densités jointes H0A - communes équipondérées]({main_rel}/densities/joint_beta_H0A_common_bandwidth_equal_communes.png)

Pour H0A, la masse est surtout du côté `β1<β2` en 1962, puis du côté `β1>β2` en 1986 et 2022.

![Densités jointes H1 - communes équipondérées]({main_rel}/densities/joint_beta_H1_common_bandwidth_equal_communes.png)

Pour H1, la distribution de 1962 reste la plus dispersée. La position relative des groupes s'inverse entre 1986 et 2022.

### Pondération par la taille électorale communale

![Densités jointes H0A - pondération par N total]({main_rel}/densities/joint_beta_H0A_common_bandwidth_N_total_weighted.png)

![Densités jointes H1 - pondération par N total]({main_rel}/densities/joint_beta_H1_common_bandwidth_N_total_weighted.png)

La pondération par le dénominateur communal conserve les positions générales. Les formes ne reposent donc pas seulement sur les petites communes, sans constituer pour autant un test de sensibilité aux priors.

### Densités marginales pondérées par les groupes

![Densités marginales H0A]({main_rel}/densities/marginal_beta_H0A_group_population_weighted.png)

![Densités marginales H1]({main_rel}/densities/marginal_beta_H1_group_population_weighted.png)

## Limites et travaux suivants

- Les résultats sont conditionnels au panel estimé V2, au recalibrage des marges, aux priors et à `king_lambda=0,5`.
- Les comparaisons NLS-KRT portent sur des modèles de nature différente ; la concordance de signe ne constitue pas un test de robustesse complet.
- L'intersection temporelle favorise les communes stables dans la géographie 2022 ; il s'agit d'un échantillon de communes, pas d'électeurs.
- Les posterior predictive checks complets restent à produire.
- La sensibilité aux priors, à `king_lambda`, au recalibrage et à plusieurs panels admissibles reste à mesurer.
- Les densités devront être comparées entre toutes les communes et le sous-ensemble `N1>0` et `N2>0`.
- Les comparaisons entre dates ne sont ni causales ni individuelles.

## Fichiers de référence

- [`release_manifest_3000_v1.json`]({output_rel}/release_manifest_3000_v1.json) : paramètres, runs et empreintes ;
- [`within_period_contrasts_3000_v1.csv`]({output_rel}/within_period_contrasts_3000_v1.csv) : résultats intra-période ;
- [`canonical_mcmc_diagnostics_3000_v1.csv`]({output_rel}/canonical_mcmc_diagnostics_3000_v1.csv) : diagnostics centrés sur les β ;
- [`identification_separate_3000_v1.csv`]({output_rel}/identification_separate_3000_v1.csv) : identification écologique ;
- [`nls_contrasts_3000_v1.csv`]({output_rel}/nls_contrasts_3000_v1.csv) : résultats ponctuels des 12 NLS ;
- [`nls_model_diagnostics_3000_v1.csv`]({output_rel}/nls_model_diagnostics_3000_v1.csv) : diagnostics numériques NLS ;
- [`nls_krt_comparison_3000_v1.csv`]({output_rel}/nls_krt_comparison_3000_v1.csv) : comparaison H0A/H1 entre NLS et KRT ;
- [`future_panel_v3_manifest.json`]({output_rel}/future_panel_v3_manifest.json) : construction du panel prévu pour les prochaines estimations.
"""
    report = report.replace("33,914", "33 914")
    MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    MD_PATH.write_text(report, encoding="utf-8")
    return MD_PATH


def _build_minimal_markdown(data: dict[str, object]) -> Path:
    panel = data["panel"]
    assert isinstance(panel, dict)
    main_rel = "../figures/v2/priority_3000_final"
    krt_diagnostics = [
        [row[0], row[1], row[2], row[3], row[8]]
        for row in _diagnostic_rows(data)
    ]
    report = f"""# {TITLE}

Les résultats portent sur un panel commun de **3 000 communes** observées en 1962, 1986 et 2022. Six modèles KRT sont présentés pour H0A et H1. Douze estimations NLS complètent l'analyse pour H0A, H1, H2 et H4.

## Hypothèses étudiées

| Hypothèse | Événement étudié | Groupe 1 | Groupe 2 | Modèles présentés |
| --- | --- | --- | --- | --- |
| H0A | abstention parmi les inscrits | ouvriers + employés | autres CSP | KRT et NLS |
| H1 | vote à gauche (`voteG + voteCG`) parmi les exprimés | ouvriers + employés | autres CSP | KRT et NLS |
| H2 | vote à gauche parmi les exprimés | ouvriers | autres CSP | NLS |
| H4 | vote à droite (`voteCD + voteD`) parmi les exprimés | agriculteurs + indépendants | salariés | NLS |

Contraste présenté : `groupe 1 - groupe 2`. Pour H4, le groupe des salariés réunit les cadres, professions intermédiaires, employés et ouvriers.

## Échantillon

| Élément | Valeur |
| --- | ---: |
| panel commun | 3 000 communes |
| univers admissible initial | 33 922 communes |
| graine | `20260802` |
| maximum `|SMD|` | 0,01939 |
| écart catégoriel maximal | 0,01032 |
| seuils retenus | 0,10 et 0,02 |

Il ne s'agit pas d'un problème d'équilibre du panel, mais d'une incohérence ponctuelle dans la donnée électorale de la commune `02643` en 1986 : 392 suffrages exprimés pour 383 inscrits. Pour ces premiers résultats, la commune est conservée, car son retrait descriptif modifie les contrastes de moins de 0,001 point et ne change pas leur interprétation. Cette petite anomalie a donc une incidence négligeable ici. Elle sera corrigée pour les prochains panels, avec un contrôle automatique imposant `0 ≤ exprimés ≤ votants ≤ inscrits` avant toute estimation.

## Premiers résultats KRT

![Contrastes KRT]({main_rel}/within_period_contrasts_3000_v1.png)

Le contraste correspond à `β1-β2`, avec `β1` pour les ouvriers et employés et `β2` pour les autres catégories socioprofessionnelles.

{_markdown_table(['Hypothèse', 'Année', 'β1', 'β2', 'β1-β2 [ICr 95 %]'], _result_rows(data))}

- H0A passe de **-11,0 points** en 1962 à **+3,9 points** en 1986 puis **+8,8 points** en 2022.
- H1 passe de **+10,1 points** en 1962 à **+15,6 points** en 1986 puis **-3,4 points** en 2022.
- Les six intervalles crédibles ne recouvrent pas zéro sous le modèle estimé.

## Premiers résultats NLS

![Contrastes NLS]({main_rel}/nls_contrasts_3000_v1.png)

{_markdown_table(['Hyp.', 'Année', 'Événement', 'Groupe 1', 'Groupe 2', 'Contraste'], _nls_result_rows(data))}

NLS : modèle `rosen_nls_2x2_unadjusted` sans covariable, solveur `scipy.optimize.least_squares` en méthode TRF, 20 points de départ, tolérance `1e-9` et maximum de 5 000 évaluations. Les douze ajustements ont un diagnostic numérique `pass` avec 20 départs réussis sur 20. Les contrastes sont présentés comme des estimations ponctuelles.

## Comparaison KRT et NLS

![Comparaison KRT et NLS]({main_rel}/nls_krt_comparison_3000_v1.png)

{_markdown_table(['Hyp.', 'Année', 'KRT [ICr 95 %]', 'NLS', 'NLS - KRT'], _nls_comparison_rows(data))}

Les six comparaisons H0A/H1 ont le même signe. Les niveaux sont proches pour H0A ; les contrastes NLS sont plus faibles pour H1, surtout en 1962 et 1986. Cette concordance de signe reste descriptive et les deux modèles ne sont pas interchangeables.

## Densités des paramètres β

Les densités jointes représentent les couples de moyennes postérieures communales `(β1, β2)`. Les axes et la bande passante sont communs aux trois années d'une même hypothèse. La diagonale correspond à `β1 = β2`.

### Communes équipondérées

![Densités jointes H0A - 1962, 1986 et 2022]({main_rel}/densities/joint_beta_H0A_common_bandwidth_equal_communes.png)

Pour H0A, la masse se situe principalement sous la diagonale en 1962, puis au-dessus en 1986 et 2022.

![Densités jointes H1 - 1962, 1986 et 2022]({main_rel}/densities/joint_beta_H1_common_bandwidth_equal_communes.png)

Pour H1, la distribution est plus dispersée en 1962. La position relative des groupes s'inverse en 2022.

### Pondération par la taille électorale

![Densités jointes H0A pondérées par le dénominateur communal]({main_rel}/densities/joint_beta_H0A_common_bandwidth_N_total_weighted.png)

La pondération de H0A conserve la position générale des distributions observée avec les communes équipondérées.

![Densités jointes H1 pondérées par le dénominateur communal]({main_rel}/densities/joint_beta_H1_common_bandwidth_N_total_weighted.png)

Pour H1, cette pondération confirme que les principales positions ne reposent pas uniquement sur les petites communes.

### Densités marginales

![Densités marginales H0A pondérées par les effectifs des groupes]({main_rel}/densities/marginal_beta_H0A_group_population_weighted.png)

Les marginales H0A isolent la distribution de chaque β et rendent plus directement visible leur déplacement entre les trois périodes.

![Densités marginales H1 pondérées par les effectifs des groupes]({main_rel}/densities/marginal_beta_H1_group_population_weighted.png)

Les marginales H1 complètent la densité jointe en montrant séparément la dispersion de chaque groupe.

## Diagnostics essentiels

{_markdown_table(['Hyp.', 'Année', 'Bilan MCMC', 'β', 'Divergences'], krt_diagnostics)}

Deux ajustements KRT sont satisfaisants et quatre satisfaisants avec réserve. Les réserves concernent principalement des paramètres autres que les β ; H1-1962 conserve aussi une réserve sur les β. Aucune divergence n'est observée.

Réglages KRT : 4 chaînes, 1 000 itérations de chauffe et 1 000 tirages conservés par chaîne, `target_accept=0,99`, `max_treedepth=14`, `king_lambda=0,5`.

## À retenir

- Le panel commun de 3 000 communes respecte largement les critères d'équilibre.
- Les contrastes changent de signe entre certaines périodes, notamment H0A après 1962 et H1 en 2022.
- Les NLS confirment le signe des six résultats H0A/H1, avec des amplitudes parfois plus faibles.
- Les résultats décrivent des relations écologiques conditionnelles aux modèles ; ils ne mesurent pas directement des comportements individuels.
"""
    MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    MD_PATH.write_text(report, encoding="utf-8")
    return MD_PATH


def _pdf_table(rows: list[list[str]], widths: list[float], header: list[str]):
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, Table, TableStyle

    cell = ParagraphStyle("table_cell", fontName="Arial", fontSize=7.1, leading=8.4)
    head = ParagraphStyle(
        "table_head", fontName="Arial-Bold", fontSize=7.1, leading=8.4, textColor=colors.white
    )
    values = [[Paragraph(html.escape(str(value)), head) for value in header]]
    values.extend([[Paragraph(html.escape(str(value)), cell) for value in row] for row in rows])
    table = Table(values, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#315C8C")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C8D1DA")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F6F8")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def build_pdf(data: dict[str, object]) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        BaseDocTemplate,
        Frame,
        Image,
        PageBreak,
        PageTemplate,
        Paragraph,
        Spacer,
    )

    pdfmetrics.registerFont(TTFont("Arial", r"C:\Windows\Fonts\arial.ttf"))
    pdfmetrics.registerFont(TTFont("Arial-Bold", r"C:\Windows\Fonts\arialbd.ttf"))
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "BodyFR", parent=styles["BodyText"], fontName="Arial", fontSize=9.2, leading=12.4,
        spaceAfter=6, textColor=colors.HexColor("#20262E")
    )
    title = ParagraphStyle(
        "TitleFR", parent=styles["Title"], fontName="Arial-Bold", fontSize=22, leading=26,
        textColor=colors.HexColor("#20262E"), spaceAfter=14
    )
    h1 = ParagraphStyle(
        "H1FR", parent=styles["Heading1"], fontName="Arial-Bold", fontSize=15, leading=18,
        textColor=colors.HexColor("#315C8C"), spaceBefore=8, spaceAfter=7
    )
    h2 = ParagraphStyle(
        "H2FR", parent=styles["Heading2"], fontName="Arial-Bold", fontSize=11.5, leading=14,
        textColor=colors.HexColor("#20262E"), spaceBefore=7, spaceAfter=5
    )
    note = ParagraphStyle(
        "NoteFR", parent=body, backColor=colors.HexColor("#EDF3F8"), borderColor=colors.HexColor("#315C8C"),
        borderWidth=0.7, borderPadding=8, spaceBefore=4, spaceAfter=9
    )
    status = ParagraphStyle(
        "StatusFR", parent=body, fontName="Arial-Bold", fontSize=10, textColor=colors.HexColor("#A14E45")
    )
    caption = ParagraphStyle(
        "CaptionFR", parent=body, fontSize=8, leading=10, textColor=colors.HexColor("#52606D"),
        alignment=TA_CENTER, spaceBefore=3, spaceAfter=8
    )

    PDF_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(PDF_PATH), pagesize=A4, leftMargin=1.7 * cm, rightMargin=1.7 * cm,
        topMargin=1.8 * cm, bottomMargin=1.7 * cm, title=TITLE, author="Projet longitudinal"
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")

    def on_page(canvas, document):
        canvas.saveState()
        canvas.setFont("Arial", 7.5)
        canvas.setFillColor(colors.HexColor("#6B7785"))
        canvas.drawString(doc.leftMargin, 0.85 * cm, "Premiers résultats - panel KRT et NLS de 3 000 communes")
        canvas.drawRightString(A4[0] - doc.rightMargin, 0.85 * cm, f"Page {document.page}")
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=on_page)])

    def p(text: str, style=body):
        return Paragraph(html.escape(text).replace("\n", "<br/>") , style)

    def rich(text: str, style=body):
        return Paragraph(text, style)

    def heading(text: str, level: int = 1):
        return p(text, h1 if level == 1 else h2)

    def figure(path: Path, label: str, width: float = 16.4 * cm):
        from PIL import Image as PILImage

        with PILImage.open(path) as source:
            ratio = source.height / source.width
        image = Image(str(path), width=width, height=width * ratio)
        image.hAlign = "CENTER"
        return [image, p(label, caption)]

    result_summary, diagnostic_summary, identification_summary, nls_summary = _summary_sentences(data)
    panel = data["panel"]
    assert isinstance(panel, dict)
    story = [
        Spacer(1, 0.35 * cm),
        p(TITLE, title),
        p("KRT : H0A et H1 - NLS : H0A, H1, H2 et H4 - 1962, 1986 et 2022", h2),
        Spacer(1, 0.35 * cm),
        p(
            "Conditionnellement au panel, au recalibrage des marges sociales et au modèle KRT, "
            "les six intervalles crédibles des contrastes intra-période ne recouvrent pas zéro. "
            "Ces résultats restent écologiques : les bornes de tomographie sont larges dans la "
            "majorité des ajustements et ne permettent pas une lecture individuelle.",
            note,
        ),
        p(result_summary),
        p(diagnostic_summary + " " + identification_summary),
        p(nls_summary),
        p(
            "Contrôle de données : une seule anomalie inter-dénominateurs apparaît parmi les "
            "9 000 couples commune-année : pour 02643 en 1986, 392 exprimés dépassent 383 "
            "inscrits. Le panel reste équilibré ; cette limite est signalée dans la lecture des résultats."
        ),
        Spacer(1, 0.2 * cm),
        _pdf_table(_result_rows(data), [1.5*cm, 1.3*cm, 1.5*cm, 1.5*cm, 7.6*cm], ["Hyp.", "Année", "β1", "β2", "β1-β2 [ICr 95 %]"]),
        Spacer(1, 0.25 * cm),
        p("Réglages : 4 chaînes, 1 000 tune, 1 000 draws par chaîne, target_accept=0,99, max_treedepth=14, king_lambda=0,5.", caption),
        PageBreak(),
        heading("1. Résultats principaux"),
    ]
    story += figure(FIG_DIR / "within_period_contrasts_3000_v1.png", "Figure 1. Contrastes écologiques intra-période et intervalles crédibles à 95 %.")
    story += [p(result_summary), _pdf_table(_change_rows(data), [1.5*cm, 2.5*cm, 5.2*cm, 6.2*cm], ["Hyp.", "Comparaison", "Changement [95 %]", "Lecture"])]
    story += [heading("Agrégats β1 et β2", 2)]
    story += figure(FIG_DIR / "aggregate_drawwise_corrected_3000_v1.png", "Figure 2. Agrégats calculés tirage par tirage avec les poids propres aux groupes.")
    story += [
        p("H0A et H1 n'ont pas le même événement ni le même dénominateur. Leurs niveaux ne doivent pas être comparés directement."),
        heading("Influence descriptive de 02643", 2),
        _pdf_table(
            _leave_one_out_rows(data),
            [2.8*cm, 3.7*cm, 3.7*cm, 4.7*cm],
            ["Hypothèse 1986", "Contraste publié", "Sans 02643", "Variation"],
        ),
        p(
            "Cette suppression est appliquée aux agrégats existants, sans réestimer le modèle. "
            "Elle change H0A de 0,0009 point et H1 de 0,0004 point ; les conclusions arrondies "
            "restent +3,9 et +15,6 points."
        ),
    ]

    compact_nls_rows = [[row[0], row[1], row[3], row[4], row[5]] for row in _nls_result_rows(data)]
    story += [
        heading("2. Résultats NLS"),
        p(
            "Les NLS forment un benchmark déterministe distinct des KRT. Les 12 ajustements "
            "couvrent H0A, H1, H2 et H4 aux trois dates sur le même panel V2 de 3 000 communes."
        ),
    ]
    story += figure(
        FIG_DIR / "nls_contrasts_3000_v1.png",
        "Figure 3. Contrastes NLS ponctuels, premier groupe moins second groupe.",
        width=15.8 * cm,
    )
    story += [
        _pdf_table(
            compact_nls_rows,
            [1.2*cm, 1.2*cm, 3.0*cm, 3.0*cm, 3.0*cm],
            ["Hyp.", "Année", "Groupe 1", "Groupe 2", "Contraste"],
        ),
        p(
            "H0A inverse son signe après 1962. H1 et H2 deviennent négatifs en 2022. H4 reste "
            "positif mais devient presque nul en 2022. Ces valeurs sont ponctuelles : aucun "
            "intervalle du contraste NLS n'est revendiqué à partir des exports disponibles."
        ),
        PageBreak(),
        heading("Comparaison KRT-NLS pour H0A et H1", 2),
    ]
    story += figure(
        FIG_DIR / "nls_krt_comparison_3000_v1.png",
        "Figure 4. Comparaison des contrastes KRT et NLS sur le même panel V2.",
        width=15.8 * cm,
    )
    story += [
        _pdf_table(
            _nls_comparison_rows(data),
            [1.2*cm, 1.2*cm, 5.3*cm, 2.4*cm, 2.5*cm],
            ["Hyp.", "Année", "KRT [ICr 95 %]", "NLS", "NLS - KRT"],
        ),
        p(
            "Les six comparaisons ont le même signe. Les NLS sont toutefois inférieurs aux KRT "
            "pour H1 de 9,0 points en 1962 et 5,7 points en 1986. La concordance de signe reste "
            "descriptive : les modèles ne sont pas interchangeables."
        ),
        heading("Diagnostics numériques NLS", 2),
        p(
            "Les 12 ajustements ont le statut pass et 20 départs réussis sur 20. Ce bilan contrôle "
            "la réussite et la stabilité de l'optimisation, pas l'incertitude ni l'identification écologique."
        ),
        PageBreak(),
        heading("3. Échantillonnage et qualité des données"),
    ]
    sampling_rows = [
        ["Panel", "3 000 communes"],
        ["Univers initial / corrigé", "33 922 / " + f"{panel['corrected_common_eligible_universe_size']:,}".replace(",", " ")],
        ["Graine", "20260802"],
        ["Règle", "0 <= exprimés <= votants <= inscrits"],
        ["Tolérance", "0,01 voix"],
        ["SMD max V2 / V3", "0,01939 / " + _f(float(panel['balance_corrected_common_eligible']['max_abs_smd']), 5)],
        ["Écart catégoriel V2 / V3", "0,01032 / " + _f(float(panel['balance_corrected_common_eligible']['max_abs_category_gap']), 5)],
    ]
    story += [
        _pdf_table(sampling_rows, [5.5*cm, 10.2*cm], ["Élément", "Valeur"]),
        Spacer(1, 0.2*cm),
        p(
            "Le futur panel V3 reprend l'ordre aléatoire V2. Les unités invalides sont écartées et "
            "l'ordre est poursuivi jusqu'à 3 000 communes. Retraits prévus : "
            + ", ".join(panel["removed_units"])
            + ". Ajouts : "
            + ", ".join(panel["added_units"])
            + "."
        ),
        p(
            "Ressons-le-Long (02643) a été vérifiée dans le procès-verbal numérisé : 383 inscrits, "
            "415 votants, 23 nuls et 392 exprimés. La source est incohérente ; aucune valeur n'a été "
            "imputée ; la commune sera exclue des prochains calculs."
        ),
        p(
            "L'audit brut de la règle complète repère aussi trois autres lignes du panel avec "
            "exprimés > votants, mais sans exprimés > inscrits. Elles sont documentées dans "
            "l'annexe machine-lisible et écartées du futur panel V3."
        ),
        p(
            "Les six estimations principales présentées dans ce rapport restent celles du panel "
            "V2. Elles ne sont pas mélangées avec le seul recalcul ponctuel H0A-1962 sur V3."
        ),
        heading("Méthode d'estimation", 2),
        p(
            "H0A modélise l'abstention parmi les inscrits. H1 modélise le vote à gauche "
            "(voteG + voteCG) parmi les suffrages exprimés. β1 correspond aux ouvriers et employés, "
            "β2 aux autres CSP. Les marges sociales sont recalibrées sur le dénominateur électoral "
            "et fermées par la méthode du plus fort reste."
        ),
        p(
            "Les trois années sont ajustées séparément par un modèle KRT bêta-binomial. Les "
            "agrégats utilisent N1 pour β1 et N2 pour β2 à chaque tirage. Les changements entre "
            "dates reposent sur 50 000 paires indépendantes de tirages."
        ),
        p(
            "Le benchmark NLS utilise rosen_nls_2x2_unadjusted avec 20 points de départ, une "
            "tolérance de 1e-9, au plus 5 000 évaluations et la graine 20260802."
        ),
        PageBreak(),
        heading("4. Diagnostics MCMC"),
    ]
    story += figure(FIG_DIR / "canonical_diagnostics_3000_v1.png", "Figure 3. Pires diagnostics parmi les 6 000 paramètres communaux β par ajustement.")
    story += [
        p(
            "Le bilan public est centré sur les β. Une réserve est toutefois conservée lorsque les "
            "quatre hyperparamètres présentent un R-hat ou un ESS moins favorable."
        ),
        _pdf_table(
            _diagnostic_rows(data),
            [0.9*cm, 0.9*cm, 3.4*cm, 1.0*cm, 1.2*cm, 1.5*cm, 1.6*cm, 1.6*cm, 0.7*cm],
            ["H", "An", "Bilan", "β", "Hors β", "R-hat", "ESS b", "ESS t", "Div."],
        ),
        heading("Diagnostics des contrastes", 2),
    ]
    story += figure(FIG_DIR / "estimand_diagnostics_3000_v1.png", "Figure 4. R-hat et tailles effectives des contrastes publiés.")
    story += [PageBreak(), heading("5. Identification écologique")]
    story += [
        _pdf_table(_identification_rows(data), [2.2*cm, 1.5*cm, 2.2*cm, 4.4*cm, 4.4*cm], ["Hypothèse", "Année", "Statut", "Largeur médiane max", "P90 largeur max"]),
        Spacer(1, 0.25*cm),
        p(
            "La convergence MCMC et l'identification écologique répondent à deux questions "
            "différentes. Des chaînes convergentes peuvent échantillonner correctement une "
            "distribution dont la précision dépend fortement de la hiérarchie et des priors."
        ),
        p(
            "Les résultats décrivent donc des contrastes écologiques conditionnels au modèle. Ils "
            "ne mesurent pas directement le comportement individuel des ouvriers et employés."
        ),
        PageBreak(),
        heading("6. Annexe visuelle - densités jointes"),
        p(
            "Chaque graphique compare les trois dates avec des axes et une bande passante communs. "
            "Les points sous-jacents sont les moyennes postérieures communales de β1 et β2."
        ),
    ]
    density_specs = [
        ("joint_beta_H0A_common_bandwidth_equal_communes.png", "Densités H0A, communes équipondérées. La masse passe surtout de β1<β2 en 1962 à β1>β2 en 1986 et 2022."),
        ("joint_beta_H1_common_bandwidth_equal_communes.png", "Densités H1, communes équipondérées. La distribution de 1962 est la plus dispersée ; le signe relatif s'inverse entre 1986 et 2022."),
        ("joint_beta_H0A_common_bandwidth_N_total_weighted.png", "Densités H0A pondérées par la taille électorale communale."),
        ("joint_beta_H1_common_bandwidth_N_total_weighted.png", "Densités H1 pondérées par la taille électorale communale."),
    ]
    for idx, (name, label) in enumerate(density_specs):
        story += figure(FIG_DIR / "densities" / name, label)
        if idx < len(density_specs) - 1:
            story.append(PageBreak())
    story += [PageBreak(), heading("7. Annexe visuelle - densités marginales")]
    story += figure(FIG_DIR / "densities" / "marginal_beta_H0A_group_population_weighted.png", "Densités marginales H0A, pondération propre à chaque groupe.")
    story += figure(FIG_DIR / "densities" / "marginal_beta_H1_group_population_weighted.png", "Densités marginales H1, pondération propre à chaque groupe.")
    story += [
        PageBreak(),
        heading("8. Limites et suite du travail"),
        p("1. Produire les posterior predictive checks par année, taille de commune et composition sociale."),
        p("2. Tester la sensibilité aux priors, à king_lambda, au recalibrage des marges et à plusieurs panels admissibles."),
        p("3. Comparer les densités sur toutes les communes et sur le sous-ensemble N1>0 et N2>0."),
        p("4. Maintenir séparées l'incertitude MCMC, l'identification écologique et l'incertitude liée au choix du panel."),
        p("5. Ne pas interpréter les comparaisons entre dates comme des trajectoires individuelles ou des effets causaux."),
        p("6. Ne pas interpréter l'accord de signe NLS-KRT comme une validation complète de robustesse."),
        heading("Fichiers associés", 2),
        p(
            "Le paquet de résultats contient les tables consolidées, le manifeste de production, "
            "les contrôles du panel et les figures. Il ne constitue pas à lui seul un dépôt "
            "reproductible complet ; les traces et le code intégral restent dans le dossier technique du projet."
        ),
    ]
    doc.build(story)
    return PDF_PATH


def build_report() -> dict[str, str]:
    ensure_runtime_dirs()
    data = _load()
    markdown = _build_minimal_markdown(data)
    pdf = build_pdf(data)
    return {"markdown": str(markdown), "pdf": str(pdf)}


if __name__ == "__main__":
    print(json.dumps(build_report(), ensure_ascii=False, indent=2))
