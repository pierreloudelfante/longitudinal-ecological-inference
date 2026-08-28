# Pipeline longitudinal KRT/NLS — panel fixe de 2 000 communes

Ce dépôt de travail produit des estimations d’inférence écologique sur 26 scrutins français, avec un même panel longitudinal de 2 000 communes. Il contient une production en cours : les résultats intermédiaires ne constituent pas une release validée.

## Contrat courant

- panel : `panel/longitudinal_2000_v1.parquet` ;
- identifiant : `longitudinal_2000_v1__strict_nested_3000__seed_20260803` ;
- SHA-256 : `bde70c71660fce29610d7931461d8db6181dba874514a1866b63cf16a81cec4a` ;
- NLS : 292 couples préparés et estimés, dont 270 dans le périmètre public v1.0.2 et 22 RxC conservés comme extension auditée ;
- KRT Python : 240 couples 2×2 attendus pour H0A–H7, avec H6/H7 admissibles sur 16 élections chacun ;
- KRT R : réplication exacte NIMBLE prévue après la fin des tentatives initiales et relances Python ;
- NetCDF : artefacts temporaires de post-traitement, exclus des archives de livraison.

Le statut machine-lisible le plus récent est :

```text
outputs/longitudinal_2000_v1/production/current_estimation_coverage.json
```

La sélection et les tables KRT partielles sont :

```text
outputs/longitudinal_2000_v1/production/all_2x2_candidate/
```

## Carte de la chaîne

```text
archives sources
  -> audit et harmonisation politique/sociale
  -> panel longitudinal fixe et matrices model_ready
  -> NLS Python/R
  -> KRT Python (tentative initiale)
  -> diagnostic MCMC | identification écologique | alerte KRT–NLS
  -> relance ciblée unique si MCMC sévère/fail
  -> sélection canonique
  -> KRT R/NIMBLE exact
  -> comparaison Python/R
  -> Parquet, figures, rapport et archives vérifiées
```

Ces trois diagnostics restent distincts :

1. `mcmc_status` mesure la qualité numérique des chaînes ;
2. `identification_status` décrit la largeur des contraintes écologiques ;
3. `method_sensitivity_status` signale un écart KRT–NLS et ne modifie jamais les priors ou `king_lambda` de façon opportuniste.

## Configuration faisant autorité

Chaque production KRT est définie par un fichier dans `config/releases/`. Le scope de release porte le panel, les scénarios, les pilotes, la paramétrisation KRT versionnée, `king_lambda`, les réglages MCMC et les graines. `config/run_settings.json` reste nécessaire pour la préparation des données et la compatibilité avec les anciens scripts, mais ne doit pas remplacer le contrat KRT de la release.

Exemples :

```text
config/releases/v1.1_pymc_fallback.json   H2/H3
config/releases/v1.2_pymc_h6_h7.json      H6/H7
config/releases/v1.3_pymc_h0b_h0c.json    H0B/H0C
config/releases/v1.4_pymc_h4_h5.json      H4/H5
```

Les runs utilisent quatre chaînes, 1 000 itérations de chauffe, 1 000 tirages conservés, `target_accept=0.99`, `max_treedepth=14` et une graine déterministe par couple. Une relance admissible utilise 2 000 + 2 000 et la graine de base dédiée.

## Entrées et sorties importantes

| Élément | Emplacement | Grain |
|---|---|---|
| Panel | `panel/longitudinal_2000_v1.parquet` | commune |
| Matrices | `outputs/model_ready/` | commune × élection × scénario |
| Runs | `outputs/runs/<run_id>/` | un ajustement |
| Couverture | `outputs/longitudinal_2000_v1/production/current_estimation_coverage.csv` | scénario |
| KRT communes partiel | `outputs/longitudinal_2000_v1/production/all_2x2_candidate/longitudinal_krt_commune_240_candidate.parquet` | commune × run |
| KRT agrégé partiel | `outputs/longitudinal_2000_v1/production/all_2x2_candidate/longitudinal_krt_aggregate_240_candidate.parquet` | run × estimand |
| Sélection partielle | `outputs/longitudinal_2000_v1/production/all_2x2_candidate/krt_240_candidate_selection.csv` | élection × scénario |
| NLS complet candidat | `outputs/longitudinal_2000_v1/production/rxc_nls_panel_extension_v11/longitudinal_nls_292_candidate.parquet` | couple × estimand |
| Réplication R exacte | `outputs/longitudinal_2000_v1/r_replication/` | couple × estimand |

## Commandes principales

Depuis ce dossier, avec l’environnement Python EI :

```powershell
$python = '..\pour_moi_avec_data\.venv-ei\Scripts\python.exe'

& $python -m code_longitudinal.v11_pipeline krt `
  --release-config config\releases\v1.1_pymc_fallback.json `
  --cores 1

& $python -m code_longitudinal.consolidate_current_krt_all_2x2
& $python -m code_longitudinal.build_current_estimation_coverage
& $python -m pytest -q tests
```

Les scripts de reprise vérifient les manifestes de succès avant chaque fit : un succès déjà présent avec le même contrat n’est pas recalculé.

## Reproduction

- **Niveau 1 — audit** : ouvrir les Parquet, CSV, figures et manifestes livrés ; aucune donnée source n’est nécessaire.
- **Niveau 2 — consolidation** : utiliser le bundle technique, les runs déjà calculés et l’environnement documenté.
- **Niveau 3 — reproduction complète** : le dépôt parent et les archives brutes de `../pour_moi_avec_data/data/raw/archives/` sont requis.

L’ancien README, qui décrivait principalement la production historique à 3 000 communes, est conservé dans `legacy/README_pre_longitudinal_2000_v1.md`.
