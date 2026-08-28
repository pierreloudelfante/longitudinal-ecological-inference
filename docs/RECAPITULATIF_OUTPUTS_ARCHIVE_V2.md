# Récapitulatif exact des outputs de l’archive V2 corrigée

## Périmètre de ce document

Ce document décrit `longitudinal_priority_results_v2_corrige_3000_en_cours_documente.zip`, copie documentée du gel du 4 août 2026. Il ne décrit pas l’état ultérieur éventuel du dossier de travail. L’archive source comportait 215 fichiers, soit 360 009 514 octets avant compression. La copie documentée ajoute quatre Markdown, remplace le README minimal et rend portables trois liens d’images, sans modifier aucun output scientifique : elle contient 219 fichiers.

La copie documentée contient 83 CSV, 49 JSON, 9 Markdown, 2 Parquet, 29 PNG, 29 SVG, 14 scripts Python, 2 archives ZIP imbriquées et 2 fichiers SHA-256.

## État scientifique au moment du gel

| Bloc | État contenu dans l’archive | Portée correcte |
| --- | --- | --- |
| Réanalyse KRT historique corrigée | 12 traces réanalysées | panel historique de 500/494/500 communes ; aucune nouvelle estimation |
| PPC KRT | 12 contrôles prédictifs | mêmes runs historiques ; calibration, pas identification |
| Panel longitudinal commun | 3 000 communes exactes | même panel pour H0A, H1, H2 et H4, aux trois dates |
| Entrées prioritaires | 12/12 auditées à 3 000 lignes | les Parquet modèle-ready ne sont pas inclus dans cette archive |
| Benchmark NLS 2×2 | 12/12 réussis | panel commun de 3 000 communes |
| Nouvelle production KRT | 2/12 terminées, 10/12 en attente | H0A-1962 et H0A-1986 seulement |
| Densités jointes et marginales | 24 couples PNG/SVG | calculées à partir des traces historiques 500/494/500 |

Le fichier `outputs/v2/priority_production_progress_v2.json` inclus est à la révision 7, avec le statut `paused_by_user` : 2 succès, 10 éléments en attente, aucun échec et aucun élément en cours. Il s’agit du statut de l’archive, même si le dossier de travail a pu avancer depuis.

## Carte des répertoires

| Chemin | Fichiers | Contenu | Limite d’usage |
| --- | ---: | --- | --- |
| `docs/` | 8 dans la copie documentée | synthèse, état du gel, méthodes, index des outputs et processus | 4 existaient dans l’archive source, 4 ont été ajoutés |
| `panel/` | 4 | panel, balance, tentatives et manifeste | panel accepté, pas données brutes |
| `outputs/v2/priority_500_reanalysis/` | 9 | correction des agrégats, contrastes, diagnostics, identification, bootstrap | résultats historiques corrigés, pas résultats KRT à 3 000 |
| `outputs/v2/ppc_krt/` | 25 | 12 CSV communaux, 12 JSON de métriques et un tableau récapitulatif | PPC des traces historiques |
| `outputs/v2/nls_priority/` | 75 | plan, audit, progression et artefacts de 12 fits NLS | benchmark distinct du KRT principal |
| `outputs/v2/diagnostic_audits/` | 2 | audits KRT de H0A-1962 et H0A-1986 | aucune preuve pour les dix fits non exécutés |
| `outputs/runs/…` | 14 | sept artefacts canoniques pour chacun des deux runs KRT terminés | traces NetCDF exclues |
| `figures/v2/priority_500_reanalysis/` | 10 | cinq figures en PNG et SVG | panel historique |
| `figures/v2/ppc_krt/` | 24 | douze PPC en PNG et SVG | panel historique |
| `figures/v2/densities/` | 24 | douze densités en PNG et SVG | panel historique |
| `code_longitudinal/` | 14 | scripts centraux de la correction et de la production V2 | sous-ensemble d’audit, non exécutable seul |
| `deliverables/` | 4 | deux archives antérieures et leurs empreintes | archives imbriquées conservées comme références |

## Détail des outputs tabulaires

### Réanalyse historique corrigée

| Fichier | Lignes | Rôle |
| --- | ---: | --- |
| `aggregate_comparison_v2.csv` | 48 | comparaison entre ancien agrégat et agrégat corrigé |
| `corrected_estimates_v2.csv` | 48 | estimations agrégées corrigées |
| `identification_metrics_v2.csv` | 12 | indicateurs de tomographie et d’identification |
| `longitudinal_contrast_changes_v2.csv` | 12 | changements entre périodes |
| `official_diagnostics_v2.csv` | 12 | verdict MCMC canonique par trace |
| `panel_bootstrap_sensitivity_v2.csv` | 24 | sensibilité descriptive au panel observé |
| `within_period_contrasts_v2.csv` | 12 | contrastes entre les deux groupes sociaux |
| `official_diagnostics_details_v2.json` | — | détail machine-lisible des diagnostics |
| `validation_summary_v2.json` | — | contrôles de validation de la réanalyse |

### Panel et préparation des entrées

- `panel_3000_common_1962_1986_2022_v2.csv` contient exactement 3 000 communes uniques et leur rang de tirage.
- `panel_3000_common_1962_1986_2022_v2_attempts.csv` contient une tentative : graine `20260802`, acceptée.
- `panel_3000_common_1962_1986_2022_v2_balance.csv` contient 44 lignes de contrôles contre deux univers de référence.
- `panel_3000_common_1962_1986_2022_v2_manifest.json` consigne les règles, effectifs, versions et empreintes.
- `priority_model_ready_3000_audit.csv` contient 12 lignes : toutes indiquent 3 000 communes incluses sans exclusion silencieuse.
- `priority_model_ready_3000_manifest.json` confirme `fits_planned=12` et `all_exactly_3000=true`.

### Nouvelle production KRT à 3 000 communes

Les deux répertoires de runs inclus sont :

- `outputs/runs/20260804T135238Z__a1d85f03a9f8/` : H0A-1962 ; fit réussi, diagnostic MCMC avec réserve ;
- `outputs/runs/20260804T140822Z__cc8c7aa063b5/` : H0A-1986 ; fit réussi, diagnostic MCMC avec réserve.

Chaque répertoire contient `manifest.json`, `longitudinal_estimates.csv`, `aggregate_comparison_v2.csv`, `mcmc_diagnostics_v2.json`, `mcmc_variable_metrics_v2.csv`, `mcmc_block_metrics_v2.csv` et `commune_latent_summaries.parquet`. Les fichiers `trace.nc` ne sont pas inclus.

## Ordre de lecture recommandé

1. `README.md` : point d’entrée et statut du gel ;
2. `docs/ETAT_ARCHIVE_CORRIGEE_3000.md` : état exact des deux productions KRT terminées ;
3. `docs/PRIORITY_RESULTS_FOR_PROFESSOR_V2.md` : synthèse substantielle ;
4. `docs/METHODE_ECHANTILLONNAGE_PANEL_3000.md` : construction et limites du panel ;
5. `docs/PROCESSUS_PROJET_ARCHIVE_V2.md` : chaîne de production, scripts et outputs ;
6. `docs/PPC_V2_METHOD.md` et `docs/PRIORITY_CHART_MAP_V2.md` : contrôles prédictifs et figures.

## Ce que l’archive ne contient pas

- les dix estimations KRT à 3 000 communes encore non exécutées au moment du gel ;
- les traces NetCDF des deux runs terminés ;
- les douze fichiers Parquet modèle-ready ;
- les archives de données brutes ;
- tous les modules Python importés par les 14 scripts sélectionnés.

L’archive est donc une livraison de résultats et d’audit intermédiaire, pas un environnement autonome permettant de tout recalculer depuis les données brutes.
