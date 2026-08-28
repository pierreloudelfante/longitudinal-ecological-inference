# État exact de l’archive corrigée — 3 000 communes

Date de gel : 4 août 2026.

Cette archive corrige les deux ambiguïtés signalées :

- les résultats historiques corrigés reposent encore sur les 12 traces KRT à 500/494/500 communes ;
- la nouvelle production utilise un panel longitudinal commun de exactement 3 000 communes pour chaque hypothèse et chaque date.

## Production KRT à 3 000 communes

Paramètres fixes : 4 chaînes, 1 000 itérations de réglage, 1 000 tirages conservés par chaîne, `target_accept=0,99`, profondeur maximale 14.

État inclus dans l’archive :

| Hypothèse | Année | Communes | État du fit | Diagnostic MCMC officiel |
| --- | ---: | ---: | --- | --- |
| H0A | 1962 | 3 000 | terminé | réserve : ESS bulk minimal 376,75 |
| H0A | 1986 | 3 000 | terminé | réserve : R-hat maximal 1,0186 et ESS bulk minimal 362,08 |
| H0A | 2022 | 3 000 | en attente | non disponible |
| H1 | 1962, 1986, 2022 | 3 000 | en attente | non disponible |
| H2 | 1962, 1986, 2022 | 3 000 | en attente | non disponible |
| H4 | 1962, 1986, 2022 | 3 000 | en attente | non disponible |

Deux estimations sur douze sont donc terminées. Dix restent à exécuter. D’après les deux durées observées, le temps résiduel est d’environ 3,3 heures si la production reprend dans les mêmes conditions.

## Un seul diagnostic par estimation

Le fichier canonique est `mcmc_diagnostics_v2.json`. Il couvre dans un verdict unique les R-hat, ESS bulk/tail, divergences, BFMI et profondeurs d’arbre de toutes les variables postérieures.

Les fichiers `mcmc_variable_metrics_v2.csv` et `mcmc_block_metrics_v2.csv` détaillent ce même diagnostic pour trouver la variable responsable ; ils ne produisent pas un second verdict.

`b_1` et `b_2` sont les probabilités latentes communales. `c_1`, `c_2`, `d_1` et `d_2` sont des hyperparamètres internes de la même estimation KRT. Ils ne désignent pas une autre estimation.

## Densités jointes des deux β

Les graphiques demandés sont présents dans `figures/v2/densities/` pour H0A, H1, H2 et H4, avec :

- une version où chaque commune a le même poids ;
- une version pondérée par la population communale ;
- les mêmes bandes passantes et les mêmes axes pour 1962, 1986 et 2022 ;
- des contours HDR à 50 %, 80 % et 95 %.

Ces comparaisons entre trois périodes utilisent encore les traces historiques 500/494/500. Il serait trompeur de les appeler « densités à 3 000 communes » tant que les dix estimations restantes ne sont pas terminées.

## Contenu des résultats à 3 000 déjà terminés

Pour chacun des deux runs terminés, l’archive inclut le manifeste, les estimations agrégées corrigées, le diagnostic officiel, les métriques détaillées et les résumés latents communaux. Les traces NetCDF, beaucoup plus lourdes, restent dans le dossier de travail local et ne sont pas dupliquées dans cette archive de livraison.
