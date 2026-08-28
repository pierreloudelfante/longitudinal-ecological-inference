# Guide des scripts du pipeline longitudinal

Ce document explique le rôle de chaque script Python livré, sa place dans le
pipeline et son importance. Il complète `METHODOLOGY_CODE_MAP.md`, consacré aux
équations, et `OUTPUT_SCHEMA.md`, consacré aux tables produites.

## Vue d'ensemble

Le flux normal est le suivant :

```text
archives brutes
  -> data_io.py
  -> build_panel.py + balance_checks.py
  -> prepare_inputs.py
  -> run_2x2_batch.py ou run_nls_batch.py ou run_rosen_benchmark.py
  -> run_registry.py
  -> build_outputs.py
  -> validate_outputs.py
  -> build_release.py
```

`run_pipeline.py` est le point d'entrée public qui orchestre ces étapes. Les
scripts d'analyse n'écrivent jamais directement dans un ancien run réussi :
chaque exécution reçoit un répertoire propre géré par `run_registry.py`.

### Niveaux d'importance

- **Critique** : modifie directement la définition des données ou les résultats
  statistiques.
- **Très important** : garantit l'orchestration, la traçabilité, la consolidation
  ou la validité des résultats.
- **Support** : produit des graphiques, de la documentation ou des artefacts de
  livraison sans modifier l'estimation statistique elle-même.

## 1. Point d'entrée et définition de l'étude

### `code_longitudinal/run_pipeline.py` — très important

Point d'entrée en ligne de commande :

```powershell
python -m code_longitudinal.run_pipeline --stage <stage>
```

Il lit `config/run_settings.json`, applique les valeurs par défaut et appelle les
modules spécialisés. Les stages disponibles sont `panel`, `schema-pilot`,
`abstention`, `2x2`, `rxc-nls`, `rxc-rosen-benchmark`, `robustness` et
`consolidate`.

Sans `--production`, les stages MCMC utilisent volontairement un smoke test de
25 communes, 20 draws, 20 itérations de réglage et une chaîne. Ces sorties
servent à vérifier le schéma et le coût du calcul ; elles ne sont pas des
résultats substantiels.

### `code_longitudinal/spec_registry.py` — critique

Définit le périmètre scientifique :

- les 15 législatives et 11 présidentielles entre 1962 et 2022 ;
- les colonnes FN/RN disponibles selon l'année ;
- les scénarios binaires H0A–H7 ;
- les scénarios multivariés RXC1–RXC2 ;
- les groupes sociaux, catégories de vote, dénominateurs et modèles autorisés.

Une nouvelle hypothèse doit être déclarée ici, et non codée en dur dans un
script d'estimation isolé. `planned_run_rows()` construit le registre de tous les
runs théoriquement prévus.

### `code_longitudinal/__init__.py` — support

Déclare `code_longitudinal` comme paquet Python et expose les registres
`ELECTIONS` et `SCENARIOS`.

## 2. Localisation, lecture et normalisation des données

### `code_longitudinal/paths.py` — support technique

Centralise les chemins vers `config/`, `panel/`, `outputs/`, `figures/`,
`docs/`, les runs et les archives brutes. `ensure_runtime_dirs()` crée les
répertoires nécessaires et place les caches Matplotlib, Numba et PyTensor dans
le projet.

### `code_longitudinal/utils.py` — très important

Regroupe les fonctions transversales :

- normalisation des codes commune sans perdre `2A` et `2B` ;
- traitement cohérent de Paris, Lyon et Marseille ;
- arrondi par plus forts restes garantissant une somme entière exacte ;
- écriture JSON ;
- empreintes SHA-256 et hachage canonique des configurations ;
- création des identifiants de runs et inventaire des versions logicielles.

La fonction `largest_remainder_round()` est particulièrement importante : elle
empêche les marges sociales ou politiques arrondies de cesser de sommer au
dénominateur électoral.

### `code_longitudinal/data_io.py` — critique

Lit directement les CSV contenus dans les archives ZIP historiques. Le module :

- repère un membre d'archive sans dépendre de sa casse ou de son sous-dossier ;
- charge les résultats électoraux et les six CSP ;
- harmonise les identifiants communaux ;
- charge VBBM, revenu, capital, immigration et région ;
- construit la covariable Nord-Est contre Sud-Est ;
- construit l'univers de référence admissible de 2022.

Les données brutes ne sont pas dupliquées dans la livraison. Elles sont attendues
dans `../pour_moi_avec_data/data/raw/archives/` relativement au projet de
travail.

## 3. Panel fixe et préparation des entrées

### `code_longitudinal/balance_checks.py` — critique pour le panel

Compare un échantillon à l'univers de référence. Pour les variables continues,
il calcule moyenne, écart-type, différence moyenne standardisée, distance KS et
quantiles. Pour les variables catégorielles, il calcule les écarts de
proportions. `balance_summary()` applique les seuils d'acceptation et vérifie
qu'aucune catégorie territoriale significative n'est vide.

### `code_longitudinal/build_panel.py` — critique

Construit un panel fixe de 3 000 communes et un pilote emboîté composé des 2 000
premiers rangs. Il essaie des permutations déterministes jusqu'à ce que les deux
panels satisfassent simultanément les critères de balance. Il enregistre :

- `panel/panel_3000.csv` et `panel/panel_2000.csv` ;
- les contrôles et tentatives de balance ;
- les figures de comparaison ;
- un manifeste avec graine, définition de l'univers et empreintes des sources.

La sélection est indépendante des résultats électoraux étudiés.

### `code_longitudinal/prepare_inputs.py` — critique

Transforme les données historiques en tables prêtes pour les modèles. Pour une
élection et un scénario, il :

1. lit le panel dans l'ordre fixé ;
2. joint élections, CSP et covariables ;
3. documente les communes absentes ou invalides ;
4. construit les partitions sociales et politiques ;
5. recale et arrondit les comptes pour fermer exactement sur `N_g` ;
6. vérifie `sum(X)=1`, `sum(N)=N_g` et `sum(Y)=N_g` ;
7. écrit CSV, Parquet, exclusions et manifeste dans `outputs/model_ready/`.

Le même module construit également le registre commune × élection de présence
sur les 26 scrutins. Toute erreur ici affecte directement toutes les estimations
en aval.

### `code_longitudinal/prepare_all_partitions.py` — critique pour l'audit longitudinal

Parcourt les 26 élections et tous les scénarios admissibles à `n=3000`. Chaque
couple appelle `prepare_model_ready`; un échec est enregistré sans interrompre
les autres. Le journal exhaustif est
`outputs/all_elections_partition_preparation.json`.

## 4. Modèles statistiques

### `code_longitudinal/run_2x2_batch.py` — critique

Cœur des modèles binaires. Il prépare puis ajuste avec PyEI :

- `king_truncated_normal`, correspondant à `truncated_normal` ;
- `krt_beta_binomial`, correspondant à `king99`.

Le script filtre les lignes incompatibles avec la tomographie de la normale
tronquée, lance le MCMC, enregistre la trace NetCDF, extrait `b_1` et `b_2` par
commune, calcule les estimations agrégées et produit les diagnostics de
convergence. Il mesure aussi temps et mémoire avant d'autoriser le palier de
taille suivant.

Sorties principales par run : `longitudinal_estimates.csv`,
`commune_latent_summaries.*`, `model_diagnostics.csv`, `excluded_units.csv`,
`trace.nc` et les décisions de palier.

### `code_longitudinal/run_pilot_ladder.py` — très important pour le pilote

Exécute H0A–H5 en 1962 et H0A–H7 en 1986 et 2022, pour King et KRT,
selon les paliers `25 → 100 → 250 → 500 → 1000 → 2000 → 3000`. Chaque
ajustement tourne dans un processus isolé afin de mesurer son propre pic
mémoire. Le batch s'arrête pour un couple seulement si le garde-fou temps ou
mémoire bloque le palier suivant. Les réglages `20/20/1` sont explicitement de
calibration.

Le mode `--missing-hypotheses` cible H0B/H0C/H2/H3/H4. Le mode
`--retry-extension-resource-limited` reprend au premier palier manquant. Il ne
contourne pas le garde-fou : la prévision mémoire utilise l'enveloppe empirique
du même modèle, majorée de 10 %, et la compare encore au plafond de 80 %.

### `code_longitudinal/nls.py` — critique

Implémentation mathématique indépendante du modèle Rosen NLS :

- paramétrisation softmax avec dernière catégorie de vote comme référence ;
- calcul des probabilités latentes et marges ajustées ;
- objectif SSE non pondéré sur les `C-1` premières catégories ;
- départ groupé, départ nul et départs aléatoires déterministes ;
- optimisation multi-départs avec `scipy.optimize.least_squares` ;
- matrice sandwich, rang, conditionnement et valeurs singulières ;
- agrégation pondérée par les effectifs des groupes sociaux.

Ce module contient les équations et algorithmes ; il ne gère pas directement les
fichiers de run.

### `code_longitudinal/run_nls_batch.py` — critique

Relie `nls.py` au pipeline. Il prépare les données, standardise une éventuelle
covariable, exécute les 20 départs, choisit le meilleur ajustement et exporte :

- probabilités agrégées par groupe social et catégorie de vote ;
- coefficients et erreurs-types sandwich ;
- diagnostics de chaque départ ;
- rang, conditionnement, coût et statut de l'optimiseur ;
- exclusions dues aux données ou à la covariable.

Pour un scénario 2 × 2, le NLS n'est autorisé que comme analyse de robustesse
avec covariable explicite.

### `code_longitudinal/run_rosen_benchmark.py` — important

Exécute le modèle bayésien PyEI `RowByColumnEI("multinomial-dirichlet")` afin de
comparer le NLS à une approche RxC MCMC. Il conserve trace, intervalles,
diagnostics, durée et mémoire. Le benchmark est volontairement limité à RXC1
tant que ce scénario n'a pas été validé à une échelle suffisante.

### `code_longitudinal/run_robustness.py` — important mais ciblé

Déclare et exécute la matrice de robustesse 2022 : VBBM, revenu, capital,
immigration et indicatrice Nord-Est/Sud-Est. Chaque combinaison appelle
`run_nls_batch.run_nls()` et conserve séparément les échecs éventuels.

## 5. Runs, schémas et consolidation

### `code_longitudinal/run_registry.py` — très important

Assure la reproductibilité opérationnelle. Une clé déterministe dépend du stage,
des paramètres et des empreintes des entrées. Si cette clé possède déjà un run
réussi, l'exécution est reprise sans écrasement, sauf demande `--force`.

Chaque tentative possède un répertoire immuable avec manifeste. Le registre
privé `run_registry_executed.csv` ne contient que les exécutions ; la vue
publique consolidée ajoute les configurations encore planifiées.

### `code_longitudinal/output_schema.py` — très important

Définit les colonnes contractuelles de toutes les tables : estimations,
diagnostics, latents, coefficients NLS, exclusions, garde-fous et β communaux.
`initialize_output_schema()` crée les CSV et Parquet vides attendus. Modifier une
table analytique sans mettre ce contrat à jour peut casser consolidation, tests
et validation.

### `code_longitudinal/beta_outputs.py` — important

Transforme les résumés latents 2 × 2 en table longue avec une ligne par run,
commune et paramètre `b_1`/`b_2`. Il ajoute les métadonnées de comparaison,
construit l'index SHA-256 des traces NetCDF et dérive les données de densité des
moyennes postérieures communales.

### `code_longitudinal/extract_latent_densities.py` — support analytique

Construit les densités marginales et les couples `(b1_mean, b2_mean)`. Il produit
une vue native par modèle et une vue sur l'intersection exacte des communes King
et KRT. Les densités sont calculées par KDE, avec repli sur un histogramme en cas
de données insuffisantes ou singulières. Il génère également les figures
marginales, conjointes et comparatives. `curated/` conserve une superposition
par couple pilote, choisie au plus grand palier commun ; le repli natif est
signalé lorsque la comparaison exacte est impossible.

### `code_longitudinal/pilot_outputs.py` — très important pour la transparence

Relit les manifestes des 270 partitions matérialisées et les runs réussis pour
construire `all_elections_partition_integrity.csv` et
`pilot_model_coverage.csv`. Il ne réestime aucun modèle : il rend la couverture
réellement atteinte vérifiable et évite de la déduire d'un dernier batch pouvant
contenir des reprises ou blocages.

### `code_longitudinal/plot_longitudinal.py` — support analytique

Sélectionne le plus grand palier comparable par élection et modèle, puis trace
l'évolution des probabilités estimées et l'écart entre les deux premiers groupes
sociaux. Il exporte PNG et SVG dans `figures/longitudinal/` dans le projet de
travail ; la livraison ne conserve que les SVG non dupliqués.

### `code_longitudinal/plot_election_2022.py` — support analytique

Produit les vues adaptées à une seule élection, sans relier artificiellement
2022 à une autre année. Pour RXC1 et RXC2 NLS à 3 000 communes, le module
construit la matrice groupe × vote, les barres de composition et le diagnostic
communal observé-prédit. Pour H0A–H7, il trace uniquement les marges d'entrée
et les étiquette comme descriptives tant que les ajustements PyEI de production
ne sont pas validés. Il exporte aussi les tables d'intégrité et de qualité
d'ajustement utilisées par `validate_outputs.py`.

### `code_longitudinal/build_illustrated_report.py` — support analytique et audit

Relit la sélection des treize densités pilotes et les β communaux joints. Il
vérifie l'intersection exacte des identifiants King/KRT, calcule pour chaque
année et groupe la moyenne communale, l'écart-type et les quartiles entre
communes, puis écrit `outputs/illustrated_report_estimates.csv`. Il génère cinq
comparaisons interannuelles en PNG/SVG et le document
`docs/RESULTS_ILLUSTRATED_1962_1986_2022.md`, qui intègre aussi les treize
densités. Les années ne sont pas reliées par une ligne et P25–P75 n'est jamais
présenté comme un intervalle de crédibilité.

### `code_longitudinal/build_professor_global_recap.py` — support de livraison

Réutilise la même sélection d'intersections et le même calcul communal pour
H0A, H0B, H0C, H1, H2, H3, H4 et H5. Il écrit la table exacte
`outputs/professor_canonical_comparisons.csv`, génère huit figures à trois
coupes dans `figures/professor_recap/` et construit
`docs/PROFESSOR_GLOBAL_RECAP_1962_1986_2022.md`. Le document rassemble aussi
l'inventaire des sorties, un exemple de chaque famille graphique, les
dénominateurs et les limites d'interprétation.

### `code_longitudinal/build_outputs.py` — très important

Consolide le dernier succès sélectionné de chaque configuration. Il reconstruit
les tables racines, le registre public, les β, les densités et les figures. Les
runs échoués ou supersédés ne sont pas mélangés aux estimations consolidées,
mais restent traçables dans le dépôt de travail.

### `code_longitudinal/build_figure_catalog.py` — support d'audit

Parcourt tous les SVG après consolidation et régénère
`docs/FIGURE_CATALOG.md`. Le document groupe les figures par famille, indique
leur table source, leur statut d'interprétation et fournit un lien vers chaque
fichier.

## 6. Validation, revue et livraison

### `code_longitudinal/validate_outputs.py` — très important

Produit le verdict machine-lisible de la livraison. Les contrôles couvrent :

- taille, unicité, emboîtement et balance des panels ;
- présence des 26 scrutins ;
- fermeture exacte des tables prêtes pour modèle ;
- schémas et clés uniques des tables consolidées ;
- bornes, ordre des intervalles et quantiles ;
- correspondance des intersections King/KRT ;
- vingt départs par run NLS ;
- existence des traces, répertoires de runs et éléments du paquet de revue.
- préparation exacte des dix scénarios 2×2 à 3 000 communes en 2022,
  matrices RXC1/RXC2 complètes, qualité des marges reconstruites, figures et
  couverture PyEI de production explicitement signalée lorsqu'elle manque.
- registre des 292 partitions, fermeture des 270 matérialisées et traçabilité
  des 22 refus RXC ;
- couverture explicite des 56 couples du pilote étendu et correspondance entre
  sélections et densités propres disponibles.
- schéma, bornes, clés et 18 références d'images du rapport illustré.

Les résultats sont écrits dans `outputs/validation_checks.csv`,
`outputs/validation_summary.json` et `docs/VALIDATION_REPORT.md`.

### `code_longitudinal/review_package.py` — support de revue

Crée `review_for_professor_01/` avec panels, documents méthodologiques, extraits
des 50 premières lignes des tables et figures. Son README rappelle la couverture
réelle, les runs réussis ou échoués et les limites d'interprétation.

### `code_longitudinal/build_manifest.py` — support d'intégrité

Inventorie les fichiers du projet hors caches et livraisons déjà construites.
Pour chaque fichier, il enregistre chemin relatif, rôle, taille et SHA-256 dans
`outputs/file_manifest.csv`.

### `code_longitudinal/build_release.py` — très important pour la livraison

Construit `deliverables/longitudinal_2022_release_01.zip`. Il sélectionne le
code, la configuration, la documentation, les tests, panels, sorties, figures et
traces nécessaires ; élimine les caches et formats dupliqués ; crée
`PACKAGE_MANIFEST.csv` ; puis vérifie toutes les empreintes, les traces indexées
et l'intégrité du ZIP.

Il ne relance pas les modèles statistiques. Il empaquette les résultats déjà
consolidés et validés.

## 7. Scripts de test

### `tests/conftest.py`

Ajoute la racine du projet au chemin Python et localise les caches Matplotlib et
Numba dans le projet.

### `tests/test_panel.py`

Vérifie les mesures de balance, la taille et l'emboîtement des panels, la
stabilité des identifiants et les 26 enregistrements de présence par commune.

### `tests/test_partitions.py`

Vérifie l'arrondi déterministe, la conservation des codes corses et la fermeture
exacte des partitions prêtes pour modèle.

### `tests/test_nls.py`

Teste le softmax, les bornes, la catégorie de référence, les marges ajustées,
l'objectif SSE, la récupération sur données synthétiques, la stabilité des
départs, les erreurs-types sandwich et l'agrégation pondérée.

### `tests/test_outputs.py`

Teste le registre des élections et scénarios, les schémas, l'extraction des
latents, l'intersection King/KRT, la reprise sans écrasement, les garde-fous de
temps et mémoire, l'unicité des β consolidés et le calcul observé-prédit 2022.

Commande :

```powershell
python -m pytest -q -p no:cacheprovider tests
```

## 8. Ordre de lecture recommandé

Pour comprendre rapidement le projet :

1. `run_pipeline.py` pour l'enchaînement ;
2. `spec_registry.py` pour les objets scientifiques ;
3. `data_io.py` et `prepare_inputs.py` pour la construction des données ;
4. `run_2x2_batch.py` pour King/KRT ;
5. `nls.py` puis `run_nls_batch.py` pour le RxC ;
6. `run_registry.py` et `build_outputs.py` pour la traçabilité ;
7. `validate_outputs.py` pour les critères de validité ;
8. `build_release.py` pour comprendre le contenu exact du ZIP.

## 9. Limites à garder visibles

- Une relation écologique n'est pas une observation individuelle.
- Les communes absentes historiquement ne sont ni remplacées ni imputées.
- Le panel rétrospectif est défini sur l'univers admissible de 2022.
- Un run marqué `warning` ou un smoke test à une chaîne n'est pas substantiel.
- Les intervalles agrégés NLS ne sont pas déclarés validés.
- Le ZIP contient les preuves et sorties sélectionnées, mais pas les archives
  brutes nécessaires à de nouveaux ajustements.
