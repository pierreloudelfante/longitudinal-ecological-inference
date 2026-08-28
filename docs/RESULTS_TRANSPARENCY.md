# Guide de lecture et transparence des résultats

## Verdict de la livraison

L'architecture, le panel fixe, les schémas de sortie, les pilotes demandés, les bêta communaux et les mécanismes de reprise sont opérationnels. La série MCMC complète 1962–2022 n'est pas revendiquée comme achevée : les petits paliers PyEI sont des calibrations non substantielles et les garde-fous de calcul restent obligatoires avant généralisation.

Au dernier contrôle consolidé :

- 57 contrôles passent, 3 avertissements sont conservés et aucun contrôle n'échoue ;
- 30 tests `pytest` passent ;
- 292 partitions sont auditées : 270 valides, 22 RXC refusées sur marge brute ;
- 1 706 lignes d'estimations et 385 diagnostics d'ajustement sont exportés ;
- 337 327 résumés latents et 674 654 lignes bêta communales sont conservés ;
- 370 traces NetCDF sont indexées ;
- 577 272 points de densité marginale sont disponibles ;
- 172 coefficients NLS et 240 diagnostics de départ sont exportés.

Ces nombres décrivent l'état de la livraison, pas un certificat de validité substantielle de chaque estimation.

## Hiérarchie de confiance

| Niveau | Contenu | Usage autorisé |
|---|---|---|
| structure validée | panels, registres, 270 partitions matérialisées, schémas, clés, reprise | audit et reproduction |
| NLS convergé et diagnostiqué | RXC1/RXC2 1986/2022 et robustesses disponibles ; 1962 conservé en `fail` | analyse descriptive, sous réserves écologiques et sans intervalle agrégé validé |
| PyEI de calibration jusqu'à n=3 000 | 52/56 couples au palier cible, 20 draws et une chaîne | test du pipeline, temps/mémoire, inspection des traces |
| MCMC `warning` ou `fail` | diagnostics insuffisants | aucun résultat substantiel |
| série 1962–2022 non exécutée | scénarios enregistrés mais non calculés en production | aucune conclusion longitudinale complète |

Le plus grand palier commun King/KRT atteint 3 000 communes demandées pour 24
couples élection–scénario. H6 en 1986 reste comparable au palier 500 ; H7 en
1986 et H5 en 2022 restent au palier 25 à cause d'un blocage KRT par la
mémoire. H5 en 1962 n'a qu'une vue
KRT native. Cette limite apparaît dans les titres et dans
`outputs/pilot_density_selection.csv`.

## Tables à utiliser

| Fichier | Rôle |
|---|---|
| `outputs/longitudinal_estimates.{csv,parquet}` | résultats agrégés, clés complètes et statut diagnostique |
| `outputs/model_diagnostics.csv` | convergence, avertissements, échecs et caractère substantiel |
| `outputs/commune_latent_summaries.{csv,parquet}` | résumé large des latents communaux |
| `outputs/commune_beta_estimates.{csv,parquet}` | un bêta par commune, groupe, scénario, modèle et quantile |
| `outputs/beta_density_data.{csv,parquet}` | données directement traçables pour les densités de bêta |
| `outputs/beta_trace_index.csv` | chemin, empreinte et métadonnées des traces NetCDF |
| `outputs/density_marginal_data.*` | marges sociales et politiques, vue native/intersection |
| `outputs/density_joint_data.*` | résultats joints King/KRT, vue native/intersection |
| `outputs/nls_coefficients.csv` | paramètres NLS retenus |
| `outputs/nls_start_diagnostics.csv` | audit des 20 départs et écarts au meilleur |
| `outputs/excluded_units.csv` | commune, étape et raison d'exclusion |
| `outputs/run_registry.csv` | historique immuable des exécutions |
| `outputs/resource_ladder_*.csv` | prévisions et décisions temps/mémoire |
| `outputs/all_elections_partition_integrity.csv` | statut des 292 partitions et raisons des 22 refus |
| `outputs/pilot_model_coverage.csv` | plus grand palier réellement réussi par couple pilote |
| `outputs/pilot_density_selection.csv` | provenance des 28 figures propres disponibles, dont les 13 du rapport illustré |
| `docs/FIGURE_CATALOG.md` | index des 238 SVG avec portée, famille et table source |
| `outputs/illustrated_report_estimates.csv` | 50 résumés β exactement tracés dans les comparaisons 1962/1986/2022 |
| `outputs/professor_canonical_comparisons.csv` | résumés β exacts des huit comparaisons canoniques H0A–H5 |
| `outputs/validation_checks.csv` | détail de chaque contrôle de livraison |

Le schéma colonne par colonne est défini dans `docs/OUTPUT_SCHEMA.md`.

## Lire une densité de bêta

La densité principale représente la distribution entre communes des moyennes postérieures \(E(\beta_i\mid\text{données})\), chaque commune comptant une fois. Elle ne représente ni tous les tirages MCMC mis bout à bout, ni une distribution d'individus. La variante pondérée par les effectifs sociaux est explicitement étiquetée.

Pour comparer King et KRT, utiliser `comparison_scope=common_intersection` et
en priorité `figures/densities/curated/`. Le nombre de communes, les draws, les
chaînes et le diagnostic restent visibles. Les variantes natives diagnostiquent
les exclusions propres à un modèle mais ne garantissent pas une composition
identique.

## Reproduire les contrôles

Depuis `ARE/part2/longitudinal_2022`, avec l'environnement Python du dépôt :

```powershell
$env:PYTHONPATH = (Get-Location).Path
& '..\pour_moi_avec_data\.venv-ei\Scripts\python.exe' -m pytest -q tests
& '..\pour_moi_avec_data\.venv-ei\Scripts\python.exe' -m code_longitudinal.run_pipeline --stage consolidate
```

Le stage `consolidate` régénère les tables, les figures disponibles, le rapport de validation et les manifestes. Les calculs MCMC de production ne doivent être lancés qu'avec les ressources nécessaires et après lecture des prévisions de palier.

## Traçabilité et provenance

- `panel/panel_manifest.json` contient la graine, le verdict de balance et les SHA-256 des sources du panel.
- `outputs/file_manifest.csv` inventorie les artefacts canoniques.
- `outputs/run_registry.csv` relie configuration, entrées, `run_key`, `run_id`, statut et répertoire immuable.
- `docs/METHODOLOGY_CODE_MAP.md` relie les équations aux fonctions et lignes de code.
- `docs/LONGITUDINAL_AUDIT.md` indique ce qui a été réutilisé, adapté ou remplacé.

## Limites à conserver dans toute communication

1. Le panel rétrospectif est défini à partir de l'univers 2022 ; les disparitions et changements communaux historiques peuvent produire une sélection de survivants.
2. Les absences historiques ne sont pas imputées et aucune commune de remplacement n'est introduite.
3. L'inférence écologique ne transforme pas des marges agrégées en observations individuelles.
4. Les intervalles NLS agrégés restent absents faute de méthode d'incertitude validée.
5. Les sorties PyEI de calibration ne sont pas des résultats de production, même si leur fichier et leur figure existent.
