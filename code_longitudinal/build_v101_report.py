from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .paths import ROOT
from .utils import file_sha256


RELEASE_ROOT = ROOT / "work" / "longitudinal_2000_v1.0.1_H0A_H1_candidate"
RESULT_DIR = RELEASE_ROOT / "01_resultats_python"
SYNTHESIS_DIR = RELEASE_ROOT / "02_syntheses"
AUDIT_DIR = RELEASE_ROOT / "03_panel_et_audit"
FIGURE_DIR = RELEASE_ROOT / "04_figures_essentielles"
METHOD_DIR = RELEASE_ROOT / "05_methodologie_et_code"
REPORT_HTML = RELEASE_ROOT / "RAPPORT_TECHNIQUE_v1.0.1.html"
PAYLOAD_PATH = METHOD_DIR / "report_payload_v1.0.1.json"


def _read_optional_csv(name: str) -> pd.DataFrame:
    path = SYNTHESIS_DIR / name
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def _records(frame: pd.DataFrame, columns: list[str], digits: int = 4) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    result = frame.loc[:, [column for column in columns if column in frame]].copy()
    for column in result.select_dtypes(include="number"):
        result[column] = result[column].round(digits)
    return result.fillna("").to_dict("records")


def build_payload(*, ready: bool) -> dict[str, Any]:
    krt = pd.read_parquet(RESULT_DIR / "longitudinal_krt_aggregate.parquet")
    commune = pd.read_parquet(RESULT_DIR / "longitudinal_krt_commune.parquet")
    nls = pd.read_parquet(RESULT_DIR / "longitudinal_nls.parquet")
    coverage = pd.read_csv(AUDIT_DIR / "coverage_by_election_department.csv")
    dep54 = pd.read_csv(AUDIT_DIR / "department54_pre1988_rows.csv")
    rxc = pd.read_csv(AUDIT_DIR / "rxc_ineligible_audit.csv")
    canonical = pd.read_csv(SYNTHESIS_DIR / "canonical_run_selection.csv")
    sensitivity = _read_optional_csv("h1_panel_sensitivity.csv")
    sensitivity_nls = _read_optional_csv("h1_panel_sensitivity_nls_diagnostics.csv")
    targeted = _read_optional_csv("targeted_mcmc_reruns.csv")
    krt_nls = _read_optional_csv("krt_nls_comparison_h0a_h1.csv")
    nls_rep = _read_optional_csv("nls_python_r_replication_summary.csv")
    panel_validation = json.loads((AUDIT_DIR / "panel_exact_validation.json").read_text(encoding="utf-8"))

    krt_pairs = krt[["election_id", "scenario_id"]].drop_duplicates()
    nls_pairs = nls[["election_id", "scenario_id"]].drop_duplicates()
    uncertainty = ["b1_sd", "b1_q025", "b1_q50", "b1_q975", "b2_sd", "b2_q025", "b2_q50", "b2_q975"]
    if len(krt_pairs) != 52 or len(nls_pairs) != 270 or len(commune) != 104000:
        raise AssertionError("canonical result counts do not match the H0A-H1 release scope")
    if not commune[uncertainty].notna().all().all():
        raise AssertionError("communal uncertainty fields are incomplete")
    substantive54 = dep54.loc[dep54["source_substantive"]]
    if len(substantive54) != 1 or str(substantive54.iloc[0]["stable_unit_id"]).split(".")[0] != "54602":
        raise AssertionError("department 54 evidence is inconsistent")

    mcmc_counts = canonical["mcmc_status"].value_counts(dropna=False).to_dict()
    identification_counts = canonical["identification_status"].value_counts(dropna=False).to_dict()
    sensitivity_contrasts = sensitivity.loc[
        sensitivity.get("estimand", pd.Series(dtype="string")).eq("contrast")
    ] if not sensitivity.empty else sensitivity
    target_columns = [
        "election_id", "scenario_id", "old_run_id", "new_run_id", "old_contrast_mean",
        "new_contrast_mean", "new_mcmc_status", "identification_status",
        "estimate_stability_status", "selected_run_id", "selected_reason",
    ]
    payload = {
        "release_id": "longitudinal_2000_v1.0.1_H0A_H1_validated" if ready else "longitudinal_2000_v1.0.1_H0A_H1_candidate",
        "ready": bool(ready),
        "ready_scope": "H0A-H1" if ready else "candidate_pending_gates",
        "headline": (
            "Le périmètre H0A–H1 est validé sur un panel fixe de 2 000 communes."
            if ready
            else "La candidate H0A–H1 est auditée ; les portes MCMC finales restent en cours."
        ),
        "counts": {
            "elections": 26,
            "panel_units": 2000,
            "panel_election_keys": 52000,
            "krt_pairs": int(len(krt_pairs)),
            "nls_pairs": int(len(nls_pairs)),
            "krt_commune_rows": int(len(commune)),
            "mcmc": {str(k): int(v) for k, v in mcmc_counts.items()},
            "identification": {str(k): int(v) for k, v in identification_counts.items()},
        },
        "hashes": {
            "original_zip": "ed80a7dfb14653ec0be943c811317c6786651fa8d97e12870f366dde1df74446",
            "panel_2000_master_file": "bde70c71660fce29610d7931461d8db6181dba874514a1866b63cf16a81cec4a",
            "legacy_panel_v2": "d70810a1add048d4823274e182f3adf8735d6f881bd32564a550c78988e8cd3f",
            "source_1988": "0ca19aa94c982c34e99cce9cc2670c7ed02da07c148ab2eafad86a689e0fa985",
        },
        "department54": {
            "source_rows": int(len(dep54)),
            "non_substantive_rows": int((~dep54["source_substantive"]).sum()),
            "substantive_unit": "54602",
            "strict_exclusion_reason": str(substantive54.iloc[0]["strict_exclusion_reason"]),
            "conclusion": (
                "Le département 54 est presque entièrement perdu à cause de la lacune de la source 1988 ; "
                "son unique ligne électorale substantielle restante (54602) échoue au contrôle social "
                "csp_total_non_positive. Le panel ne change pas et aucun modèle n'est relancé pour le 54."
            ),
        },
        "legacy_v2_sensitivity_anomalies": [
            {"election_id": "leg_1962_r1", "unit_id": "59473", "inscrits": 178, "votants": 149, "exprimes": 150},
            {"election_id": "leg_1986_r1", "unit_id": "02643", "inscrits": 383, "votants": 383, "exprimes": 392},
            {"election_id": "leg_1986_r1", "unit_id": "06149", "inscrits": 6270, "votants": 4370, "exprimes": 4696},
            {"election_id": "leg_1986_r1", "unit_id": "14606", "inscrits": 88, "votants": 70, "exprimes": 79},
        ],
        "rxc": {
            "pairs": int(rxc[["election_id", "scenario_id"]].drop_duplicates().shape[0]),
            "offenders_in_panel": int(rxc["in_panel_2000"].sum()),
            "panel_exact_closure_failures": int((~rxc["panel_model_ready_exact_closure"]).sum()),
            "status": "deferred_to_v1.1",
        },
        "nls_replication": _records(nls_rep, list(nls_rep.columns)) if not nls_rep.empty else [],
        "sensitivity": _records(
            sensitivity_contrasts,
            [
                "row_type", "election_id", "cell_label", "comparison_label", "mean", "q025", "q975",
                "difference_mean", "difference_q025_descriptive", "difference_q975_descriptive",
                "intervals_overlap", "interpretation_scope",
            ],
        ),
        "sensitivity_nls": _records(
            sensitivity_nls,
            [
                "election_id", "cell", "n_communes", "nls_contrast",
                "target_group_share_unweighted", "target_group_share_electoral_weighted",
                "left_vote_share", "electoral_weight_total", "vbbm_mean", "n_departments",
            ],
        ),
        "targeted_reruns": _records(targeted, target_columns),
        "krt_nls": _records(
            krt_nls,
            [
                "election_id", "scenario_id", "krt_contrast_mean", "krt_contrast_q025",
                "krt_contrast_q975", "nls_contrast", "nls_minus_krt", "nls_inside_krt_interval",
                "mcmc_status", "identification_status",
            ],
        ),
        "coverage": {
            "rows": int(len(coverage)),
            "elections": int(coverage["election_id"].nunique()),
            "departments": int(coverage["department"].nunique()),
        },
        "panel_validation": panel_validation,
        "figures": [
            item
            for item in (
                "04_figures_essentielles/h1_panel_sensitivity.png",
                "04_figures_essentielles/krt_nls_comparison_h0a_h1.png",
                "04_figures_essentielles/raw_scatter_2022_bounds_and_target_share.png",
            )
            if (RELEASE_ROOT / item).exists()
        ],
        "reserves": [
            "Les résultats KRT sont des inférences écologiques : convergence MCMC et identification sont diagnostiquées séparément.",
            "La sensibilité entre panels compare des modèles estimés séparément ; les distributions de différences sont descriptives et non causales.",
            "La reproduction complète nécessite le dépôt parent et les archives sources, non incluses dans la livraison.",
            "Les 22 couples RxC sont audités mais leur estimation est reportée à la version 1.1.",
            "ready=true signifie uniquement que le périmètre H0A–H1 satisfait les portes de cette release.",
        ],
    }
    return payload


def _table(records: list[dict[str, Any]], *, max_rows: int = 60) -> str:
    if not records:
        return "<p class='muted'>Non disponible à ce stade.</p>"
    rows = records[:max_rows]
    columns = list(rows[0])
    head = "".join(f"<th>{html.escape(str(column))}</th>" for column in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(row.get(column, '')))}</td>" for column in columns) + "</tr>"
        for row in rows
    )
    suffix = f"<p class='muted'>Table tronquée à {max_rows} lignes dans le rapport ; CSV complet livré.</p>" if len(records) > max_rows else ""
    return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>{suffix}"


def build_html(payload: dict[str, Any]) -> None:
    cards = "".join(
        f"<div class='card'><span>{label}</span><strong>{value}</strong></div>"
        for label, value in (
            ("Communes fixes", payload["counts"]["panel_units"]),
            ("Scrutins", payload["counts"]["elections"]),
            ("Couples KRT", payload["counts"]["krt_pairs"]),
            ("Couples NLS", payload["counts"]["nls_pairs"]),
        )
    )
    figures = "".join(
        f"<figure><img src='{html.escape(path)}'><figcaption>{html.escape(Path(path).stem.replace('_', ' '))}</figcaption></figure>"
        for path in payload["figures"]
    )
    reserves = "".join(f"<li>{html.escape(item)}</li>" for item in payload["reserves"])
    source = f"""<!doctype html>
<html lang='fr'><head><meta charset='utf-8'><title>Rapport technique v1.0.1 H0A–H1</title>
<style>
:root{{--ink:#172033;--blue:#245c8a;--light:#eef4f8;--line:#ccd8e2;--caveat:#9a6700}}
body{{font-family:Segoe UI,Arial,sans-serif;color:var(--ink);max-width:1180px;margin:0 auto;padding:36px;line-height:1.48}}
h1{{font-size:32px;margin-bottom:6px}} h2{{margin-top:34px;border-bottom:2px solid var(--blue);padding-bottom:5px}}
h3{{margin-top:24px}} .subtitle,.muted{{color:#5e6b78}} .status{{padding:14px 18px;background:var(--light);border-left:5px solid var(--blue)}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0}} .card{{padding:15px;background:#f6f8fa;border:1px solid var(--line)}}
.card span{{display:block;color:#5e6b78}} .card strong{{font-size:28px;color:var(--blue)}}
.table-wrap{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;font-size:12px}} th,td{{border:1px solid var(--line);padding:6px;text-align:left;vertical-align:top}} th{{background:var(--light)}}
figure{{margin:28px 0}} img{{max-width:100%;height:auto;border:1px solid var(--line)}} figcaption{{color:#5e6b78;font-size:13px}}
code{{background:#f2f4f6;padding:2px 4px}} .hash{{font-family:Consolas,monospace;font-size:11px;word-break:break-all}}
@media print{{body{{padding:0}} h2{{page-break-before:auto}} figure,table{{page-break-inside:avoid}}}}
</style></head><body>
<h1>Release longitudinale v1.0.1 — H0A/H1</h1><p class='subtitle'>{html.escape(payload['release_id'])}</p>
<p class='status'><strong>Conclusion.</strong> {html.escape(payload['headline'])}<br><code>ready={str(payload['ready']).lower()}</code> ; <code>ready_scope={html.escape(payload['ready_scope'])}</code>.</p>
<div class='cards'>{cards}</div>
<h2>1. Périmètre et interprétation</h2><p>Cette release conserve 52 couples KRT (H0A et H1 pour 26 scrutins) et 270 couples NLS. Les 22 RxC restent audités mais différés. Les diagnostics MCMC, l’identification écologique et la stabilité entre spécifications sont trois verdicts distincts.</p>
{_table([{'dimension': 'convergence MCMC', **payload['counts']['mcmc']}, {'dimension': 'identification écologique', **payload['counts']['identification']}])}
<h2>2. Panel et département 54</h2><p>{html.escape(payload['department54']['conclusion'])}</p>
<p>Couverture auditée : {payload['coverage']['rows']} lignes élection × département. Les 2 000 mêmes <code>unit_id</code> sont présents à chacun des 26 scrutins (52 000 clés), avec SMD maximal {payload['panel_validation']['max_abs_smd_all_elections']:.4f} et écart catégoriel maximal {payload['panel_validation']['max_abs_category_gap_all_elections']:.4f}. Hash panel : <span class='hash'>{payload['hashes']['panel_2000_master_file']}</span>.</p>
<h2>3. Sensibilité H1</h2><p>Les différences entre fits indépendants sont descriptives. Le libellé <code>pipeline_only</code> n’est utilisé que lorsque les hashes X, Y et N sont identiques.</p>
<p><strong>Anomalies historiques V2.</strong> La cellule diagnostique conserve 59473 en 1962 (178 inscrits, 149 votants, 150 exprimés), ainsi que 02643, 06149 et 14606 en 1986, dont les exprimés dépassent les votants. Cette conservation permet de comparer la matrice effectivement estimée ; les partitions X/Y/N ferment exactement et ces exceptions ne touchent pas le panel canonique.</p>
<h3>Contrôles rapides NLS et composition</h3>{_table(payload['sensitivity_nls'], max_rows=12)}
<h3>Sensibilité KRT</h3>{_table(payload['sensitivity'], max_rows=36)}
<h2>4. Relances MCMC ciblées</h2><p>Six runs seulement, avec une seconde graine et 2 000 itérations de chauffe + 2 000 tirages. La sélection canonique suit la règle fixée avant lecture des résultats.</p>{_table(payload['targeted_reruns'])}
<h2>5. Comparaison KRT–NLS</h2><p>Le point NLS est présenté sans pseudo-intervalle postérieur. Les intervalles sont ceux du KRT.</p>{_table(payload['krt_nls'], max_rows=52)}
<h2>6. Réplication NLS R/Python</h2>{_table(payload['nls_replication'])}
<h2>7. RxC différés</h2><p>{payload['rxc']['pairs']} couples audités ; {payload['rxc']['offenders_in_panel']} unité fautive appartient au panel 2 000 ; {payload['rxc']['panel_exact_closure_failures']} matrice panel échoue à la fermeture exacte. Exécution : <code>{payload['rxc']['status']}</code>.</p>
<h2>8. Figures essentielles</h2>{figures}
<h2>9. Réserves et reproduction</h2><ul>{reserves}</ul>
<h2>10. Empreintes de référence</h2>{_table([payload['hashes']])}
</body></html>"""
    REPORT_HTML.write_text(source, encoding="utf-8")


def write_supporting_docs(payload: dict[str, Any]) -> None:
    release_configuration_path = METHOD_DIR / "release_configuration_v1.0.1.json"
    if release_configuration_path.exists():
        release_configuration = json.loads(release_configuration_path.read_text(encoding="utf-8"))
        release_configuration["ready"] = bool(payload["ready"])
        release_configuration["ready_scope"] = payload["ready_scope"]
        release_configuration_path.write_text(
            json.dumps(release_configuration, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    dependencies = """# Dépendances et reproduction

La livraison est autonome pour la lecture des résultats consolidés, mais **la reproduction complète nécessite le dépôt parent** et les archives brutes qui ne sont pas redistribuées dans les ZIP.

## Environnements

- Python : voir `05_methodologie_et_code/code_longitudinal/` et la configuration de release ; PyEI, PyMC, ArviZ, pandas, NumPy, SciPy et PyArrow sont requis.
- R : les comparaisons livrées utilisent les scripts et manifestes présents dans l’archive technique ; les paquets exacts sont listés par ces manifestes.
- Les traces NetCDF sont des fichiers temporaires de post-traitement et sont exclues des deux livraisons.

## Chemins

Les manifestes de livraison distinguent `runtime_root`, `runtime_path`, `delivery_path`, `delivery_included` et `external_required`. Aucun chemin absolu local n’est requis pour lire les artefacts livrés.
"""
    (RELEASE_ROOT / "DEPENDENCIES_AND_REPRODUCTION.md").write_text(dependencies, encoding="utf-8")
    selected = pd.read_csv(SYNTHESIS_DIR / "canonical_run_selection.csv")
    replacements = selected.loc[selected["replaces_run_id"].fillna("").ne("")]
    replacement_lines = "\n".join(
        f"- {row.election_id}/{row.scenario_id}: {row.replaces_run_id} → {row.run_id} ({row.selected_reason})"
        for row in replacements.itertuples(index=False)
    ) or "- Aucun remplacement canonique à ce stade."
    sensitivity_registry_path = RELEASE_ROOT / "07_auxiliary_runs" / "h1_panel_sensitivity" / "auxiliary_run_registry.csv"
    if sensitivity_registry_path.exists():
        sensitivity_registry = pd.read_csv(sensitivity_registry_path, dtype="string")
        sensitivity_run_lines = "\n".join(
            f"- {row.election_id} — {row.cell}: `{row.run_id}`"
            for row in sensitivity_registry.sort_values(["election_id", "cell"]).itertuples(index=False)
        )
    else:
        sensitivity_run_lines = "- Non finalisé."
    targeted_path = SYNTHESIS_DIR / "targeted_mcmc_reruns.csv"
    targeted = pd.read_csv(targeted_path, dtype="string") if targeted_path.exists() else pd.DataFrame()
    if not targeted.empty:
        targeted_run_lines = "\n".join(
            f"- {row.election_id}/{row.scenario_id}: `{row.new_run_id}`"
            for row in targeted.sort_values(["scenario_id", "election_id"]).itertuples(index=False)
        )
    else:
        targeted_run_lines = "- Non finalisé."
    changelog = f"""# CHANGELOG v1.0.1

## Corrections

- panel principal confirmé à 2 000 communes, graine panel 20260803 et hash inchangé ;
- audit du département 54 corrigé : 589 lignes 1988 non substantielles, 54602 exclue pour `csp_total_non_positive` ;
- `foreign_share` provient de `petrangerYYYY`, vérifié contre `etranger/(etranger+francais)` ; `peretrangerYYYY` est exclu sans lui attribuer une interprétation non documentée ;
- années de référence extraites des colonnes sources, statuts documentaires `unknown` en l’absence de preuve ;
- quatre anomalies V2 (59473 en 1962 ; 02643, 06149 et 14606 en 1986) documentées et confinées aux cellules de sensibilité `diagnostic_only` ;
- chemins Python/R corrigés vers `02_comparaison_python_r/` ;
- méthodes 2×2 complétées par `rosen_nls_2x2_unadjusted` ;
- NetCDF exclus des livraisons ; reproduction complète signalée comme dépendante du dépôt parent.

## Contrôles

- 26 élections, 292 couples classés, 52 couples KRT, 270 couples NLS ;
- 104 000 lignes KRT communales et huit champs d’incertitude complets ;
- 22 RxC audités, anomalies hors panel et fermeture exacte sur les matrices panel ;
- réplication NLS R/Python sur 270 couples avec seuil 1e-6 ;
- sensibilité H1 et relances ciblées séparées des runs canoniques.

## Sélection canonique

{replacement_lines}

## Modèles relancés

### Sensibilité H1 — six runs

{sensitivity_run_lines}

### Relances ciblées — six runs

{targeted_run_lines}

## Réserves

- `ready={str(payload['ready']).lower()}` a pour seul périmètre `ready_scope={payload['ready_scope']}` ;
- différences de sensibilité entre fits indépendants uniquement descriptives ;
- RxC estimés reportés à v1.1 ;
- reproduction complète dépendante du dépôt parent.
"""
    (RELEASE_ROOT / "CHANGELOG_v1.0.1.md").write_text(changelog, encoding="utf-8")
    readme = f"""# Livraison professeur — longitudinal 2000 v1.0.1

Statut : `ready={str(payload['ready']).lower()}` ; périmètre : `{payload['ready_scope']}`.

Commencer par `RAPPORT_TECHNIQUE_v1.0.1.pdf`, puis consulter les trois Parquet principaux dans `01_resultats_python/`, le panel et les audits résumés dans `03_panel_et_audit/`, et les figures dans `04_figures_essentielles/`.

La reproduction complète nécessite le dépôt parent. Voir `DEPENDENCIES_AND_REPRODUCTION.md`.
"""
    (RELEASE_ROOT / "README_PROFESSEUR.md").write_text(readme, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the v1.0.1 HTML report payload and supporting documents.")
    parser.add_argument("--ready", action="store_true")
    args = parser.parse_args()
    METHOD_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_payload(ready=args.ready)
    PAYLOAD_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    build_html(payload)
    write_supporting_docs(payload)
    print(json.dumps({"report": str(REPORT_HTML), "ready": payload["ready"], "payload_sha256": file_sha256(PAYLOAD_PATH)}))


if __name__ == "__main__":
    main()
