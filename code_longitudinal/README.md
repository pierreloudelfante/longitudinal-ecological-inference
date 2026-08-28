# Code du pipeline longitudinal

Ce paquet contient l'implémentation canonique de l'extension 1962–2022. Le
point d'entrée public est :

```powershell
python -m code_longitudinal.run_pipeline --stage <stage>
```

Les stages disponibles sont `panel`, `schema-pilot`, `abstention`, `2x2`,
`rxc-nls`, `rxc-rosen-benchmark`, `robustness` et `consolidate`.

Le guide détaillé de chaque script, de ses entrées, sorties et dépendances est
dans `../docs/SCRIPT_GUIDE.md`. Les équations et leur correspondance avec les
fonctions sont dans `../docs/METHODOLOGY_CODE_MAP.md`.

## Carte complète des modules

| Module | Responsabilité principale | Importance |
|---|---|---|
| `run_pipeline.py` | point d'entrée et orchestration des stages | très importante |
| `spec_registry.py` | registre des 26 scrutins et scénarios H0A–H7/RXC1–RXC2 | critique |
| `paths.py` | chemins du projet et localisation des caches | support |
| `utils.py` | identifiants communaux, PLM, arrondi exact, JSON et hachage | très importante |
| `data_io.py` | lecture des archives, identifiants stables, covariables et univers 2022 | critique |
| `balance_checks.py` | mesures et verdict de balance des panels | critique pour le panel |
| `build_panel.py` | panel fixe de 3 000 communes et pilote emboîté de 2 000 | critique |
| `build_common_panel_v2.py` | panel commun exact de 3 000 communes admissibles en 1962/1986/2022 | critique pour la production finale |
| `prepare_inputs.py` | partitions sociales/politiques et tables prêtes pour modèle | critique |
| `prepare_all_partitions.py` | préparation exhaustive des 292 couples admissibles | critique pour l'audit longitudinal |
| `run_pilot_ladder.py` | paliers King/KRT isolés pour 1962/1986/2022 | très importante pour le pilote |
| `pilot_outputs.py` | synthèses de couverture et d'intégrité des partitions | très importante pour la transparence |
| `run_2x2_batch.py` | modèles King/KRT, diagnostics, traces et β communaux | critique |
| `run_priority_production_v2.py` | plan reprenable H0A/H1/H2/H4 sur panel commun, avec filtres ciblés | critique pour la production finale |
| `diagnostics_v2.py` | verdict MCMC canonique unique sur toutes les variables postérieures | critique pour l’audit final |
| `postprocess_aggregates_v2.py` | agrégats KRT draw-wise avec dénominateurs propres aux groupes | critique pour les estimands publiés |
| `identification_v2.py` | diagnostic d’identification écologique séparé du MCMC | importante pour l’interprétation |
| `density_figures_v2.py` | densités jointes/marginales à bandwidth commun entre périodes | support analytique final |
| `finalize_priority_results_3000.py` | contrôle des six fits, résultats, figures, rapport et ZIP complet | critique pour la livraison finale |
| `build_chatgpt_package_3000.py` | paquet de revue sous 500 Mo avec tous les résultats et deux traces représentatives | support de livraison |
| `nls.py` | équations, optimisation multi-départs et sandwich du modèle NLS | critique |
| `run_nls_batch.py` | exécution, diagnostics et export du NLS | critique |
| `run_rosen_benchmark.py` | benchmark RxC multinomial-Dirichlet | importante |
| `run_robustness.py` | matrice des analyses de robustesse avec covariables | importante mais ciblée |
| `run_registry.py` | clés déterministes, reprise et runs immuables | très importante |
| `output_schema.py` | contrats de colonnes et initialisation des sorties | très importante |
| `beta_outputs.py` | table β communale et index des traces postérieures | importante |
| `extract_latent_densities.py` | densités et intersections comparables King/KRT | support analytique |
| `plot_longitudinal.py` | figures temporelles et écarts entre groupes | support analytique |
| `plot_election_2022.py` | figures mono-élection, ajustement NLS et audit des dix entrées 2×2 à n=3 000 | support analytique |
| `build_illustrated_report.py` | table des β comparables, cinq figures interannuelles et rapport Markdown illustré | support analytique et audit |
| `build_professor_global_recap.py` | inventaire global, huit comparaisons canoniques et récapitulatif professeur | support analytique et livraison |
| `build_figure_catalog.py` | catalogue exhaustif des figures, portées et tables sources | support d'audit |
| `build_outputs.py` | sélection des succès et consolidation des sorties | très importante |
| `validate_outputs.py` | contrôles structurels et statistiques de livraison | très importante |
| `review_package.py` | paquet compact destiné à la revue professorale | support |
| `build_manifest.py` | inventaire des fichiers et empreintes SHA-256 | support |
| `build_release.py` | ZIP nettoyé, manifeste et vérification d'intégrité | très importante pour la livraison |
| `__init__.py` | déclaration du paquet et exports publics | support |

## Enchaînement normal

```text
data_io
  -> build_panel + balance_checks
  -> prepare_inputs
  -> run_2x2_batch / run_nls_batch / run_rosen_benchmark
  -> run_registry
  -> build_outputs
  -> validate_outputs
  -> build_release
```

`run_pipeline.py` appelle ces modules selon le stage demandé. Sans
`--production`, les stages MCMC utilisent 20 draws, 20 itérations de réglage
et une chaîne ; le palier peut atteindre 3 000 mais ces sorties ne doivent
toujours pas être interprétées comme substantielles.

Préparation exhaustive des partitions :

```powershell
python -m code_longitudinal.prepare_all_partitions --sample-size 3000
```

Pilote King/KRT isolé jusqu'au palier autorisé :

```powershell
python -m code_longitudinal.run_pilot_ladder --max-rung 3000
```

Extension H0B/H0C/H2/H3/H4 et reprise empirique sans contourner les garde-fous :

```powershell
python -m code_longitudinal.run_pilot_ladder --max-rung 3000 --missing-hypotheses
python -m code_longitudinal.run_pilot_ladder --max-rung 3000 --retry-extension-resource-limited
```

Lot de production limité aux quatre hypothèses principales comparables en
1962/1986/2022 (`H0A`, `H1`, `H2`, `H4`) :

```powershell
python -m code_longitudinal.run_priority_production --sample-size 2000 --cores 4
```

Le lot impose `4 × 1 000` tirages après `1 000` itérations de réglage,
`target_accept=0.99`, reprend les succès existants et audite aussi BFMI et les
atteintes de profondeur d'arbre en plus de R-hat, ESS et divergences.

Production finale ciblée H0A/H1 sur le panel commun exact :

```powershell
python -m code_longitudinal.run_priority_production_v2 --scenario H0A --scenario H1
python -m code_longitudinal.finalize_priority_results_3000 --check-ready
python -m code_longitudinal.finalize_priority_results_3000
python -m code_longitudinal.build_chatgpt_package_3000
```

Le finaliseur exige exactement six succès distincts, le SHA-256 du même panel, 4 chaînes, 1 000 tune, 1 000 draws par chaîne, `target_accept=0.99` et `max_treedepth=14`. Il recalcule les agrégats depuis les traces et refuse la livraison si ceux-ci ne concordent pas avec les exports des runs.

## Conventions de modification

- Ne pas écrire directement dans un ancien répertoire de run.
- Ajouter une élection ou un scénario dans `spec_registry.py`, pas dans un
  script isolé.
- Garder les colonnes compatibles avec `output_schema.py`.
- Toute modification des partitions, des β ou du NLS doit être accompagnée
  d'un test.
- Mettre à jour `docs/SCRIPT_GUIDE.md` lorsqu'un module change de rôle.
- Exécuter `consolidate`, puis `build_release`, après toute modification
  substantielle des résultats ou de la documentation livrée.
