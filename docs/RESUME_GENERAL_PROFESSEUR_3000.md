# Rapport général — estimations écologiques sur 3 000 communes

## Résumé

Ce document présente la production intermédiaire consolidée `H0A/H1 × 1962/1986/2022`. Les six ajustements KRT utilisent le même panel de 3 000 communes. Chaque ajustement comprend 4 chaînes, 1 000 itérations de chauffe et 1 000 tirages conservés par chaîne, avec `target_accept=0,99` et `max_treedepth=14`.

Dans le panel retenu, le contraste écologique d’abstention `β₁−β₂` est négatif en 1962, puis positif en 1986 et 2022. Le contraste de vote à gauche est positif en 1962 et 1986, puis négatif en 2022. Les six intervalles intra-période excluent zéro.

Le bilan MCMC conservateur classe **2 ajustements satisfaisants**, **4 satisfaisants avec réserve** et aucun insuffisant. Les métriques principales restent calculées sur les β communaux. Une réserve est toutefois appliquée lorsqu’un hyperparamètre présente un R-hat ou un ESS moins favorable. Les diagnostics des contrastes agrégés comptent 5 `pass` et 1 `caveat`. L’identification écologique reste limitée pour cinq ajustements sur six.

## Échantillonnage

Le panel est tiré sans remise dans l’intersection des communes admissibles en 1962, 1986 et 2022. L’univers commun comprend 33 922 communes raccordées à la géographie 2022 et disposant des variables nécessaires aux trois dates.

La graine `20260802` fournit un panel de 3 000 communes accepté à la première tentative. La porte d’équilibre porte sur la taille électorale, plusieurs parts sociales, la région et la catégorie VBBM. Le même panel, dans le même ordre, est utilisé pour les six ajustements.

| Élément | Valeur |
| --- | ---: |
| univers commun admissible | 33 922 communes |
| panel | 3 000 communes |
| fraction de sondage communale | 8,844 % |
| part des inscrits 2022 de l’univers commun | 7,981 % |
| graine | `20260802` |
| maximum `|SMD|` | 0,01939 |
| maximum d’écart catégoriel | 0,01032 |
| SHA-256 du panel | `d70810a1…e8cd3f` |

Les seuils sont 0,10 pour les SMD et 0,02 pour les écarts catégoriels. Le panel satisfait ces seuils. Il ne s’agit pas d’un échantillon d’électeurs. L’intersection temporelle peut favoriser les communes géographiquement stables, et les contrôles d’équilibre reposent principalement sur des variables de 2022.

## Hypothèses et méthode

| Hypothèse | Événement | β₁ | β₂ | Dénominateur |
| --- | --- | --- | --- | --- |
| H0A | abstention | ouvriers + employés | autres CSP | inscrits |
| H1 | vote à gauche (`voteG + voteCG`) | ouvriers + employés | autres CSP | suffrages exprimés |

Le modèle KRT est un modèle écologique bayésien bêta-binomial. Pour chaque commune, il estime deux probabilités latentes, `β₁` et `β₂`, à partir des marges sociales et électorales. Les paramètres communaux suivent des distributions Beta hiérarchiques. Le réglage retenu est `king_lambda=0,5`.

Les effectifs sociaux sont recalibrés au dénominateur de chaque hypothèse puis fermés par la méthode du plus fort reste. Les agrégats sont calculés à chaque tirage avec les poids propres aux groupes : `N1` pour `β₁` et `N2` pour `β₂`. Le contraste publié est calculé tirage par tirage.

Les trois dates sont ajustées séparément. Les comparaisons temporelles utilisent 50 000 paires indépendantes de tirages provenant des ajustements concernés. Elles ne correspondent ni à un modèle temporel joint, ni au suivi des mêmes électeurs.

## Résultats intra-période

![Agrégats de β₁ et β₂](../figures/v2/priority_3000_final/aggregate_drawwise_corrected_3000_v1.png)

H0A atteint son niveau le plus faible en 1986 et le plus élevé en 2022. Pour H1, `β₁` est le plus élevé en 1986 et diminue en 2022. Les niveaux de H0A et H1 ne sont pas directement comparables car leurs événements et leurs dénominateurs diffèrent.

![Contrastes intra-période](../figures/v2/priority_3000_final/within_period_contrasts_3000_v1.png)

| Hypothèse | Année | β₁ | β₂ | β₁−β₂ [ICr 95 %] | tirages où β₁−β₂>0 |
| --- | ---: | ---: | ---: | ---: | ---: |
| H0A | 1962 | 0,260 | 0,370 | −0,110 [−0,136 ; −0,085] | 0 / 4 000 |
| H0A | 1986 | 0,222 | 0,184 | +0,039 [+0,020 ; +0,057] | 4 000 / 4 000 |
| H0A | 2022 | 0,550 | 0,461 | +0,088 [+0,071 ; +0,106] | 4 000 / 4 000 |
| H1 | 1962 | 0,467 | 0,366 | +0,101 [+0,040 ; +0,159] | 3 999 / 4 000 |
| H1 | 1986 | 0,518 | 0,363 | +0,156 [+0,113 ; +0,199] | 4 000 / 4 000 |
| H1 | 2022 | 0,305 | 0,339 | −0,034 [−0,060 ; −0,008] | 27 / 4 000 |

Pour H0A, le signe du contraste s’inverse entre 1962 et 1986. Pour H1, il s’inverse entre 1986 et 2022.

## Comparaisons entre périodes

Les valeurs ci-dessous sont accompagnées d’un intervalle postérieur de comparaison sous indépendance des ajustements.

| Hypothèse | Comparaison | Changement [intervalle 95 %] | Lecture |
| --- | --- | ---: | --- |
| H0A | 1962 → 1986 | +0,149 [+0,117 ; +0,181] | inversion du signe |
| H0A | 1962 → 2022 | +0,198 [+0,167 ; +0,230] | hausse du contraste |
| H0A | 1986 → 2022 | +0,049 [+0,025 ; +0,075] | hausse du contraste |
| H1 | 1962 → 1986 | +0,055 [−0,018 ; +0,130] | intervalle contenant zéro |
| H1 | 1962 → 2022 | −0,135 [−0,199 ; −0,069] | baisse du contraste |
| H1 | 1986 → 2022 | −0,189 [−0,241 ; −0,139] | inversion du signe |

La comparaison H1 entre 1962 et 1986 est la seule dont l’intervalle à 95 % contient zéro.

## Densités communales

Les densités jointes représentent les couples de moyennes postérieures communales `(b1_mean, b2_mean)`. Elles illustrent l’hétérogénéité entre communes ; elles ne représentent pas l’incertitude d’une moyenne nationale. Les axes et le bandwidth sont communs aux trois dates dans chaque hypothèse. La diagonale correspond à `β₁=β₂`.

### H0A

![H0A — communes équipondérées](../figures/v2/priority_3000_final/densities/joint_beta_H0A_common_bandwidth_equal_communes.png)

En 1962, la masse se situe principalement au-dessus de la diagonale, soit `β₁<β₂`. En 1986 et 2022, elle se situe principalement en dessous. La distribution de 2022 est déplacée vers des valeurs plus élevées pour les deux groupes.

![H0A — pondération par la taille communale](../figures/v2/priority_3000_final/densities/joint_beta_H0A_common_bandwidth_N_total_weighted.png)

La pondération par le dénominateur communal conserve la même structure générale. L’inversion ne repose donc pas uniquement sur les petites communes du panel.

### H1

![H1 — communes équipondérées](../figures/v2/priority_3000_final/densities/joint_beta_H1_common_bandwidth_equal_communes.png)

La distribution de H1–1962 est large, multimodale et proche des bornes 0 et 1. En 1986, la masse est principalement sous la diagonale. En 2022, elle est principalement au-dessus.

![H1 — pondération par la taille communale](../figures/v2/priority_3000_final/densities/joint_beta_H1_common_bandwidth_N_total_weighted.png)

La pondération par taille conserve ces positions relatives. Pour H1–1962, la forme observée est présente dans les moyennes postérieures communales et ne vient pas seulement de l’affichage. Elle reste sensible aux bornes écologiques, aux priors, à la structure hiérarchique et au lissage KDE près de 0 et 1.

### Densités marginales

![Densités marginales H0A](../figures/v2/priority_3000_final/densities/marginal_beta_H0A_group_population_weighted.png)

Pour H0A, `β₁` est inférieur à `β₂` en 1962, puis supérieur en 1986 et 2022. Les niveaux des deux groupes sont les plus élevés en 2022.

![Densités marginales H1](../figures/v2/priority_3000_final/densities/marginal_beta_H1_group_population_weighted.png)

Pour H1, `β₁` est le plus élevé en 1986 et le plus faible en 2022. Les distributions de 1962 sont plus dispersées que celles de 1986 et 2022.

## Diagnostics MCMC centrés sur les β

![Diagnostic MCMC centré sur les β avec réserves](../figures/v2/priority_3000_final/canonical_diagnostics_3000_v1.png)

Le graphique place chaque estimation selon le R-hat le plus élevé et l’ESS bulk le plus faible parmi les 6 000 β communaux. La couleur correspond au bilan conservateur : une estimation est affichée avec réserve si les β ou les quatre hyperparamètres présentent un `caveat`. Les six ajustements ont zéro divergence, zéro saturation de profondeur d’arbre et un BFMI supérieur à 0,30.

| Hypothèse | Année | Bilan | β | Hors β | R-hat max β | ESS bulk min β | ESS tail min β | Origine de la réserve |
| --- | ---: | --- | --- | --- | ---: | ---: | ---: | --- |
| H0A | 1962 | satisfaisant avec réserve | pass | caveat | 1,0072 | 2 819,0 | 2 080,2 | ESS bulk hors β |
| H0A | 1986 | satisfaisant avec réserve | pass | caveat | 1,0069 | 4 206,4 | 2 008,1 | R-hat et ESS bulk hors β |
| H0A | 2022 | satisfaisant | pass | pass | 1,0085 | 5 092,1 | 2 035,7 | — |
| H1 | 1962 | satisfaisant avec réserve | caveat | caveat | 1,0102 | 581,0 | 358,0 | β : R-hat et ESS tail ; hors β : R-hat et ESS bulk |
| H1 | 1986 | satisfaisant | pass | pass | 1,0074 | 4 215,8 | 1 989,9 | — |
| H1 | 2022 | satisfaisant avec réserve | pass | caveat | 1,0077 | 2 327,2 | 1 707,2 | ESS bulk hors β |

### Diagnostics des contrastes publiés

![Diagnostics des contrastes agrégés](../figures/v2/priority_3000_final/estimand_diagnostics_3000_v1.png)

| Hypothèse | Année | Statut du contraste | R-hat | ESS bulk | ESS tail | MCSE moyenne |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| H0A | 1962 | pass | 1,0080 | 936,9 | 1 553,3 | 0,00044 |
| H0A | 1986 | caveat | 1,0118 | 519,3 | 1 212,8 | 0,00041 |
| H0A | 2022 | pass | 1,0036 | 930,7 | 1 697,4 | 0,00029 |
| H1 | 1962 | pass | 1,0035 | 1 139,7 | 2 135,2 | 0,00092 |
| H1 | 1986 | pass | 1,0076 | 595,1 | 1 019,4 | 0,00089 |
| H1 | 2022 | pass | 1,0077 | 847,9 | 1 456,1 | 0,00047 |

H1–1962 est le seul cas où les β eux-mêmes justifient une réserve : R-hat maximal à 1,0102 et ESS tail minimal à 358,0. Les réserves de H0A–1962, H0A–1986 et H1–2022 proviennent uniquement des hyperparamètres. Le contraste agrégé de H1–1962 est correctement échantillonné. H0A–1986 reste légèrement au-dessus du seuil R-hat de 1,01 pour le contraste.

Le fichier public `canonical_mcmc_diagnostics_3000_v1.csv` distingue `beta_diagnostic_status`, `non_beta_parameter_status` et le bilan unique `mcmc_assessment_label`. Les JSON bruts conservent le détail de toutes les variables pour la traçabilité.

## Identification écologique

L’identification est distincte de la convergence MCMC. Elle mesure dans quelle mesure les marges communales contraignent les probabilités latentes.

H0A–1986 est `pass`. Les cinq autres ajustements sont `caveat`, principalement parce que les bornes de tomographie sont larges. Le modèle hiérarchique et les priors contribuent donc à la précision des distributions postérieures. Les résultats ne doivent pas être interprétés comme des comportements individuels directement observés.

## Outputs utilisés

| Fichier | Lignes | Contenu |
| --- | ---: | --- |
| `aggregate_drawwise_corrected_3000_v1.csv` | 12 | agrégats de β₁ et β₂ |
| `within_period_contrasts_3000_v1.csv` | 6 | contrastes intra-période |
| `between_period_contrast_changes_3000_v1.csv` | 6 | comparaisons entre dates |
| `canonical_mcmc_diagnostics_3000_v1.csv` | 6 | métriques β, réserve hors β et bilan conservateur |
| `estimand_mcmc_diagnostics_3000_v1.csv` | 18 | diagnostics de β₁, β₂ et du contraste |
| `identification_separate_3000_v1.csv` | 6 | identification écologique |
| `joint_latent_3000_v1.csv` | 18 000 | moyennes postérieures communales |
| `density_bandwidths_3000_v1.csv` | 8 | paramètres de lissage |
| `release_manifest_3000_v1.json` | 1 | runs, paramètres et empreintes |

Le dossier `figures/v2/priority_3000_final/` contient dix figures, chacune en PNG et SVG.

Dans l’archive complète, chaque run conserve sa trace NetCDF, ses latents communaux, son manifeste et ses diagnostics. La version compacte conserve tous les résultats consolidés et deux traces représentatives afin de rester sous 500 Mo.

## Limites

Les résultats dépendent du panel commun, de la reconstruction des marges sociales, des priors et de `king_lambda`. L’incertitude liée au choix du panel n’est pas propagée. Les posterior predictive checks complets et la sensibilité aux priors restent à produire. Les comparaisons entre dates ne sont ni causales, ni individuelles.

## Documents associés

- [`METHODE_ECHANTILLONNAGE_PANEL_3000.md`](METHODE_ECHANTILLONNAGE_PANEL_3000.md) : construction du panel ;
- [`METHODOLOGIE_ET_CHOIX_SENSIBLES_3000.md`](METHODOLOGIE_ET_CHOIX_SENSIBLES_3000.md) : modèle et choix méthodologiques ;
- [`COMPARAISON_DENSITES_JOINTES_3_PERIODES.md`](COMPARAISON_DENSITES_JOINTES_3_PERIODES.md) : lecture détaillée des densités ;
- [`PRIORITY_RESULTS_3000_FINAL.md`](PRIORITY_RESULTS_3000_FINAL.md) : tables techniques ;
- [`README_PRODUCTION_3000_H0A_H1.md`](README_PRODUCTION_3000_H0A_H1.md) : guide de production.
