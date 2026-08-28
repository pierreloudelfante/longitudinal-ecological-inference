# Premiers résultats - modèles KRT et NLS

Les résultats portent sur un panel commun de **3 000 communes** observées en 1962, 1986 et 2022. Six modèles KRT sont présentés pour H0A et H1. Douze estimations NLS complètent l'analyse pour H0A, H1, H2 et H4.

## Hypothèses étudiées

| Hypothèse | Événement étudié | Groupe 1 | Groupe 2 | Modèles présentés |
| --- | --- | --- | --- | --- |
| H0A | abstention parmi les inscrits | ouvriers + employés | autres CSP | KRT et NLS |
| H1 | vote à gauche (`voteG + voteCG`) parmi les exprimés | ouvriers + employés | autres CSP | KRT et NLS |
| H2 | vote à gauche parmi les exprimés | ouvriers | autres CSP | NLS |
| H4 | vote à droite (`voteCD + voteD`) parmi les exprimés | agriculteurs + indépendants | salariés | NLS |

Contraste présenté : `groupe 1 - groupe 2`. Pour H4, le groupe des salariés réunit les cadres, professions intermédiaires, employés et ouvriers.

## Échantillon

| Élément | Valeur |
| --- | ---: |
| panel commun | 3 000 communes |
| univers admissible initial | 33 922 communes |
| graine | `20260802` |
| maximum `|SMD|` | 0,01939 |
| écart catégoriel maximal | 0,01032 |
| seuils retenus | 0,10 et 0,02 |

Il ne s'agit pas d'un problème d'équilibre du panel, mais d'une incohérence ponctuelle dans la donnée électorale de la commune `02643` en 1986 : 392 suffrages exprimés pour 383 inscrits. Pour ces premiers résultats, la commune est conservée, car son retrait descriptif modifie les contrastes de moins de 0,001 point et ne change pas leur interprétation. Cette petite anomalie a donc une incidence négligeable ici. Elle sera corrigée pour les prochains panels, avec un contrôle automatique imposant `0 ≤ exprimés ≤ votants ≤ inscrits` avant toute estimation.

## Premiers résultats KRT

![Contrastes KRT](../figures/v2/priority_3000_final/within_period_contrasts_3000_v1.png)

Le contraste correspond à `β1-β2`, avec `β1` pour les ouvriers et employés et `β2` pour les autres catégories socioprofessionnelles.

| Hypothèse | Année | β1 | β2 | β1-β2 [ICr 95 %] |
| --- | --- | --- | --- | --- |
| H0A | 1962 | 0,260 | 0,370 | -0,110 [-0,136 ; -0,085] |
| H0A | 1986 | 0,222 | 0,184 | +0,039 [+0,020 ; +0,057] |
| H0A | 2022 | 0,550 | 0,461 | +0,088 [+0,071 ; +0,106] |
| H1 | 1962 | 0,467 | 0,366 | +0,101 [+0,040 ; +0,159] |
| H1 | 1986 | 0,518 | 0,363 | +0,156 [+0,113 ; +0,199] |
| H1 | 2022 | 0,305 | 0,339 | -0,034 [-0,060 ; -0,008] |

- H0A passe de **-11,0 points** en 1962 à **+3,9 points** en 1986 puis **+8,8 points** en 2022.
- H1 passe de **+10,1 points** en 1962 à **+15,6 points** en 1986 puis **-3,4 points** en 2022.
- Les six intervalles crédibles ne recouvrent pas zéro sous le modèle estimé.

## Premiers résultats NLS

![Contrastes NLS](../figures/v2/priority_3000_final/nls_contrasts_3000_v1.png)

| Hyp. | Année | Événement | Groupe 1 | Groupe 2 | Contraste |
| --- | --- | --- | --- | --- | --- |
| H0A | 1962 | abstention parmi les inscrits | 0,255 | 0,353 | -0,098 |
| H0A | 1986 | abstention parmi les inscrits | 0,193 | 0,166 | +0,027 |
| H0A | 2022 | abstention parmi les inscrits | 0,487 | 0,430 | +0,057 |
| H1 | 1962 | vote à gauche parmi les exprimés | 0,394 | 0,383 | +0,011 |
| H1 | 1986 | vote à gauche parmi les exprimés | 0,481 | 0,383 | +0,099 |
| H1 | 2022 | vote à gauche parmi les exprimés | 0,268 | 0,311 | -0,044 |
| H2 | 1962 | vote à gauche parmi les exprimés | 0,403 | 0,379 | +0,024 |
| H2 | 1986 | vote à gauche parmi les exprimés | 0,471 | 0,414 | +0,057 |
| H2 | 2022 | vote à gauche parmi les exprimés | 0,241 | 0,305 | -0,063 |
| H4 | 1962 | vote à droite parmi les exprimés | 0,616 | 0,599 | +0,017 |
| H4 | 1986 | vote à droite parmi les exprimés | 0,630 | 0,540 | +0,091 |
| H4 | 2022 | vote à droite parmi les exprimés | 0,466 | 0,464 | +0,002 |

NLS : modèle `rosen_nls_2x2_unadjusted` sans covariable, solveur `scipy.optimize.least_squares` en méthode TRF, 20 points de départ, tolérance `1e-9` et maximum de 5 000 évaluations. Les douze ajustements ont un diagnostic numérique `pass` avec 20 départs réussis sur 20. Les contrastes sont présentés comme des estimations ponctuelles.

## Comparaison KRT et NLS

![Comparaison KRT et NLS](../figures/v2/priority_3000_final/nls_krt_comparison_3000_v1.png)

| Hyp. | Année | KRT [ICr 95 %] | NLS | NLS - KRT |
| --- | --- | --- | --- | --- |
| H0A | 1962 | -0,110 [-0,136 ; -0,085] | -0,098 | +0,012 |
| H0A | 1986 | +0,039 [+0,020 ; +0,057] | +0,027 | -0,011 |
| H0A | 2022 | +0,088 [+0,071 ; +0,106] | +0,057 | -0,031 |
| H1 | 1962 | +0,101 [+0,040 ; +0,159] | +0,011 | -0,090 |
| H1 | 1986 | +0,156 [+0,113 ; +0,199] | +0,099 | -0,057 |
| H1 | 2022 | -0,034 [-0,060 ; -0,008] | -0,044 | -0,010 |

Les six comparaisons H0A/H1 ont le même signe. Les niveaux sont proches pour H0A ; les contrastes NLS sont plus faibles pour H1, surtout en 1962 et 1986. Cette concordance de signe reste descriptive et les deux modèles ne sont pas interchangeables.

## Densités des paramètres β

Les densités jointes représentent les couples de moyennes postérieures communales `(β1, β2)`. Les axes et la bande passante sont communs aux trois années d'une même hypothèse. La diagonale correspond à `β1 = β2`.

### Communes équipondérées

![Densités jointes H0A - 1962, 1986 et 2022](../figures/v2/priority_3000_final/densities/joint_beta_H0A_common_bandwidth_equal_communes.png)

Pour H0A, la masse se situe principalement sous la diagonale en 1962, puis au-dessus en 1986 et 2022.

![Densités jointes H1 - 1962, 1986 et 2022](../figures/v2/priority_3000_final/densities/joint_beta_H1_common_bandwidth_equal_communes.png)

Pour H1, la distribution est plus dispersée en 1962. La position relative des groupes s'inverse en 2022.

### Pondération par la taille électorale

![Densités jointes H0A pondérées par le dénominateur communal](../figures/v2/priority_3000_final/densities/joint_beta_H0A_common_bandwidth_N_total_weighted.png)

La pondération de H0A conserve la position générale des distributions observée avec les communes équipondérées.

![Densités jointes H1 pondérées par le dénominateur communal](../figures/v2/priority_3000_final/densities/joint_beta_H1_common_bandwidth_N_total_weighted.png)

Pour H1, cette pondération confirme que les principales positions ne reposent pas uniquement sur les petites communes.

### Densités marginales

![Densités marginales H0A pondérées par les effectifs des groupes](../figures/v2/priority_3000_final/densities/marginal_beta_H0A_group_population_weighted.png)

Les marginales H0A isolent la distribution de chaque β et rendent plus directement visible leur déplacement entre les trois périodes.

![Densités marginales H1 pondérées par les effectifs des groupes](../figures/v2/priority_3000_final/densities/marginal_beta_H1_group_population_weighted.png)

Les marginales H1 complètent la densité jointe en montrant séparément la dispersion de chaque groupe.

## Diagnostics essentiels

| Hyp. | Année | Bilan MCMC | β | Divergences |
| --- | --- | --- | --- | --- |
| H0A | 1962 | satisfaisant avec réserve | pass | 0 |
| H0A | 1986 | satisfaisant avec réserve | pass | 0 |
| H0A | 2022 | satisfaisant | pass | 0 |
| H1 | 1962 | satisfaisant avec réserve | caveat | 0 |
| H1 | 1986 | satisfaisant | pass | 0 |
| H1 | 2022 | satisfaisant avec réserve | pass | 0 |

Deux ajustements KRT sont satisfaisants et quatre satisfaisants avec réserve. Les réserves concernent principalement des paramètres autres que les β ; H1-1962 conserve aussi une réserve sur les β. Aucune divergence n'est observée.

Réglages KRT : 4 chaînes, 1 000 itérations de chauffe et 1 000 tirages conservés par chaîne, `target_accept=0,99`, `max_treedepth=14`, `king_lambda=0,5`.

## À retenir

- Le panel commun de 3 000 communes respecte largement les critères d'équilibre.
- Les contrastes changent de signe entre certaines périodes, notamment H0A après 1962 et H1 en 2022.
- Les NLS confirment le signe des six résultats H0A/H1, avec des amplitudes parfois plus faibles.
- Les résultats décrivent des relations écologiques conditionnelles aux modèles ; ils ne mesurent pas directement des comportements individuels.
