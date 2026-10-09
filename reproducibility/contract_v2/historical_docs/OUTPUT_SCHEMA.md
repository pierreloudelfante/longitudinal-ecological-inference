# Schéma des sorties longitudinales

Toutes les clés sont UTF-8 et les probabilités sont sur `[0,1]`. Les CSV servent à la revue légère ; les Parquet sont les tables canoniques lorsque les deux formats existent.

## `longitudinal_estimates`

Grain : une estimation par run, élection, scénario, modèle, groupe social et catégorie de vote. Clé : `run_id, social_group, vote_category, covariate_name`.

Les colonnes couvrent l'identité du run, le scrutin, le scénario, le modèle, la covariable éventuelle, l'estimation et son intervalle, les effectifs, le temps, les statuts et la graine. `lower`/`upper` restent vides pour le NLS tant qu'une incertitude agrégée n'est pas validée.

## `model_diagnostics`

Grain : un ajustement. Contient la configuration, les effectifs demandé/utilisé, les filtrages, le temps, la mémoire, R-hat, ESS, divergences, statuts et erreur éventuelle. Des colonnes NLS supplémentaires peuvent apparaître : objectif, rang, conditionnement et valeurs singulières.

## `commune_latent_summaries`

Grain : une commune effectivement utilisée par un run King/KRT. Clé : `run_id, unit_id`. Contient poids sociaux et moyenne, écart-type, médiane et intervalle 95 % de `b1` et `b2` extraits directement de la trace.

## Bêta communaux et densités

- `commune_beta_estimates.{csv,parquet}` : format long explicite, clé `run_id, unit_id, beta_parameter`. Chaque ligne conserve le groupe social correspondant, le poids, la moyenne postérieure communale, l'écart-type et les quantiles 2,5 %, 50 % et 97,5 %.
- `beta_density_data.{csv,parquet}` : données prêtes à tracer. La base est toujours `density_of_commune_posterior_means` : chaque commune compte exactement une fois dans la densité principale.
- `beta_trace_index.csv` : index des traces NetCDF qui conservent tous les tirages postérieurs de `b_1` et `b_2`, avec chemin, taille et SHA-256.

Les tirages ne sont pas développés dans un CSV géant, car cela multiplierait artificiellement le poids des communes et deviendrait prohibitif en production. Ils restent accessibles sans perte dans chaque `trace.nc`.

## `nls_coefficients` et `nls_start_diagnostics`

Les coefficients ont pour clé `run_id, social_group, vote_category, term`; la dernière catégorie électorale est la référence implicite à coefficients nuls. Les diagnostics de départ contiennent coût, convergence, coefficients sérialisés et écarts maximaux de coefficients/prédictions au meilleur départ.

## Données de densité

- `density_marginal_data` : grille `[0,1]`, paramètre latent, pondération (`equal_commune` ou `social_population_weighted`) et portée (`native` ou `common_intersection`).
- `density_joint_data` : couples communaux `(b1_mean,b2_mean)` utilisés pour les points, hexbins et contours.

Les deux tables portent aussi `comparison_key`, le palier demandé et les réglages MCMC. Une intersection ne rapproche donc que deux runs King/KRT ayant exactement la même configuration hors nom du modèle ; les paliers différents ne sont jamais mélangés.

## Autres tables

### Audit longitudinal des partitions et du pilote

- `all_elections_partition_integrity.csv` : grain élection–scénario pour les
  292 partitions admissibles. Contient demandé/utilisé/exclu, `N_total`, les
  trois écarts de fermeture, unicité, non-négativité, verdict, erreur et chemin
  du manifeste ;
- `all_elections_partition_preparation.json` : journal détaillé des 292
  tentatives, y compris les 22 RXC refusées avant arrondi ;
- `pilot_model_coverage.csv` : grain élection–scénario–modèle pour les 26
  couples pilotes ; donne cible, plus grand palier réussi, effectif utilisé,
  configuration MCMC, diagnostic et limitation ;
- `pilot_density_selection.csv` : une ligne par modèle représenté dans chacune
  des 28 figures propres actuellement disponibles, avec `run_id`, intersection, palier, effectif, draws,
  tune, chaînes et diagnostic.
- `illustrated_report_estimates.csv` : deux lignes (`b_1`, `b_2`) par run retenu
  dans le rapport 1962/1986/2022. La clé est
  `election_id, scenario_id, model_key, beta_parameter`. La moyenne principale
  donne le même poids à chaque commune ; P25, médiane et P75 décrivent la
  dispersion entre communes. `mean_social_weighted` est conservée comme mesure
  auxiliaire, sans être tracée dans la comparaison principale.
- `professor_canonical_comparisons.csv` : même schéma et même clé que la table
  précédente, mais pour les scénarios H0A, H0B, H0C, H1, H2, H3, H4 et H5 sur
  les trois coupes législatives 1962/1986/2022. C'est la source exacte des huit
  graphiques dans `figures/professor_recap/`.

### Audit mono-élection 2022

- `election_2022_input_integrity.csv` : une ligne par scénario 2×2 H0A–H7.
  Colonnes principales : nombre de lignes et d'identifiants uniques,
  duplications, minimum de `N_g`, écart maximal entre la somme des comptes
  sociaux et `N_g`, puis entre la somme des comptes politiques et `N_g`.
- `election_2022_fit_quality.csv` : une ligne par scénario RXC et bloc
  politique. Contient `rmse`, `mae`, `max_absolute_error`, moyenne observée et
  moyenne prédite des parts communales. Ces mesures portent sur la
  reconstruction des marges, pas sur des observations individuelles.

### Tables de suivi générales

- `excluded_units` : clé complète du run et de la commune, étape et raison ;
- `resource_ladder_preflight` : décision prise avant un nouveau palier, avec projections de temps et mémoire ;
- `resource_ladder_gates` : même garde recalculée après chaque run réussi pour le palier suivant ;
- `rxc_runtime_benchmark` : taille RxC, réglages MCMC, temps, mémoire et diagnostics ;
- `run_registry_executed.csv` : journal append-only des exécutions réelles ;
- `run_registry.csv` : vue publique réunissant exécutions réelles et combinaisons encore planifiées ;
- `run_registry_all.csv` : alias de compatibilité de la vue publique ;
- `panel_election_presence.csv` : présence de chaque commune du panel dans chaque archive électorale.
