# Résultats illustrés — législatives 1962, 1986 et 2022

## Synthèse technique

Ce rapport rassemble **18 figures directement visibles dans le Markdown** : cinq comparaisons interannuelles et treize densités King/KRT, réparties entre les législatives de 1962, 1986 et 2022 (premier tour). H0A, H1 et H5 sont comparées aux trois dates ; H6 et H7 seulement en 1986 et 2022, car FN/RN n’est pas défini en 1962 dans le registre.

Le résultat le plus important est une limite : **tous les ajustements PyEI présentés ici sont des calibrations 20 draws / 20 tune / 1 chaîne avec diagnostic `fail`**. Les graphiques vérifient la chaîne données → traces → β communaux → densités → comparaison annuelle, mais ne constituent pas des estimations substantielles des comportements individuels. Les constats ci-dessous sont descriptifs et ne sont ni causaux ni validés pour publication.

La comparaison est la plus proche du plan pour H0A et H1, qui atteignent le palier demandé de 3 000 aux trois dates avec des intersections King/KRT de 2 813 à 2 963 communes. H5 et H7 restent les points faibles : H5-2022 ne compare que 15 communes et H7-1986 seulement 21.

## Ce que montrent les comparaisons entre années

Les années sont traitées comme des coupes discrètes. Les figures utilisent des points, et non des lignes, afin de ne pas suggérer une trajectoire continue avec seulement deux ou trois dates. Le point est la moyenne non pondérée des moyennes postérieures communales ; la barre P25–P75 décrit l’hétérogénéité entre communes, **pas** l’incertitude postérieure.

### H0A — Abstention — ouvriers et employés vs autres CSP

Dans ces calibrations, les deux modèles placent la moyenne communale d’abstention plus haut en 2022 qu’en 1986 pour les deux groupes. Le niveau de 1962 et l’amplitude des écarts dépendent toutefois du modèle ; ce constat reste descriptif.

![Comparaison interannuelle — H0A](../figures/illustrated_report/comparison_interannuelle__H0A.svg)

| Année | Modèle | Communes | β₁ ouvriers + employés | β₂ agriculteurs + indépendants + cadres + professions intermédiaires | Diagnostic |
| --- | --- | --- | --- | --- | --- |
| 1962 | King — normale tronquée | 2 963 | 0.347 | 0.331 | fail |
| 1962 | KRT — King99 bêta-binomial | 2 963 | 0.235 | 0.376 | fail |
| 1986 | King — normale tronquée | 2 928 | 0.195 | 0.206 | fail |
| 1986 | KRT — King99 bêta-binomial | 2 928 | 0.159 | 0.208 | fail |
| 2022 | King — normale tronquée | 2 820 | 0.488 | 0.448 | fail |
| 2022 | KRT — King99 bêta-binomial | 2 820 | 0.470 | 0.469 | fail |

### H1 — Vote à gauche — ouvriers et employés vs autres CSP

Pour β₁ (ouvriers + employés), les deux modèles donnent une moyenne plus faible en 2022 qu’en 1962. Pour β₂, King et KRT ne décrivent pas la même direction entre ces deux dates : aucune conclusion robuste ne peut être tirée.

![Comparaison interannuelle — H1](../figures/illustrated_report/comparison_interannuelle__H1.svg)

| Année | Modèle | Communes | β₁ ouvriers + employés | β₂ agriculteurs + indépendants + cadres + professions intermédiaires | Diagnostic |
| --- | --- | --- | --- | --- | --- |
| 1962 | King — normale tronquée | 2 925 | 0.558 | 0.257 | fail |
| 1962 | KRT — King99 bêta-binomial | 2 925 | 0.393 | 0.389 | fail |
| 1986 | King — normale tronquée | 2 935 | 0.414 | 0.456 | fail |
| 1986 | KRT — King99 bêta-binomial | 2 935 | 0.450 | 0.415 | fail |
| 2022 | King — normale tronquée | 2 813 | 0.326 | 0.317 | fail |
| 2022 | KRT — King99 bêta-binomial | 2 813 | 0.273 | 0.314 | fail |

### H5 — Vote au centre — cadres vs autres CSP

La comparaison temporelle n’est pas homogène : King est absent en 1962, l’intersection 1986 ne contient que 687 communes et celle de 2022 seulement 15. Cette figure sert principalement à rendre visible cette fragilité.

![Comparaison interannuelle — H5](../figures/illustrated_report/comparison_interannuelle__H5.svg)

| Année | Modèle | Communes | β₁ cadres | β₂ agriculteurs + indépendants + professions intermédiaires + employés + ouvriers | Diagnostic |
| --- | --- | --- | --- | --- | --- |
| 1962 | KRT — King99 bêta-binomial | 2 985 | 0.180 | 0.005 | fail |
| 1986 | King — normale tronquée | 687 | 0.055 | 0.003 | fail |
| 1986 | KRT — King99 bêta-binomial | 687 | 0.159 | 0.004 | fail |
| 2022 | King — normale tronquée | 15 | 0.607 | 0.135 | fail |
| 2022 | KRT — King99 bêta-binomial | 15 | 0.270 | 0.205 | fail |

### H6 — Vote FN/RN — ouvriers vs autres CSP

Les deux calibrations placent les moyennes β₁ et β₂ plus haut en 2022 qu’en 1986. Les effectifs comparés diffèrent (473 contre 2 485 communes) et les diagnostics échouent ; il ne s’agit donc pas encore d’une estimation validée de l’évolution du vote FN/RN.

![Comparaison interannuelle — H6](../figures/illustrated_report/comparison_interannuelle__H6.svg)

| Année | Modèle | Communes | β₁ ouvriers | β₂ agriculteurs + indépendants + cadres + professions intermédiaires + employés | Diagnostic |
| --- | --- | --- | --- | --- | --- |
| 1986 | King — normale tronquée | 473 | 0.145 | 0.065 | fail |
| 1986 | KRT — King99 bêta-binomial | 473 | 0.147 | 0.052 | fail |
| 2022 | King — normale tronquée | 2 485 | 0.418 | 0.199 | fail |
| 2022 | KRT — King99 bêta-binomial | 2 485 | 0.294 | 0.226 | fail |

### H7 — Vote FN/RN — employés vs autres CSP

Le point 1986 repose sur 21 communes et King/KRT y divergent fortement, surtout pour β₁. La comparaison 1986–2022 est trop instable pour être interprétée comme une évolution.

![Comparaison interannuelle — H7](../figures/illustrated_report/comparison_interannuelle__H7.svg)

| Année | Modèle | Communes | β₁ employés | β₂ agriculteurs + indépendants + cadres + professions intermédiaires + ouvriers | Diagnostic |
| --- | --- | --- | --- | --- | --- |
| 1986 | King — normale tronquée | 21 | 0.519 | 0.002 | fail |
| 1986 | KRT — King99 bêta-binomial | 21 | 0.118 | 0.076 | fail |
| 2022 | King — normale tronquée | 2 580 | 0.384 | 0.209 | fail |
| 2022 | KRT — King99 bêta-binomial | 2 580 | 0.271 | 0.231 | fail |

## Périmètre et définitions

| Hypothèse | Vote cible | β₁ — groupe cible | β₂ — complément | Dénominateur | Années |
| --- | --- | --- | --- | --- | --- |
| H0A | abstention | ouvriers + employés | agriculteurs + indépendants + cadres + professions intermédiaires | inscrits | 1962, 1986, 2022 |
| H1 | gauche | ouvriers + employés | agriculteurs + indépendants + cadres + professions intermédiaires | suffrages exprimés | 1962, 1986, 2022 |
| H5 | centre | cadres | agriculteurs + indépendants + professions intermédiaires + employés + ouvriers | suffrages exprimés | 1962, 1986, 2022 |
| H6 | fn_rn | ouvriers | agriculteurs + indépendants + cadres + professions intermédiaires + employés | suffrages exprimés | 1986, 2022 |
| H7 | fn_rn | employés | agriculteurs + indépendants + cadres + professions intermédiaires + ouvriers | suffrages exprimés | 1986, 2022 |

Les groupes sociaux sont construits à partir des six CSP actives. Les marges politiques sont validées avant fermeture par plus forts restes. Une commune absente ou dégénérée est exclue à la date concernée sans remplacement.

### Couverture exacte des figures

| Année | Hypothèse | Vue | Modèles | Palier | Communes | draws/tune/chaînes | Diagnostic |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1962 | H0A | common_intersection | King — normale tronquée, KRT — King99 bêta-binomial | 3000 | 2963 | 20/20/1 | fail |
| 1962 | H1 | common_intersection | King — normale tronquée, KRT — King99 bêta-binomial | 3000 | 2925 | 20/20/1 | fail |
| 1962 | H5 | native_only | KRT — King99 bêta-binomial | 3000 | 2985 | 20/20/1 | fail |
| 1986 | H0A | common_intersection | King — normale tronquée, KRT — King99 bêta-binomial | 3000 | 2928 | 20/20/1 | fail |
| 1986 | H1 | common_intersection | King — normale tronquée, KRT — King99 bêta-binomial | 3000 | 2935 | 20/20/1 | fail |
| 1986 | H5 | common_intersection | King — normale tronquée, KRT — King99 bêta-binomial | 3000 | 687 | 20/20/1 | fail |
| 1986 | H6 | common_intersection | King — normale tronquée, KRT — King99 bêta-binomial | 500 | 473 | 20/20/1 | fail |
| 1986 | H7 | common_intersection | King — normale tronquée, KRT — King99 bêta-binomial | 25 | 21 | 20/20/1 | fail |
| 2022 | H0A | common_intersection | King — normale tronquée, KRT — King99 bêta-binomial | 3000 | 2820 | 20/20/1 | fail |
| 2022 | H1 | common_intersection | King — normale tronquée, KRT — King99 bêta-binomial | 3000 | 2813 | 20/20/1 | fail |
| 2022 | H5 | common_intersection | King — normale tronquée, KRT — King99 bêta-binomial | 25 | 15 | 20/20/1 | fail |
| 2022 | H6 | common_intersection | King — normale tronquée, KRT — King99 bêta-binomial | 3000 | 2485 | 20/20/1 | fail |
| 2022 | H7 | common_intersection | King — normale tronquée, KRT — King99 bêta-binomial | 3000 | 2580 | 20/20/1 | fail |

## Formalisme et traduction algorithmique

Pour une année `t`, une hypothèse `h`, un modèle `m`, une commune `i` et un groupe social `g`, `β̂[g,i,t,h,m]` désigne la moyenne postérieure communale extraite directement de `b_1` ou `b_2`. Les densités représentent la distribution de ces `β̂`, à poids égal entre communes.

La comparaison annuelle trace :

`β̄[g,t,h,m] = (1 / |I[t,h]|) × Σ(i ∈ I[t,h]) β̂[g,i,t,h,m]`

où `I[t,h]` est l’intersection exacte des communes King/KRT lorsque les deux modèles existent. Pour H5-1962, aucune vue King valide n’existe : la vue KRT native est conservée et signalée. L’intervalle graphique est `[P25(β̂), P75(β̂)]` entre communes.

La correspondance code-formalisme est directe :

- extraction et export des `b_1`/`b_2` communaux : `code_longitudinal/beta_outputs.py`, fonction `build_commune_beta_estimates` ;
- construction des intersections et densités : `code_longitudinal/extract_latent_densities.py`, fonctions `_with_scopes`, `_select_largest_plot_views` et `_plot_curated_overlays` ;
- calcul de `β̄`, quartiles et contrôle des identifiants : `code_longitudinal/build_illustrated_report.py`, fonction `build_comparison_table` ;
- tracé interannuel sans interpolation : même fichier, fonction `plot_interannual_comparisons` ;
- génération du présent document : même fichier, fonction `write_illustrated_report`.

Le détail avec numéros de lignes est maintenu dans [`METHODOLOGY_CODE_MAP.md`](METHODOLOGY_CODE_MAP.md). La table exacte qui alimente les cinq comparaisons est [`outputs/illustrated_report_estimates.csv`](../outputs/illustrated_report_estimates.csv).

## 1962 — distributions communales

Chaque panneau montre la densité des moyennes postérieures communales : une commune compte une fois. La hauteur d’une densité n’est pas une probabilité ; la surface sous chaque courbe vaut un.

### H0A — Abstention — ouvriers et employés vs autres CSP

Vue : intersection exacte King/KRT ; palier demandé `3000` ; communes représentées `2963` ; modèles : King — normale tronquée, KRT — King99 bêta-binomial. Le diagnostic PyEI est `fail`, donc la figure documente la calibration, pas un résultat final.

![1962 — H0A — densités communales](../figures/densities/curated/density_overlay__leg_1962_r1__H0A__n3000.svg)

### H1 — Vote à gauche — ouvriers et employés vs autres CSP

Vue : intersection exacte King/KRT ; palier demandé `3000` ; communes représentées `2925` ; modèles : King — normale tronquée, KRT — King99 bêta-binomial. Le diagnostic PyEI est `fail`, donc la figure documente la calibration, pas un résultat final.

![1962 — H1 — densités communales](../figures/densities/curated/density_overlay__leg_1962_r1__H1__n3000.svg)

### H5 — Vote au centre — cadres vs autres CSP

Vue : vue native KRT, faute de vue King valide ; palier demandé `3000` ; communes représentées `2985` ; modèles : KRT — King99 bêta-binomial. Le diagnostic PyEI est `fail`, donc la figure documente la calibration, pas un résultat final.

![1962 — H5 — densités communales](../figures/densities/curated/density_overlay__leg_1962_r1__H5__n3000.svg)

## 1986 — distributions communales

Chaque panneau montre la densité des moyennes postérieures communales : une commune compte une fois. La hauteur d’une densité n’est pas une probabilité ; la surface sous chaque courbe vaut un.

### H0A — Abstention — ouvriers et employés vs autres CSP

Vue : intersection exacte King/KRT ; palier demandé `3000` ; communes représentées `2928` ; modèles : King — normale tronquée, KRT — King99 bêta-binomial. Le diagnostic PyEI est `fail`, donc la figure documente la calibration, pas un résultat final.

![1986 — H0A — densités communales](../figures/densities/curated/density_overlay__leg_1986_r1__H0A__n3000.svg)

### H1 — Vote à gauche — ouvriers et employés vs autres CSP

Vue : intersection exacte King/KRT ; palier demandé `3000` ; communes représentées `2935` ; modèles : King — normale tronquée, KRT — King99 bêta-binomial. Le diagnostic PyEI est `fail`, donc la figure documente la calibration, pas un résultat final.

![1986 — H1 — densités communales](../figures/densities/curated/density_overlay__leg_1986_r1__H1__n3000.svg)

### H5 — Vote au centre — cadres vs autres CSP

Vue : intersection exacte King/KRT ; palier demandé `3000` ; communes représentées `687` ; modèles : King — normale tronquée, KRT — King99 bêta-binomial. Le diagnostic PyEI est `fail`, donc la figure documente la calibration, pas un résultat final.

![1986 — H5 — densités communales](../figures/densities/curated/density_overlay__leg_1986_r1__H5__n3000.svg)

### H6 — Vote FN/RN — ouvriers vs autres CSP

Vue : intersection exacte King/KRT ; palier demandé `500` ; communes représentées `473` ; modèles : King — normale tronquée, KRT — King99 bêta-binomial. Le diagnostic PyEI est `fail`, donc la figure documente la calibration, pas un résultat final.

![1986 — H6 — densités communales](../figures/densities/curated/density_overlay__leg_1986_r1__H6__n500.svg)

### H7 — Vote FN/RN — employés vs autres CSP

Vue : intersection exacte King/KRT ; palier demandé `25` ; communes représentées `21` ; modèles : King — normale tronquée, KRT — King99 bêta-binomial. Le diagnostic PyEI est `fail`, donc la figure documente la calibration, pas un résultat final.

![1986 — H7 — densités communales](../figures/densities/curated/density_overlay__leg_1986_r1__H7__n25.svg)

## 2022 — distributions communales

Chaque panneau montre la densité des moyennes postérieures communales : une commune compte une fois. La hauteur d’une densité n’est pas une probabilité ; la surface sous chaque courbe vaut un.

### H0A — Abstention — ouvriers et employés vs autres CSP

Vue : intersection exacte King/KRT ; palier demandé `3000` ; communes représentées `2820` ; modèles : King — normale tronquée, KRT — King99 bêta-binomial. Le diagnostic PyEI est `fail`, donc la figure documente la calibration, pas un résultat final.

![2022 — H0A — densités communales](../figures/densities/curated/density_overlay__leg_2022_r1__H0A__n3000.svg)

### H1 — Vote à gauche — ouvriers et employés vs autres CSP

Vue : intersection exacte King/KRT ; palier demandé `3000` ; communes représentées `2813` ; modèles : King — normale tronquée, KRT — King99 bêta-binomial. Le diagnostic PyEI est `fail`, donc la figure documente la calibration, pas un résultat final.

![2022 — H1 — densités communales](../figures/densities/curated/density_overlay__leg_2022_r1__H1__n3000.svg)

### H5 — Vote au centre — cadres vs autres CSP

Vue : intersection exacte King/KRT ; palier demandé `25` ; communes représentées `15` ; modèles : King — normale tronquée, KRT — King99 bêta-binomial. Le diagnostic PyEI est `fail`, donc la figure documente la calibration, pas un résultat final.

![2022 — H5 — densités communales](../figures/densities/curated/density_overlay__leg_2022_r1__H5__n25.svg)

### H6 — Vote FN/RN — ouvriers vs autres CSP

Vue : intersection exacte King/KRT ; palier demandé `3000` ; communes représentées `2485` ; modèles : King — normale tronquée, KRT — King99 bêta-binomial. Le diagnostic PyEI est `fail`, donc la figure documente la calibration, pas un résultat final.

![2022 — H6 — densités communales](../figures/densities/curated/density_overlay__leg_2022_r1__H6__n3000.svg)

### H7 — Vote FN/RN — employés vs autres CSP

Vue : intersection exacte King/KRT ; palier demandé `3000` ; communes représentées `2580` ; modèles : King — normale tronquée, KRT — King99 bêta-binomial. Le diagnostic PyEI est `fail`, donc la figure documente la calibration, pas un résultat final.

![2022 — H7 — densités communales](../figures/densities/curated/density_overlay__leg_2022_r1__H7__n3000.svg)

## Limites, incertitude et robustesse

- Les diagnostics PyEI échouent : une chaîne ne permet pas de calculer un R-hat valide et 20 tirages ne permettent pas une ESS de production.
- Les barres P25–P75 résument les différences entre communes ; elles ne remplacent pas un intervalle de crédibilité ou une analyse d’incertitude interannuelle.
- Les effectifs varient selon la date et l’hypothèse à cause des absences et lignes dégénérées. Les communes ne sont jamais remplacées.
- H5-1962 est une vue KRT native, donc sans comparaison King/KRT. H5-2022 (`n=15`) et H7-1986 (`n=21`) sont des smoke tests particulièrement fragiles.
- L’inférence écologique estime des associations agrégées sous hypothèses de modèle ; elle n’observe pas les choix individuels et ne démontre pas de causalité.
- Trois dates ne suffisent pas à documenter la série 1962–2022 prévue dans le plan. Elles valident uniquement le format de restitution longitudinale.

## Suite recommandée

1. Relancer H0A et H1 en production (`4 × 1 000` draws, `1 000` tune, `target_accept=0,99`) sur les plus grands paliers autorisés par les garde-fous.
2. Réparer ou redéfinir les cas H5-2022 et H7-1986 avant toute comparaison temporelle.
3. Ajouter progressivement les autres législatives au même schéma, puis séparer un rapport présidentiel.
4. Ne convertir les observations descriptives en résultats que lorsque divergences, R-hat, ESS et intersections communes satisfont les critères configurés.

## Questions encore ouvertes

- Les contrastes visibles persistent-ils avec quatre chaînes et une ESS suffisante ?
- Restent-ils stables en pondération par effectifs sociaux plutôt qu’à poids communal égal ?
- Sont-ils robustes à l’ajout séparé de VBBM, revenu/capital, immigration et région Nord-Est/Sud-Est ?
- Les changements de périmètre communal expliquent-ils une part des différences entre années malgré l’absence de remplacement ?

## Sources internes

- `outputs/pilot_density_selection.csv` : choix des runs, intersections et effectifs ;
- `outputs/density_joint_data.csv` : β communaux joints et poids sociaux ;
- `outputs/illustrated_report_estimates.csv` : agrégats et quartiles exactement tracés ;
- `outputs/model_diagnostics.csv` : diagnostics des ajustements ;
- `figures/densities/curated/` : treize superpositions de densités ;
- `figures/illustrated_report/` : cinq comparaisons interannuelles.
