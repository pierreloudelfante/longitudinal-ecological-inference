# Livraison longitudinale Cagé–Piketty 1962–2022

## Verdict à lire avant les figures

Cette archive est un paquet minimal, auditable et reproductible du pipeline
longitudinal. Elle contient le code, la configuration, les tests, le panel, les
entrées validées, les succès statistiques sélectionnés, leurs traces, les
tables consolidées, les figures et la documentation nécessaire. Les archives
brutes historiques restent dans le dépôt parent et ne sont pas dupliquées.

État exact de la livraison :

- registre complet : 15 législatives et 11 présidentielles, 1962–2022 ;
- panel fixe : 3 000 communes, pilote emboîté de 2 000, graine `20260802` ;
- partitions : 292 couples admissibles contrôlés, 270 valides et matérialisés,
  22 RXC refusés sur incohérence de marge brute supérieure à `0,01` voix ;
- pilote King/KRT 1962–1986–2022 : 52/56 couples modèle–scénario au palier
  demandé 3 000 ; les cinq hypothèses ajoutées H0B/H0C/H2/H3/H4 atteignent
  toutes 3 000 pour King et KRT sur les trois dates ; 3 couples restent limités
  par les ressources et 1 est structurellement inapplicable ;
- NLS : RXC1 et RXC2 passent en 1986/2022 ; les deux scénarios 1962 convergent
  mais sont conservés avec diagnostic `fail` pour défaut de rang ;
- MCMC de production : **aucun résultat `4 chaînes × 1 000 draws` validé** ;
- validation : 57 contrôles réussis, 0 échec, 3 avertissements ;
- tests : 31 réussis.

Atteindre un palier demandé de 3 000 ne rend pas une estimation substantielle.
Les traces PyEI du pilote utilisent 20 draws, 20 tune et une chaîne. Elles
valident le chemin algorithmique et la faisabilité de taille, pas les thèses
empiriques de Cagé et Piketty.

## Organisation du ZIP

```text
longitudinal_2022_release_01/
├── README.md
├── PACKAGE_MANIFEST.csv
├── requirements-dev.txt
├── code_longitudinal/
├── config/
├── docs/
├── panel/
├── outputs/
│   ├── model_ready/
│   └── runs/
├── figures/
└── tests/
```

Il n'y a ni cache, ni bytecode, ni dossier temporaire, ni copie du paquet
professeur dans le ZIP. Les grandes tables sont conservées en Parquet lorsque
le CSV ferait doublon ; les figures ne sont conservées qu'en SVG. Chaque
dossier important possède un README local.

## 1. Panel et balance

L'univers de référence comprend 34 644 communes admissibles en 2022. Le panel
est une permutation sans remise indépendante des votes. Les 2 000 premiers
rangs du même tirage forment le pilote emboîté.

Pour une variable continue (z),

\[
SMD(z)=\frac{\bar z_S-\bar z_U}{s_U}.
\]

Les deux panels doivent simultanément satisfaire `max |SMD| ≤ 0,10`, un écart
catégoriel région/VBBM `≤ 0,02` et aucune catégorie territoriale vide.

| Panel | max \(|SMD|\) | max écart catégoriel | Verdict |
|---|---:|---:|---|
| 3 000 | 0,024499 | 0,009710 | accepté |
| 2 000 | 0,028289 | 0,012308 | accepté |

Les variables continues sont `log1p(inscrits)`, ouvriers, employés, cadres et
agriculteurs + indépendants ; les variables catégorielles sont région et VBBM.
KS et quantiles sont descriptifs. Voir `docs/BALANCE_TESTS.md`.

## 2. Partitions sur les 26 élections

Les six CSP sont recalées proportionnellement vers le dénominateur électoral,
puis fermées par plus forts restes. Pour toute table matérialisée :

\[
\sum_r X_{ir}=1,\qquad \sum_r N_{ir}=N_i,\qquad \sum_cY_{ic}=N_i.
\]

Le contrôle politique dépend de la partition utilisée : votants/inscrits pour
H0, bloc cible/complement pour H1–H7 et cinq blocs bruts pour RXC. Les 240
partitions 2×2 passent toutes. Sur les 52 partitions RXC, 30 passent et 22 sont
refusées : législatives 1993, 2002, 2007, 2012, 2017 et présidentielles 1974,
1995, 2007, 2012, 2017, 2022, pour RXC1 et RXC2.

Une commune historique absente n'est jamais remplacée. Le détail des 292
couples se trouve dans `outputs/all_elections_partition_integrity.csv` et
`docs/ALL_ELECTION_PARTITIONS_REPORT.md`.

## 3. Modèles 2×2 et bêta communaux

Pour la commune (i),

\[
y_i=x_i\beta_{1i}+(1-x_i)\beta_{2i}.
\]

`king_truncated_normal` appelle PyEI `truncated_normal` ;
`krt_beta_binomial` appelle PyEI `king99`. Les tirages `b_1` et `b_2` sont
conservés dans `trace.nc`. Par commune et paramètre,
`commune_beta_estimates` exporte moyenne, écart-type et quantiles.

La densité principale porte sur les moyennes postérieures communales
(E(\beta_i\mid\text{marges})), une commune comptant une fois. Elle n'empile
pas tous les tirages et ne décrit pas des individus observés.

## 4. Pilote 1962–1986–2022

Le pilote couvre H0A–H5 en 1962 et H0A–H7 en 1986 et 2022. Les cinq hypothèses
ajoutées sont H0B (ouvriers × abstention), H0C (employés × abstention), H2
(ouvriers × gauche), H3 (employés × gauche) et H4 (agriculteurs+indépendants ×
droite). Les paliers communs sont `25 → 100 → 250 → 500 → 1000 → 2000 → 3000`.

| Élection | Couples King/KRT ciblés | Atteignent n=3 000 | Limitations |
|---|---:|---:|---|
| 1962 | 16 | 15 | King H5 sans ligne intérieure |
| 1986 | 20 | 18 | KRT H6/H7 limité par mémoire |
| 2022 | 20 | 19 | KRT H5 limité par mémoire |
| **total** | **56** | **52** | **3 ressources, 1 structure** |

Le garde-fou ne change pas la cible. Il empêche seulement le palier suivant si
sa durée projetée dépasse 12 heures ou si son pic mémoire dépasse 80 % de la
mémoire disponible. Chaque ajustement est mesuré dans un processus isolé.

Les 28 figures propres disponibles se trouvent dans
`figures/densities/curated/`. Le rapport
`docs/RESULTS_ILLUSTRATED_1962_1986_2022.md` en intègre 13 et ajoute cinq
comparaisons interannuelles. Vingt-quatre densités
emploient une comparaison King/KRT au palier demandé 3 000. H6 en 1986 reste
comparé au palier 500 ; H7 en 1986 et H5 en 2022 restent au palier 25 ; H5 en
1962 est une vue KRT native.
Les titres exposent palier, intersection, draws, chaînes et diagnostics. Voir
`docs/PILOT_1962_1986_2022_REPORT.md`.

Le document `docs/PROFESSOR_GLOBAL_RECAP_1962_1986_2022.md` fournit la vue
d'ensemble : inventaire des sorties, exemples des familles graphiques et huit
comparaisons canoniques H0A–H5 alimentées exactement par
`outputs/professor_canonical_comparisons.csv`.

## 5. NLS RXC

Le NLS sans covariable pose une matrice constante groupe × vote :

\[
\pi_{rc}=\operatorname{softmax}(\eta_{r1},\ldots,\eta_{r,C-1},0)_c,
\qquad \widehat t_{ic}=\sum_r x_{ir}\pi_{rc}.
\]

La dernière catégorie est la référence. Les résidus portent sur `C−1`
catégories, la SSE est non pondérée et l'optimiseur est
`least_squares(method="trf", loss="linear")`, 5 000 évaluations et tolérances
`1e-9`. Vingt départs déterministes sont conservés.

| Élection | Scénario | Communes utilisées | Diagnostic |
|---|---|---:|---|
| 1962 | RXC1 | 2 985 | `fail`, rang 11/12 |
| 1962 | RXC2 | 2 985 | `fail`, rang 19/24 |
| 1986 | RXC1 | 2 962 | `pass` |
| 1986 | RXC2 | 2 962 | `pass` |
| 2022 | RXC1 | 3 000 | `pass` |
| 2022 | RXC2 | 3 000 | `pass` |

En 1962, le centre est presque partout nul ; le défaut d'identification n'est
pas masqué. Les intervalles agrégés NLS restent absents faute de méthode
d'incertitude validée.

## 6. Tables principales

| Fichier | Rôle |
|---|---|
| `longitudinal_estimates.*` | 1 706 estimations agrégées avec clés et statut |
| `model_diagnostics.csv` | 385 diagnostics d'ajustement |
| `commune_latent_summaries.parquet` | 337 327 résumés latents communaux |
| `commune_beta_estimates.*` | 674 654 lignes bêta, soit b1/b2 par commune |
| `beta_trace_index.csv` | 370 traces NetCDF, taille et SHA-256 |
| `beta_density_data.parquet` | 577 272 points de densité reproductibles |
| `nls_coefficients.csv` | 172 coefficients |
| `nls_start_diagnostics.csv` | 240 diagnostics de départ |
| `excluded_units.csv` | exclusions, étape et raison |
| `pilot_model_coverage.csv` | couverture exacte des 56 couples du pilote étendu |
| `pilot_density_selection.csv` | provenance des 28 densités propres disponibles |
| `docs/FIGURE_CATALOG.md` | catalogue exhaustif des 238 figures SVG |
| `illustrated_report_estimates.csv` | 50 résumés β des cinq comparaisons interannuelles |
| `professor_canonical_comparisons.csv` | résumés β des huit comparaisons canoniques H0A–H5 |
| `all_elections_partition_integrity.csv` | statut des 292 partitions |
| `validation_checks.csv` | preuve des 60 contrôles |

Le dictionnaire de colonnes est dans `docs/OUTPUT_SCHEMA.md`.

## 7. Niveaux de confiance

| Niveau | État | Usage |
|---|---|---|
| panel, balance, identifiants | validé | reproduction du suivi fixe |
| 270 partitions matérialisées | validé comptablement | entrée des modèles déclarés |
| 22 RXC refusées | source incompatible avec la tolérance | ne pas ajuster sans décision méthodologique |
| NLS diagnostiqué `pass` | 1986/2022 ciblés | description écologique avec réserves |
| PyEI `20/20/1` | calibration, même à n=3 000 | pipeline, mémoire, inspection seulement |
| PyEI de production | absent | aucune conclusion substantielle MCMC |

Trois avertissements sont donc attendus : diagnostics MCMC insuffisants,
couverture de production 2022 nulle et 22 marges RXC sources refusées.

## 8. Reprise et traçabilité

Un `run_key` dépend du stage, des paramètres et des SHA-256 des entrées. Chaque
tentative reçoit un `run_id` horodaté et un dossier immuable. Un succès identique
est repris sans écrasement. `run_registry_executed.csv` est le journal des
tentatives ; `run_registry.csv` ajoute les combinaisons planifiées.

La consolidation sélectionne le dernier succès par configuration. Les runs
échoués ne contaminent pas les estimations mais restent visibles dans le
registre de travail. Le ZIP conserve uniquement les runs requis par les tables
et l'index des traces.

## 9. Formalisme et code

`docs/METHODOLOGY_CODE_MAP.md` relie chaque équation aux fonctions et lignes de
code. Repères centraux :

- partitions brutes par scénario : `prepare_inputs.py:67` ;
- fermeture exacte : `prepare_inputs.py:183` ;
- extraction communale `b_1`/`b_2` : `run_2x2_batch.py:133` ;
- intersection King/KRT : `extract_latent_densities.py:91` ;
- plus grand palier graphique : `extract_latent_densities.py:216` ;
- NLS multi-départs : `nls.py:105` ;
- reprise : `run_registry.py:54-112` ;
- validations longitudinales : `validate_outputs.py:270`.

Les noms de fonctions sont les repères contractuels ; les numéros de ligne
facilitent la revue de cette version.

## 10. Reproduction

Préparer toutes les partitions, puis consolider :

```powershell
python -m code_longitudinal.prepare_all_partitions --sample-size 3000
python -m code_longitudinal.run_pipeline --stage consolidate
```

Relancer le pilote de calibration jusqu'au palier autorisé :

```powershell
python -m code_longitudinal.run_pilot_ladder --max-rung 3000
```

Lancer les tests sans cache local :

```powershell
python -m pytest tests -q -p no:cacheprovider
```

Les ajustements de production doivent utiliser explicitement `--production`
ou `--draws 1000 --tune 1000 --chains 4`, avec `target_accept=0.99`. Ils peuvent
nécessiter une machine plus grande et plusieurs heures par couple.

## 11. Intégrité et minimalisme

`PACKAGE_MANIFEST.csv` donne, pour chaque autre fichier du ZIP, chemin relatif,
taille et SHA-256. Le constructeur vérifie ces empreintes, toutes les traces
indexées, chaque membre du ZIP et l'absence de caches. Un fichier `.sha256`
placé à côté du ZIP vérifie l'archive entière.

Sont volontairement exclus : données brutes inchangées, `.cache`,
`.pytest_cache`, `__pycache__`, bytecode, dossiers temporaires, PNG dupliquant
les SVG, runs échoués ou supersédés et copie redondante du paquet professeur.

## 12. Limites scientifiques

1. Le panel rétrospectif est défini dans l'univers 2022 : il représente un
   suivi de survivants communaux, pas l'univers historique de chaque date.
2. Les absences ne sont ni imputées ni remplacées.
3. Les relations écologiques ne sont pas des comportements individuels
   observés ; l'erreur écologique reste possible.
4. Les densités de calibration illustrent le pipeline, pas une postérieure de
   production validée.
5. La série complète 1962–2022 n'est pas encore estimée en production.
6. Les 22 RXC refusées exigent une décision explicite sur les données sources ;
   augmenter silencieusement la tolérance violerait le protocole livré.
