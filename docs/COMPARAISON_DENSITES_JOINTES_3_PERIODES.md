# Comparaison des densités jointes de β₁ et β₂ — 1962, 1986 et 2022

## Conclusion du contrôle visuel

Les panneaux correspondant aux six fits, répétés sous deux pondérations, sont cohérents et comparables : chaque période contient les mêmes 3 000 communes, les axes sont fixés de 0 à 1, la diagonale `β₁=β₂` est visible et la même matrice de lissage est utilisée entre les trois dates à l’intérieur de chaque hypothèse et de chaque schéma de pondération.

Le résultat visuel principal est double :

- **H0A** passe d’une distribution largement au-dessus de la diagonale en 1962 (`β₁<β₂`) à des distributions largement en dessous en 1986 et 2022 (`β₁>β₂`) ; 2022 est en outre déplacée vers des niveaux d’abstention nettement plus élevés ;
- **H1** est très diffuse et multimodale en 1962, concentrée sous la diagonale en 1986 (`β₁>β₂`), puis déplacée vers le bas-gauche et majoritairement au-dessus de la diagonale en 2022 (`β₁<β₂`).

Le cas H1–1962 est le seul panneau dont la masse s’étend fortement vers les bornes 0 et 1. Cette forme est présente dans les données de latents communaux et dans les deux pondérations : elle ne correspond pas à un panneau vide, à une mauvaise échelle ou à une erreur de rendu. Elle doit néanmoins être interprétée avec prudence à cause de la géométrie près des bornes, de la multimodalité et du diagnostic MCMC `caveat`.

## Ce que représentent les graphiques

Chaque point est une commune et porte les coordonnées :

- axe horizontal : moyenne postérieure communale `b1_mean`, ouvriers + employés ;
- axe vertical : moyenne postérieure communale `b2_mean`, autres CSP.

La diagonale partage le plan en deux :

- en dessous, `β₁>β₂` ;
- au-dessus, `β₁<β₂`.

Les contours HDR contiennent respectivement 50 %, 80 % et 95 % de la masse de la densité KDE. Ces figures décrivent la **distribution entre communes de moyennes postérieures**. Elles ne représentent ni 3 000 individus, ni l’ensemble des draws MCMC, ni un intervalle crédible de la moyenne agrégée.

Deux pondérations répondent à deux questions différentes :

| Version | Poids | Question descriptive |
| --- | --- | --- |
| `equal_communes` | une commune = un poids | comment se répartissent les communes du panel ? |
| `N_total_weighted` | poids proportionnel au dénominateur communal | où se situe la masse lorsque les grandes communes comptent davantage ? |

Les échelles de densité de couleur ne doivent être comparées qu’à l’intérieur d’une même planche. Elles diffèrent volontairement entre H0A/H1 et entre pondération égale/pondérée.

## H0A — abstention

### Communes équipondérées

![H0A — densité jointe, communes équipondérées](../figures/v2/priority_3000_final/densities/joint_beta_H0A_common_bandwidth_equal_communes.png)

**Lecture visuelle.** En 1962, la masse se situe principalement au-dessus de la diagonale : l’abstention latente est généralement plus élevée pour les autres CSP que pour les ouvriers et employés. La distribution est allongée et l’étalement vertical de β₂ est plus important. En 1986, la masse se resserre dans le bas-gauche et passe sous la diagonale. En 2022, elle se déplace nettement vers le haut-droite tout en restant majoritairement sous la diagonale. Le déplacement 1986→2022 concerne donc à la fois le niveau général d’abstention et l’ampleur du contraste.

### Pondération par la taille communale

![H0A — densité jointe, pondération N total](../figures/v2/priority_3000_final/densities/joint_beta_H0A_common_bandwidth_N_total_weighted.png)

**Lecture visuelle.** La pondération par taille ne change pas le sens du résultat. Elle renforce la part de masse sous la diagonale en 1986 et surtout en 2022. Les grandes communes de 2022 sont légèrement plus à droite et en haut que la commune moyenne, ce qui explique le déplacement des centroïdes pondérés. En 1962, elles renforcent au contraire le constat `β₁<β₂`.

### Résumé descriptif à poids égal

| Année | Moyenne β₁ | É.-t. β₁ | Moyenne β₂ | É.-t. β₂ | Corrélation | Communes avec β₁>β₂ |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1962 | 0,253 | 0,055 | 0,360 | 0,115 | 0,771 | 9,4 % |
| 1986 | 0,196 | 0,040 | 0,166 | 0,040 | 0,857 | 93,6 % |
| 2022 | 0,498 | 0,063 | 0,435 | 0,045 | 0,748 | 93,1 % |

Ces statistiques sont calculées sur les 3 000 couples de `joint_latent_3000_v1.csv`. Elles confirment la forme visible : 1962 possède notamment un étalement de β₂ presque trois fois supérieur à celui de 1986.

## H1 — vote à gauche

### Communes équipondérées

![H1 — densité jointe, communes équipondérées](../figures/v2/priority_3000_final/densities/joint_beta_H1_common_bandwidth_equal_communes.png)

**Lecture visuelle.** H1–1962 est très hétérogène : la masse est étendue, multimodale et atteint les voisinages de 0 et 1. La simple position d’un mode ne suffit donc pas à résumer cette période. En 1986, la distribution devient beaucoup plus compacte, orientée positivement et principalement sous la diagonale. En 2022, elle se déplace vers des valeurs plus faibles de β₁ et β₂ et passe majoritairement au-dessus de la diagonale, ce qui correspond à l’inversion du contraste agrégé.

### Pondération par la taille communale

![H1 — densité jointe, pondération N total](../figures/v2/priority_3000_final/densities/joint_beta_H1_common_bandwidth_N_total_weighted.png)

**Lecture visuelle.** La pondération par taille conserve la forte dispersion de 1962, mais donne davantage de poids à la masse centrale et aux grandes communes à β₁ élevé. En 1986, elle concentre encore davantage la masse sous la diagonale. En 2022, elle conserve une majorité de masse au-dessus de la diagonale. Le sens des trois périodes est donc robuste au passage d’une commune-un poids à une pondération par taille, même si les formes et les centroïdes changent.

### Résumé descriptif à poids égal

| Année | Moyenne β₁ | É.-t. β₁ | Moyenne β₂ | É.-t. β₂ | Corrélation | Communes avec β₁>β₂ |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1962 | 0,409 | 0,176 | 0,364 | 0,273 | 0,634 | 65,6 % |
| 1986 | 0,495 | 0,099 | 0,367 | 0,131 | 0,821 | 93,5 % |
| 2022 | 0,272 | 0,098 | 0,309 | 0,102 | 0,714 | 23,8 % |

La dispersion de H1–1962 est bien supérieure à celle des deux autres périodes, en particulier pour β₂. La corrélation positive observée dans tous les panneaux traduit une co-variation communale ; elle n’est pas une preuve causale.

## Effet quantitatif de la pondération par taille

Le tableau suivant utilise `N_total = b1_weight + b2_weight`. La dernière colonne est la taille effective de la pondération, `1/Σwᵢ²`, après normalisation des poids.

| Hypothèse | Année | β₁ pondérée | β₂ pondérée | Corrélation pondérée | Masse pondérée β₁>β₂ | n effectif |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| H0A | 1962 | 0,259 | 0,371 | 0,756 | 4,1 % | 227 |
| H0A | 1986 | 0,220 | 0,184 | 0,854 | 96,0 % | 286 |
| H0A | 2022 | 0,543 | 0,463 | 0,849 | 98,7 % | 320 |
| H1 | 1962 | 0,452 | 0,374 | 0,648 | 70,8 % | 219 |
| H1 | 1986 | 0,514 | 0,368 | 0,865 | 98,3 % | 299 |
| H1 | 2022 | 0,302 | 0,340 | 0,809 | 20,8 % | 326 |

La forte réduction du nombre effectif est attendue : quelques grandes communes portent une part importante du poids total. La version pondérée décrit donc davantage les grandes unités et ne doit pas remplacer silencieusement la version équipondérée.

## Densités marginales comme contrôle complémentaire

![H0A — densités marginales sociales comparées](../figures/v2/priority_3000_final/densities/marginal_beta_H0A_group_population_weighted.png)

**Lecture.** Pour H0A, les courbes marginales montrent clairement l’inversion entre 1962 et 1986 ainsi que le déplacement général vers des probabilités d’abstention plus élevées en 2022. Les courbes sont pondérées par `N1` pour β₁ et `N2` pour β₂, ce qui correspond mieux aux deux populations sociales que la pondération jointe par `N_total`.

![H1 — densités marginales sociales comparées](../figures/v2/priority_3000_final/densities/marginal_beta_H1_group_population_weighted.png)

**Lecture.** Pour H1, la courbe de β₁ est la plus à droite en 1986 et la plus à gauche en 2022. Les marginales de 1962 restent nettement plus larges et parfois multimodales, surtout pour β₂. Cette instabilité visuelle concorde avec la prudence diagnostique exigée pour H1–1962.

## Pourquoi les centroïdes des figures ne sont pas exactement les agrégats publiés

Les moyennes des figures jointes sont calculées sur les moyennes postérieures communales : poids égaux ou un poids commun `N_total` pour chaque couple `(β₁,β₂)`. Les agrégats publiés suivent une autre procédure, plus appropriée aux estimands sociaux :

`β̄₁(s) = Σᵢ N1ᵢ β₁ᵢ(s) / Σᵢ N1ᵢ`

`β̄₂(s) = Σᵢ N2ᵢ β₂ᵢ(s) / Σᵢ N2ᵢ`

Ils sont recalculés à chaque draw `s`, puis résumés. Il est donc normal qu’un centroïde visuel, une proportion de communes sous la diagonale et le contraste agrégé ne soient pas numériquement identiques. Les figures contrôlent la forme communale ; les tables draw-wise contrôlent l’estimand agrégé.

## Contrôle visuel formel

| Contrôle | Résultat | Commentaire |
| --- | --- | --- |
| trois périodes présentes | conforme | 1962, 1986 et 2022 dans chaque planche |
| même nombre de communes | conforme | `n=3000` affiché dans chaque panneau |
| axes comparables | conforme | x et y fixés à `[0,1]` |
| diagonale de référence | conforme | ligne `β₁=β₂` visible |
| lissage temporel comparable | conforme | même matrice H entre dates, par hypothèse et pondération |
| contours de masse | conforme | HDR 50 %, 80 % et 95 % identifiés |
| distinction de pondération | conforme | points constants ou proportionnels à `N_total` |
| labels et légendes | conforme | axes, années, poids et contours lisibles |
| version vectorielle | conforme | un SVG accompagne chaque PNG |
| comportement aux bornes | réserve | H1–1962 atteint 0/1 ; prudence sur la KDE de bord |

## Limites d’interprétation des densités

1. Une KDE lisse les données ; ses modes et contours dépendent du bandwidth choisi.
2. Le bandwidth commun améliore la comparaison temporelle, mais ne supprime pas le biais de bord sur `[0,1]`.
3. Les points sont des moyennes postérieures ; l’incertitude propre à chaque commune est comprimée dans un seul couple.
4. Les HDR représentent une masse KDE descriptive, pas une région crédible d’un paramètre agrégé.
5. Les communes partagent un modèle hiérarchique et ne sont pas des observations indépendantes au sens classique.
6. La position relative à la diagonale ne remplace pas le calcul draw-wise des contrastes.
7. La version `N_total` a une taille effective de 219 à 326 communes selon le panneau ; elle est dominée par les grandes communes.

## Sources et reproductibilité

- données : `outputs/v2/priority_3000_final/joint_latent_3000_v1.csv` ;
- paramètres de lissage : `outputs/v2/priority_3000_final/density_bandwidths_3000_v1.csv` ;
- figures : `figures/v2/priority_3000_final/densities/` ;
- générateur : `code_longitudinal/density_figures_v2.py` ;
- agrégats de référence : `outputs/v2/priority_3000_final/aggregate_drawwise_corrected_3000_v1.csv` ;
- contrastes : `outputs/v2/priority_3000_final/within_period_contrasts_3000_v1.csv`.
