# Résultats longitudinaux prioritaires — note pour le professeur

## Résumé

Les quatre hypothèses principales H0A, H1, H2 et H4 ont été estimées pour les législatives de 1962, 1986 et 2022 avec le modèle KRT bêta-binomial sur un sous-panel tiré fixe de 500 communes. Après exclusion des lignes sans marges exploitables, les effectifs analytiques sont de 500 communes en 1962, 494 en 1986 et 500 en 2022. Les runs utilisent quatre chaînes, au moins 1 000 itérations de réglage et 1 000 tirages conservés par chaîne, avec `target_accept≥0,99`.

Le bilan final est **7/12 couples strictement validés**, plus **1 avec réserve mineure BFMI**. Les comparaisons H0A et H1 sont strictement validées aux trois dates; elles constituent les comparaisons canoniques recommandées. Les autres sorties sont conservées pour transparence mais les cas exploratoires ne doivent pas soutenir seuls une conclusion.

## Hypothèses testées

- **H0A** — abstention des ouvriers et employés comparée aux autres CSP, dénominateur inscrits.
- **H1** — vote à gauche des ouvriers et employés comparé aux autres CSP, dénominateur suffrages exprimés.
- **H2** — vote à gauche des ouvriers comparé aux autres CSP, dénominateur suffrages exprimés.
- **H4** — vote à droite des agriculteurs et indépendants comparé aux salariés, dénominateur suffrages exprimés.

## Diagnostics des meilleurs runs

| year | scenario_id | classification | draws | max_rhat | min_ess_bulk | min_ess_tail | divergences | min_bfmi |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1962 | H0A | validé | 1000 | 1.009 | 444.914 | 621.579 | 0.0 | 0.436 |
| 1986 | H0A | validé | 2000 | 1.006 | 1020.446 | 1976.388 | 0.0 | 0.592 |
| 2022 | H0A | validé | 1000 | 1.008 | 693.200 | 1068.579 | 0.0 | 0.605 |
| 1962 | H1 | validé | 2000 | 1.004 | 832.913 | 1410.329 | 0.0 | 0.310 |
| 1986 | H1 | validé | 1000 | 1.008 | 477.779 | 777.667 | 0.0 | 0.445 |
| 2022 | H1 | validé | 1000 | 1.008 | 487.782 | 767.295 | 0.0 | 0.491 |
| 1962 | H2 | avec réserve BFMI | 2000 | 1.005 | 620.535 | 947.217 | 0.0 | 0.265 |
| 1986 | H2 | validé | 2000 | 1.006 | 599.621 | 994.495 | 0.0 | 0.309 |
| 2022 | H2 | exploratoire | 1000 | 1.045 | 112.787 | 119.685 | 0.0 | 0.148 |
| 1962 | H4 | exploratoire | 1000 | 1.009 | 305.222 | 422.592 | 0.0 | 0.295 |
| 1986 | H4 | exploratoire | 1000 | 1.026 | 259.584 | 339.927 | 0.0 | 0.325 |
| 2022 | H4 | exploratoire | 1000 | 1.036 | 80.880 | 106.105 | 0.0 | 0.073 |

![Vue des diagnostics](../figures/priority_production/diagnostics_overview.png)

## Comparaisons canoniques entre périodes

Les années sont traitées comme trois coupes discrètes. Les points montrent les moyennes postérieures et les barres les intervalles crédibles à 95 %; aucune ligne ne suggère une trajectoire continue.

### H0A — abstention

![Comparaison canonique H0A](../figures/priority_production/canonical_H0A.png)

### H1 — vote à gauche

![Comparaison canonique H1](../figures/priority_production/canonical_H1.png)

## Densités jointes des deux β entre périodes

Ces figures reprennent le type de représentation historique du dossier. Chaque panneau montre la densité empirique jointe des **moyennes postérieures communales** de β₁ et β₂. Les axes et l’échelle de couleur sont identiques entre 1962, 1986 et 2022; les panneaux indiquent leurs effectifs analytiques respectifs (500, 494 et 500). La diagonale représente β₁=β₂; un nuage situé sous la diagonale correspond à β₁>β₂.

### H0A — comparaison validée aux trois périodes

La comparaison de forme et de position de la densité est autorisée aux trois dates, puisque les trois runs sont validés.

![Densité jointe H0A entre périodes](../figures/priority_production/joint_beta_H0A_periods.png)

### H1 — comparaison validée aux trois périodes

La comparaison de forme et de position de la densité est autorisée aux trois dates, puisque les trois runs sont validés.

![Densité jointe H1 entre périodes](../figures/priority_production/joint_beta_H1_periods.png)

### H2 — comparaison partiellement diagnostiquée

La figure est fournie pour transparence : 1986 est validé, 1962 porte une réserve BFMI et 2022 reste exploratoire. Elle ne doit donc pas soutenir seule une conclusion longitudinale.

![Densité jointe H2 entre périodes](../figures/priority_production/joint_beta_H2_periods.png)

### H4 — démonstration exploratoire

Les trois panneaux H4 sont exploratoires. Ils reproduisent le graphique demandé mais ne constituent pas une preuve comparative validée.

![Densité jointe H4 entre périodes](../figures/priority_production/joint_beta_H4_periods.png)

## Démonstration d’une distribution marginale communale

La figure suivante montre la distribution des moyennes postérieures communales. Elle décrit l’hétérogénéité entre communes et ne doit pas être lue comme une distribution d’individus observés.

![Densité communale H0A 2022](../figures/priority_production/density_demo_H0A_2022.png)

## Sorties produites

- `outputs/priority_best_runs.csv` : un meilleur run par hypothèse et période;
- `outputs/priority_best_estimates.csv` : estimations, intervalles, effectifs et statut;
- `outputs/priority_joint_beta_data.csv` : couples communaux (β₁, β₂) utilisés par les densités jointes;
- `outputs/priority_production_diagnostics.csv` : audit complet de tous les essais;
- `outputs/runs/<run_id>/trace.nc` : traces complètes conservées localement;
- `figures/priority_production/` : figures PNG et SVG;
- `docs/PRIORITY_CHART_MAP.md` : source et question de chaque figure.

## Limites

- Il s’agit d’inférence écologique : les comportements individuels ne sont pas observés directement.
- Le sous-panel tiré de 500 communes réduit le temps de calcul et reste identique entre dates; six communes sont sans marges analytiques exploitables en 1986, d’où `n=494` pour cette période. Il ne s’agit pas de l’univers communal complet.
- Les runs classés « exploratoire » sont fournis pour audit, pas pour une conclusion isolée.
- King est conservé comme calibration historique, mais n’a pas été relancé en production car son coût aurait été disproportionné par rapport au gain attendu.
