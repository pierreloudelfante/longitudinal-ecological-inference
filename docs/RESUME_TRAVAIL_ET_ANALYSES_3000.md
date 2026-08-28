# Résumé du travail et des analyses consolidées — panel commun de 3 000 communes

## Synthèse technique

La production intermédiaire consolidée porte sur **six ajustements KRT** : deux hypothèses (`H0A` et `H1`) en 1962, 1986 et 2022, sur le même panel de 3 000 communes. Chaque ajustement utilise 4 chaînes, 1 000 itérations de chauffe et 1 000 tirages conservés par chaîne, avec `target_accept=0,99` et `max_treedepth=14`.

Les résultats mettent en évidence deux évolutions descriptives nettes :

- pour **H0A (abstention)**, le contraste ouvriers-employés moins autres CSP passe de −0,110 en 1962 à +0,039 en 1986 puis +0,088 en 2022 ;
- pour **H1 (vote à gauche)**, le contraste est positif en 1962 (+0,101) et 1986 (+0,156), puis négatif en 2022 (−0,034).

Ces contrastes sont des inférences écologiques conditionnelles au panel et au modèle. Ils ne décrivent pas des trajectoires individuelles et ne démontrent pas une relation causale.

L’évaluation est **partageable avec réserves** : les six fits sont terminés, sans divergence ni saturation de profondeur d’arbre. Le bilan MCMC classe H0A–2022 et H1–1986 `satisfaisant`. Les quatre autres sont `satisfaisant avec réserve`, soit à cause des β, soit à cause des hyperparamètres. L’identification écologique est une évaluation distincte : un fit est `pass` et cinq sont `caveat` sur ce plan.

## Ce qui a effectivement été estimé

| Hypothèse | Événement modélisé | Groupe 1 — β₁ | Groupe 2 — β₂ | Dénominateur |
| --- | --- | --- | --- | --- |
| H0A | abstention | ouvriers + employés | autres CSP | inscrits |
| H1 | vote à gauche | ouvriers + employés | autres CSP | suffrages exprimés |

Les six ajustements finaux sont :

| Hypothèse | Année | Run final | Communes | Temps d’estimation | Pic mémoire |
| --- | ---: | --- | ---: | ---: | ---: |
| H0A | 1962 | `20260804T135238Z__a1d85f03a9f8` | 3 000 | 13,4 min | 832,0 Mo |
| H0A | 1986 | `20260804T140822Z__cc8c7aa063b5` | 3 000 | 20,8 min | 502,2 Mo |
| H0A | 2022 | `20260804T144933Z__4830d0298ccd` | 3 000 | 11,3 min | 358,1 Mo |
| H1 | 1962 | `20260804T150252Z__2df1cacde040` | 3 000 | 65,2 min | 370,8 Mo |
| H1 | 1986 | `20260804T161211Z__6719825c1e9a` | 3 000 | 23,6 min | 591,8 Mo |
| H1 | 2022 | `20260804T163742Z__1cc94b3f41d5` | 3 000 | 12,9 min | 383,8 Mo |

Le temps MCMC cumulé enregistré est d’environ **147 minutes**. Les exécutions ont été séquentielles (`cores=1`) afin de contenir l’usage mémoire ; cela ne réduit ni le nombre de chaînes ni le nombre de tirages sauvegardés.

Le plan de production plus large comportait aussi H2 et H4. Ces scénarios ne font pas partie de la livraison finale décrite ici : les résultats canoniques sont exclusivement `H0A/H1 × 1962/1986/2022`.

## Résultats principaux

Les moyennes de β₁ et β₂ sont calculées à chaque tirage postérieur avec les effectifs propres à chaque groupe. L’intervalle présenté est l’intervalle crédible à 95 % du contraste `β₁−β₂`.

| Hypothèse | Année | β₁ | β₂ | β₁−β₂ [ICr 95 %] | P(β₁−β₂>0) | MCMC | Identification |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| H0A | 1962 | 0,260 | 0,370 | −0,110 [−0,136 ; −0,085] | 0,000 | caveat | caveat |
| H0A | 1986 | 0,222 | 0,184 | +0,039 [+0,020 ; +0,057] | 1,000 | caveat | pass |
| H0A | 2022 | 0,550 | 0,461 | +0,088 [+0,071 ; +0,106] | 1,000 | pass | caveat |
| H1 | 1962 | 0,467 | 0,366 | +0,101 [+0,040 ; +0,159] | 0,9998 | caveat | caveat |
| H1 | 1986 | 0,518 | 0,363 | +0,156 [+0,113 ; +0,199] | 1,000 | pass | caveat |
| H1 | 2022 | 0,305 | 0,339 | −0,034 [−0,060 ; −0,008] | 0,0068 | caveat | caveat |

![Agrégats corrigés de β₁ et β₂](../figures/v2/priority_3000_final/aggregate_drawwise_corrected_3000_v1.png)

**Lecture.** H0A montre un déplacement commun des niveaux d’abstention vers le haut en 2022, accompagné d’une inversion du contraste par rapport à 1962. H1 montre un niveau de β₁ élevé en 1986 puis nettement plus faible en 2022. Les niveaux de H0A et H1 ne doivent pas être comparés directement : leurs événements et leurs dénominateurs sont différents.

![Contrastes intra-période](../figures/v2/priority_3000_final/within_period_contrasts_3000_v1.png)

**Lecture.** Les six intervalles crédibles des contrastes intra-période excluent zéro. Cette séparation postérieure ne supprime cependant ni les réserves de convergence de quatre fits ni les limites d’identification écologique.

## Comparaisons entre périodes

Les changements sont obtenus à partir de 50 000 paires indépendantes de tirages provenant de fits distincts, avec la graine `20260804`.

| Hypothèse | Périodes comparées | Changement du contraste [ICr 95 %] | Lecture |
| --- | --- | ---: | --- |
| H0A | 1962 → 1986 | +0,149 [+0,117 ; +0,181] | inversion nette du contraste |
| H0A | 1962 → 2022 | +0,198 [+0,167 ; +0,230] | hausse nette et durable |
| H0A | 1986 → 2022 | +0,049 [+0,025 ; +0,075] | hausse supplémentaire |
| H1 | 1962 → 1986 | +0,055 [−0,018 ; +0,130] | changement incertain à 95 % |
| H1 | 1962 → 2022 | −0,135 [−0,199 ; −0,069] | baisse nette |
| H1 | 1986 → 2022 | −0,189 [−0,241 ; −0,139] | inversion nette |

Le panel communal est commun, mais le modèle n’est pas longitudinal au niveau des paramètres : chaque élection est ajustée séparément. Ces changements comparent donc des distributions postérieures de périodes distinctes, sans modéliser une covariance temporelle entre les paramètres.

## Diagnostics centrés sur les β pour les six estimations

![Diagnostics MCMC des β communaux](../figures/v2/priority_3000_final/canonical_diagnostics_3000_v1.png)

| Hypothèse | Année | Bilan | Origine de la réserve | R-hat max β | ESS bulk min β | ESS tail min β | BFMI min |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: |
| H0A | 1962 | satisfaisant avec réserve | ESS bulk hors β | 1,0072 | 2 819,0 | 2 080,2 | 0,454 |
| H0A | 1986 | satisfaisant avec réserve | R-hat et ESS bulk hors β | 1,0069 | 4 206,4 | 2 008,1 | 0,551 |
| H0A | 2022 | satisfaisant | — | 1,0085 | 5 092,1 | 2 035,7 | 0,542 |
| H1 | 1962 | satisfaisant avec réserve | β : R-hat et ESS tail ; hors β : R-hat et ESS bulk | 1,0102 | 581,0 | 358,0 | 0,315 |
| H1 | 1986 | satisfaisant | — | 1,0074 | 4 215,8 | 1 989,9 | 0,491 |
| H1 | 2022 | satisfaisant avec réserve | ESS bulk hors β | 1,0077 | 2 327,2 | 1 707,2 | 0,574 |

Les six fits ont **0 divergence** et **0 atteinte de `max_treedepth`**. H1–1962 est le seul cas où la réserve concerne directement les β : R-hat maximal à 1,0102 et ESS tail minimal à 358,0. Les réserves de H0A–1962, H0A–1986 et H1–2022 viennent uniquement des paramètres hors β.

Il existe un seul bilan MCMC publié par estimation dans `canonical_mcmc_diagnostics_3000_v1.csv`. Les métriques principales portent sur les β ; les paramètres hors β peuvent seulement ajouter une réserve. Les JSON bruts conservent le détail de toutes les variables pour audit. Les diagnostics d’identification ne sont pas un second diagnostic de chaînes.

## Densités communales et contrôle visuel

Les densités jointes représentent les 3 000 couples de moyennes postérieures communales `(b1_mean, b2_mean)` pour chaque période. Elles montrent la forme et l’hétérogénéité entre communes ; elles ne représentent pas directement l’incertitude de l’agrégat national.

Le contrôle détaillé, les quatre planches jointes, les deux planches marginales et les statistiques descriptives sont dans [`COMPARAISON_DENSITES_JOINTES_3_PERIODES.md`](COMPARAISON_DENSITES_JOINTES_3_PERIODES.md).

## Échantillonnage et population cible

Le panel est un tirage sans remise de 3 000 communes dans 33 922 communes admissibles aux trois dates, conditionné par une porte d’équilibre mesurée sur des variables 2022. La graine `20260802` a été acceptée au premier essai.

- fraction de sondage communale : 8,844 % ;
- maximum `|SMD|` contre l’univers commun : 0,01939 ;
- maximum d’écart catégoriel : 0,01032 ;
- SHA-256 du panel : `d70810a1add048d4823274e182f3adf8735d6f881bd32564a550c78988e8cd3f`.

La méthode détaillée est dans [`METHODE_ECHANTILLONNAGE_PANEL_3000.md`](METHODE_ECHANTILLONNAGE_PANEL_3000.md). Les choix de modèle, de dénominateur, d’arrondi, d’agrégation et de diagnostic sont explicités dans [`METHODOLOGIE_ET_CHOIX_SENSIBLES_3000.md`](METHODOLOGIE_ET_CHOIX_SENSIBLES_3000.md).

## Limites qui doivent accompagner toute présentation

1. **Inférence écologique.** Les β sont des probabilités latentes de groupe compatibles avec des marges communales, pas des comportements individuels observés.
2. **Panel conditionnel.** Les intervalles ne propagent pas l’incertitude liée au choix d’un autre panel équilibré.
3. **Survivance géographique.** L’admissibilité aux trois dates exclut certaines communes disparues, fusionnées, non raccordées ou incomplètes.
4. **Équilibre mesuré en 2022.** L’équilibre historique sur les mêmes variables n’est pas démontré.
5. **Priors non testés ici.** Les résultats KRT sont conditionnels au choix `king_lambda=0,5` et aux hyperpriors correspondants.
6. **Diagnostics incomplets pour quatre fits.** `caveat` signifie utilisable avec réserve, pas convergence entièrement satisfaisante.
7. **Identification distincte.** Des bornes de tomographie larges limitent l’interprétation individuelle, même lorsque le sampler passe ses diagnostics.
8. **Comparaisons temporelles non causales.** Les différences entre années peuvent refléter les contextes électoraux, les données, les dénominateurs ou le modèle ; elles ne démontrent pas un mécanisme causal.

## Suites recommandées

1. réaliser des posterior predictive checks pour les six fits finaux ;
2. tester la sensibilité à `king_lambda` et à des priors alternatifs ;
3. répéter l’analyse sur plusieurs panels équilibrés ;
4. examiner spécifiquement H1–1962 avec davantage de tirages ou une paramétrisation alternative ;
5. documenter la stabilité aux choix de blocs politiques et à la reconstruction des marges sociales ;
6. conserver les conclusions au niveau écologique, avec une formulation non causale.

## Sources canoniques

- résultats agrégés : `outputs/v2/priority_3000_final/aggregate_drawwise_corrected_3000_v1.csv` ;
- contrastes intra-période : `outputs/v2/priority_3000_final/within_period_contrasts_3000_v1.csv` ;
- changements inter-périodes : `outputs/v2/priority_3000_final/between_period_contrast_changes_3000_v1.csv` ;
- diagnostics : `outputs/v2/priority_3000_final/canonical_mcmc_diagnostics_3000_v1.csv` ;
- diagnostics des estimands : `outputs/v2/priority_3000_final/estimand_mcmc_diagnostics_3000_v1.csv` ;
- identification : `outputs/v2/priority_3000_final/identification_separate_3000_v1.csv` ;
- latents communaux : `outputs/v2/priority_3000_final/joint_latent_3000_v1.csv` ;
- lissages : `outputs/v2/priority_3000_final/density_bandwidths_3000_v1.csv` ;
- manifeste : `outputs/v2/priority_3000_final/release_manifest_3000_v1.json`.
