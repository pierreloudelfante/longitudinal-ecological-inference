# Processus du projet correspondant à l’archive V2 corrigée

## Objet et règle de lecture

Cette documentation suit les artefacts réellement présents dans `longitudinal_priority_results_v2_corrige_3000_en_cours.zip`. Elle distingue systématiquement :

- la réanalyse corrigée de 12 traces KRT historiques sur 500/494/500 communes ;
- le benchmark NLS exécuté 12 fois sur le nouveau panel commun de 3 000 communes ;
- la nouvelle production KRT à 3 000 communes, interrompue après 2 fits sur 12 dans ce gel.

Ces trois blocs ne doivent pas être fusionnés dans une même interprétation.

## 1. Préservation de la livraison V1

Le script `code_longitudinal/preserve_v1_integrity.py` établit les empreintes du périmètre historique protégé. Le résultat inclus est `outputs/v2/preservation_manifest_v1.json`, qui référence 129 fichiers. Les archives `deliverables/longitudinal_priority_results_clear.zip` et `deliverables/longitudinal_2022_release_01.zip`, accompagnées de leurs SHA-256, sont conservées dans la livraison.

Cette étape protège l’historique ; elle ne transforme aucun résultat.

## 2. Correction des agrégats historiques

Le script `code_longitudinal/postprocess_aggregates_v2.py` relit les tirages existants et remplace le dénominateur communal total par l’effectif du groupe social concerné :

```text
agrégat_groupe_1 = somme(N1_i × bêta1_i) / somme(N1_i)
agrégat_groupe_2 = somme(N2_i × bêta2_i) / somme(N2_i)
```

Il ne réestime pas les modèles V1. Les tableaux produits se trouvent dans `outputs/v2/priority_500_reanalysis/`, en particulier `corrected_estimates_v2.csv` et `aggregate_comparison_v2.csv`.

## 3. Diagnostic, identification et sensibilité des traces historiques

- `code_longitudinal/diagnostics_v2.py` produit un verdict MCMC unique couvrant R-hat, ESS, divergences, BFMI et profondeur d’arbre ;
- `code_longitudinal/identification_v2.py` calcule les métriques d’identification écologique ;
- le post-traitement calcule les contrastes intra-période, les changements entre dates et une sensibilité descriptive par bootstrap des communes.

Les sorties correspondantes sont `official_diagnostics_v2.csv`, `identification_metrics_v2.csv`, `within_period_contrasts_v2.csv`, `longitudinal_contrast_changes_v2.csv` et `panel_bootstrap_sensitivity_v2.csv`. Elles portent toutes sur les traces historiques.

## 4. Contrôles prédictifs postérieurs historiques

`code_longitudinal/ppc_v2.py` vérifie le mapping entre trace, parquet d’entrée et ordre des communes, puis simule des comptes binomiaux prédictifs. Les 12 résultats sont rassemblés dans `outputs/v2/ppc_krt/ppc_metrics.csv`, avec un CSV communal, un JSON de métriques et une figure PNG/SVG par run.

Une bonne couverture PPC décrit la calibration des marges observées ; elle ne prouve pas l’identification des comportements individuels.

## 5. Construction du panel commun de 3 000 communes

`code_longitudinal/build_common_panel_v2.py` :

1. construit un univers de référence 2022 avec identifiants harmonisés, six CSP complètes, VBBM et région ;
2. conserve les communes dont les marges électorales et CSP sont admissibles en 1962, 1986 et 2022 ;
3. intersecte ces ensembles avec l’univers de référence, ce qui donne 33 922 communes ;
4. permute cet univers avec `numpy.random.default_rng(seed)` et retient les 3 000 premières lignes ;
5. accepte le candidat seulement si les contrôles d’équilibre passent contre l’univers admissible et l’univers 2022 complet ;
6. incrémente la graine et recommence en cas de refus.

La graine initiale `20260802` est acceptée au premier essai. Le détail des règles, seuils et limites est fourni dans `docs/METHODE_ECHANTILLONNAGE_PANEL_3000.md`.

## 6. Préparation des douze jeux d’entrée

`code_longitudinal/prepare_priority_v2.py` prépare les combinaisons :

```text
3 élections × 4 hypothèses (H0A, H1, H2, H4) = 12 entrées
```

Les preuves incluses sont `outputs/v2/priority_model_ready_3000_audit.csv` et `outputs/v2/priority_model_ready_3000_manifest.json`. Elles confirment 3 000 communes dans chaque entrée, le même `sample_id`, des identifiants uniques et aucune exclusion.

Les douze Parquet modèle-ready eux-mêmes ne sont pas inclus dans l’archive.

## 7. Benchmark NLS sur le panel commun

`code_longitudinal/run_nls_priority_v2.py` orchestre `run_nls_batch.py` sur les douze entrées. Le fichier `outputs/v2/nls_priority/audit.json` indique `executed=true` et 12 succès. Chaque run conserve coefficients, estimations, diagnostic du modèle, diagnostic des départs, manifeste et pointeur `current.json`.

Ce bloc est un benchmark NLS 2×2 intercept-only. Il ne remplace pas les estimations KRT bayésiennes.

## 8. Production KRT à 3 000 communes

`code_longitudinal/run_priority_production_v2.py` planifie douze fits avec : 4 chaînes, 1 000 itérations de réglage, 1 000 tirages conservés, un cœur, `target_accept=0,99`, profondeur maximale 14 et graine `20260802`.

Au moment du gel :

| Run | Statut | Diagnostic officiel |
| --- | --- | --- |
| H0A-1962 | terminé | réserve : ESS bulk minimal sous le seuil de passage |
| H0A-1986 | terminé | réserve : R-hat maximal et ESS bulk minimal |
| 10 autres combinaisons | en attente | indisponible |

Le suivi canonique est `outputs/v2/priority_production_progress_v2.json`. Les deux lignes de synthèse sont aussi dans `priority_production_diagnostics_v2.csv` et les audits détaillés dans `outputs/v2/diagnostic_audits/`.

## 9. Figures et densités

`code_longitudinal/density_figures_v2.py` génère les densités jointes de `(bêta1, bêta2)` et les marginales. Les 24 couples PNG/SVG de `figures/v2/densities/` utilisent les traces historiques 500/494/500, car la production KRT à 3 000 n’était pas complète.

Les cinq autres figures de synthèse dans `figures/v2/priority_500_reanalysis/` et les douze PPC dans `figures/v2/ppc_krt/` ont la même portée historique.

## 10. Finalisation et empaquetage

`code_longitudinal/finalize_priority_results_v2.py` produit la synthèse professorale, la carte des figures, puis sélectionne les artefacts à inclure. Il conserve pour chaque run KRT terminé sept fichiers canoniques, mais exclut les traces NetCDF. Il ajoute aussi les archives V1 protégées et leur empreinte.

La livraison est volontairement intermédiaire : son nom contient `en_cours` et son état machine-lisible est `paused_by_user`.

## Chaîne de preuve minimale

Pour vérifier une affirmation sans dépendre du texte narratif, utiliser dans cet ordre :

1. `panel/*_manifest.json`, `*_attempts.csv` et `*_balance.csv` pour l’échantillonnage ;
2. `priority_model_ready_3000_audit.csv` pour les 12 entrées ;
3. `nls_priority/audit.json` pour le benchmark NLS ;
4. `priority_production_progress_v2.json` pour l’avancement KRT ;
5. le `manifest.json` et `mcmc_diagnostics_v2.json` de chaque run terminé ;
6. `validation_summary_v2.json` et les CSV de réanalyse pour les résultats historiques corrigés.

## Reproductibilité réelle de l’archive

L’archive permet d’auditer les résultats livrés, les identifiants du panel, les paramètres et les empreintes. Elle n’est pas autonome pour une reconstruction complète : les données brutes, plusieurs modules Python importés, les entrées Parquet et les traces NetCDF ne sont pas tous présents. Les commandes de recalcul doivent être lancées depuis le projet complet, pas depuis cette archive seule.
