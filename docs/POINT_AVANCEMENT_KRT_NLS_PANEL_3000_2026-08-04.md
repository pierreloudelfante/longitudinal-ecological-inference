# Point d'avancement - estimations KRT et NLS sur un panel de 3 000 communes

*Production intermédiaire - 4 août 2026*

## Synthèse technique

Conditionnellement au panel, au recalibrage des marges sociales et au modèle KRT, les six intervalles crédibles des contrastes intra-période ne recouvrent pas zéro. Ces résultats restent des estimations écologiques dépendantes de la structure hiérarchique et des priors. Les bornes de tomographie sont larges dans la majorité des ajustements et ne permettent pas une interprétation directe en comportements individuels.

Le contraste écologique d'abstention passe de -11,0 points en 1962 à +3,9 points en 1986 puis +8,8 points en 2022. Pour le vote à gauche, il passe de +10,1 points à +15,6 points puis -3,4 points.

Diagnostics MCMC : 2 ajustements satisfaisants, 4 satisfaisants avec réserve, 0 insuffisant ; aucune divergence. Identification écologique : 1 pass et 5 caveat.

NLS : 12 ajustements H0A, H1, H2 et H4, tous avec diagnostic pass. Pour H0A et H1, 6 comparaisons sur 6 ont le même signe que les KRT ; les écarts de niveau restent importants pour H1 en 1962 et 1986.

Sur les 9 000 couples commune-année du panel, une seule anomalie apparaît dans la comparaison directe des dénominateurs publiés par H0A et H1 : pour `02643` en 1986, les 392 suffrages exprimés de H1 dépassent les 383 inscrits de H0A. Le panel reste équilibré et les six estimations existantes sont conservées comme résultats intermédiaires. La valeur source n'est pas corrigée arbitrairement ; une validation renforcée et un panel V3 sont prêts pour les prochaines estimations.

## Résultats principaux

![Contrastes intra-période](../figures/v2/priority_3000_final/within_period_contrasts_3000_v1.png)

Le graphique présente `β1-β2`, avec `β1` pour les ouvriers et employés et `β2` pour les autres CSP. Une valeur positive indique un niveau estimé plus élevé pour les ouvriers et employés.

| Hypothèse | Année | β1 | β2 | β1-β2 [ICr 95 %] |
| --- | --- | --- | --- | --- |
| H0A | 1962 | 0,260 | 0,370 | -0,110 [-0,136 ; -0,085] |
| H0A | 1986 | 0,222 | 0,184 | +0,039 [+0,020 ; +0,057] |
| H0A | 2022 | 0,550 | 0,461 | +0,088 [+0,071 ; +0,106] |
| H1 | 1962 | 0,467 | 0,366 | +0,101 [+0,040 ; +0,159] |
| H1 | 1986 | 0,518 | 0,363 | +0,156 [+0,113 ; +0,199] |
| H1 | 2022 | 0,305 | 0,339 | -0,034 [-0,060 ; -0,008] |

![Agrégats calculés tirage par tirage](../figures/v2/priority_3000_final/aggregate_drawwise_corrected_3000_v1.png)

Les niveaux de H0A et H1 ne sont pas directement comparables : H0A porte sur l'abstention parmi les inscrits, H1 sur le vote à gauche parmi les suffrages exprimés.

### Influence descriptive de la commune `02643`

| Hypothèse 1986 | Contraste publié | Sans 02643 | Variation |
| --- | --- | --- | --- |
| H0A | +0,039 | +0,039 | +0,0009 point |
| H1 | +0,156 | +0,156 | +0,0004 point |

Ce calcul retire `02643` des agrégats de moyennes postérieures déjà estimées ; ce n'est pas une réestimation du modèle hiérarchique. La variation est de 0,0009 point pour H0A et de 0,0004 point pour H1. Les conclusions arrondies restent respectivement `+3,9` et `+15,6` points. Un recalcul ponctuel H0A-1962 sur le panel V3 donne par ailleurs un écart de -0,05 point ; il n'est pas mélangé à la série principale V2.

## Résultats NLS

Les NLS constituent un benchmark déterministe distinct des modèles KRT. Douze ajustements sont disponibles : H0A, H1, H2 et H4 pour 1962, 1986 et 2022, toujours sur le panel V2 commun de 3 000 communes. Chaque contraste est la probabilité estimée du premier groupe moins celle du second groupe pour l'événement défini par l'hypothèse.

![Contrastes NLS par hypothèse et année](../figures/v2/priority_3000_final/nls_contrasts_3000_v1.png)

| Hyp. | Année | Événement et dénominateur | Groupe 1 | Groupe 2 | Contraste |
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

H0A reproduit l'inversion de signe entre 1962 et les deux dates suivantes. H1 et H2 sont positifs en 1962 et 1986, puis négatifs en 2022. H4 est positif aux trois dates, mais devient presque nul en 2022. Ces valeurs sont des estimations ponctuelles NLS ; aucun intervalle du contraste n'est revendiqué à partir des exports disponibles.

### Comparaison KRT-NLS pour H0A et H1

![Comparaison des contrastes KRT et NLS](../figures/v2/priority_3000_final/nls_krt_comparison_3000_v1.png)

| Hyp. | Année | KRT [ICr 95 %] | NLS | NLS - KRT |
| --- | --- | --- | --- | --- |
| H0A | 1962 | -0,110 [-0,136 ; -0,085] | -0,098 | +0,012 |
| H0A | 1986 | +0,039 [+0,020 ; +0,057] | +0,027 | -0,011 |
| H0A | 2022 | +0,088 [+0,071 ; +0,106] | +0,057 | -0,031 |
| H1 | 1962 | +0,101 [+0,040 ; +0,159] | +0,011 | -0,090 |
| H1 | 1986 | +0,156 [+0,113 ; +0,199] | +0,099 | -0,057 |
| H1 | 2022 | -0,034 [-0,060 ; -0,008] | -0,044 | -0,010 |

Les six comparaisons ont le même signe. Les niveaux sont proches pour H0A, avec des écarts NLS-KRT de `+1,2`, `-1,1` et `-3,1` points. Pour H1, les NLS sont inférieurs aux KRT de `9,0` points en 1962, `5,7` points en 1986 et `1,0` point en 2022. La concordance de signe est donc descriptive ; elle ne signifie pas que les deux modèles fournissent des estimations interchangeables.

### Diagnostics numériques NLS

| Hyp. | Année | Statut | Départs réussis | SSE | Condition information |
| --- | --- | --- | --- | --- | --- |
| H0A | 1962 | pass | 20/20 | 33,34 | 6,61 |
| H0A | 1986 | pass | 20/20 | 9,17 | 15,03 |
| H0A | 2022 | pass | 20/20 | 17,25 | 5,78 |
| H1 | 1962 | pass | 20/20 | 177,37 | 7,06 |
| H1 | 1986 | pass | 20/20 | 54,12 | 15,89 |
| H1 | 2022 | pass | 20/20 | 47,39 | 6,41 |
| H2 | 1962 | pass | 20/20 | 177,33 | 10,90 |
| H2 | 1986 | pass | 20/20 | 54,63 | 21,80 |
| H2 | 2022 | pass | 20/20 | 47,27 | 17,44 |
| H4 | 1962 | pass | 20/20 | 177,31 | 6,05 |
| H4 | 1986 | pass | 20/20 | 53,41 | 20,96 |
| H4 | 2022 | pass | 20/20 | 70,03 | 23,30 |

Les 12 ajustements ont le statut `pass`, avec 20 départs réussis sur 20. Ce contrôle porte sur la réussite et la stabilité numérique de l'optimisation. Il ne remplace ni une mesure d'incertitude du contraste, ni le contrôle d'identification écologique présenté pour les KRT.

## Comparaisons entre périodes

| Hypothèse | Comparaison | Changement [intervalle 95 %] | Lecture |
| --- | --- | --- | --- |
| H0A | 1962 -> 1986 | +0,149 [+0,117 ; +0,181] | signe déterminé sous le modèle |
| H0A | 1962 -> 2022 | +0,198 [+0,167 ; +0,230] | signe déterminé sous le modèle |
| H0A | 1986 -> 2022 | +0,049 [+0,025 ; +0,075] | signe déterminé sous le modèle |
| H1 | 1962 -> 1986 | +0,055 [-0,018 ; +0,130] | intervalle contenant zéro |
| H1 | 1962 -> 2022 | -0,135 [-0,199 ; -0,069] | signe déterminé sous le modèle |
| H1 | 1986 -> 2022 | -0,189 [-0,241 ; -0,139] | signe déterminé sous le modèle |

Les changements sont calculés à partir de 50 000 paires indépendantes de tirages provenant des ajustements séparés. Il ne s'agit ni d'un modèle temporel joint, ni du suivi des mêmes électeurs.

## Échantillonnage et contrôle des données

Le panel ayant servi aux six estimations est un tirage de 3 000 communes dans 33 922 communes admissibles selon les contrôles initiaux. Il reste largement sous les seuils d'écart fixés. La règle transversale ajoutée retire huit communes de cet univers, qui compte désormais **33 914 communes**. La virgule indique ici le séparateur de milliers. Le panel V3 corrigé conserve exactement 3 000 communes et sera utilisé pour les prochaines estimations.

| Élément | Valeur |
| --- | ---: |
| taille du panel | 3 000 communes |
| graine | `20260802` |
| règle électorale | `0 <= exprimés <= votants <= inscrits` |
| tolérance des flottants | 0,01 voix |
| maximum `|SMD|` du panel estimé V2 | 0,01939 |
| maximum d'écart catégoriel V2 | 0,01032 |
| maximum `|SMD|` du futur panel V3 | 0,01918 |
| maximum d'écart catégoriel V3 | 0,01065 |
| seuils | 0,10 et 0,02 |
| `king_lambda` | 0,5 |

Réparation prévue pour les prochains calculs - communes retirées : `59473`, `14606`, `02643`, `06149`. Communes ajoutées : `05062`, `14249`, `50079`, `37093`.

La sélection V3 ne refait pas un tirage entièrement différent. Elle reprend l'ordre aléatoire V2, écarte les unités qui échouent au nouveau contrôle et poursuit cet ordre jusqu'à retrouver 3 000 communes. L'équilibre est ensuite recalculé par rapport à l'univers commun corrigé et à l'univers de référence 2022. Les six estimations principales n'ont pas été relancées : l'anomalie ne remet pas en cause l'échantillonnage et son influence descriptive est négligeable.

Pour Ressons-le-Long (`02643`), le CSV officiel utilisé par le projet est identique au fichier actuellement distribué (SHA-256 `e265cdd2...`). Le procès-verbal numérisé indique 383 inscrits, 415 votants, 23 bulletins nuls et 392 exprimés : la source d'archive est elle-même incohérente. Aucune valeur d'inscrits n'a donc été inventée ; la commune est exclue du panel préparé pour les prochains calculs. [Page officielle des données](https://www.unehistoireduconflitpolitique.fr/telecharger.html).

Le contrôle brut plus strict `exprimés <= votants <= inscrits` repère neuf lignes sources, dont quatre appartiennent au panel V2. Trois de ces quatre lignes supplémentaires ont `exprimés > votants` mais pas `exprimés > inscrits` ; elles n'apparaissent donc pas dans l'unique anomalie issue de la comparaison directe H0A-H1. Le détail est disponible dans [`source_data_anomalies_3000_v1.csv`](../outputs/v2/priority_3000_final/source_data_anomalies_3000_v1.csv).

## Hypothèses et estimation

| Hypothèse | Événement | β1 | β2 | Dénominateur |
| --- | --- | --- | --- | --- |
| H0A | abstention | ouvriers + employés | autres CSP | inscrits |
| H1 | vote à gauche (`voteG + voteCG`) | ouvriers + employés | autres CSP | exprimés |

Les parts sociales sont recalibrées sur le dénominateur électoral propre à chaque hypothèse, puis fermées par la méthode du plus fort reste. Le modèle KRT bêta-binomial est estimé séparément pour chaque année. Chaque ajustement utilise 4 chaînes, 1 000 itérations de chauffe et 1 000 tirages conservés par chaîne, `target_accept=0,99`, `max_treedepth=14` et `king_lambda=0,5`.

Les agrégats sont calculés à chaque tirage avec les poids propres aux groupes : `N1` pour `β1` et `N2` pour `β2`. Le contraste est ensuite calculé sur les agrégats obtenus au même tirage.

Le benchmark NLS utilise le modèle `rosen_nls_2x2_unadjusted`. Chaque ajustement repose sur 20 points de départ, une tolérance de `1e-9`, un maximum de 5 000 évaluations et la graine `20260802`. Contrairement aux KRT, ces sorties NLS sont présentées comme des estimations ponctuelles : les exports ne permettent pas de construire directement un intervalle fiable du contraste entre groupes.

## Diagnostics MCMC

![Diagnostics centrés sur les paramètres β](../figures/v2/priority_3000_final/canonical_diagnostics_3000_v1.png)

Les valeurs affichées sont les pires parmi les 6 000 paramètres communaux `b_1` et `b_2`. Le bilan devient « satisfaisant avec réserve » lorsqu'un paramètre hors β est moins bien identifié, même si les β passent les seuils.

| Hyp. | Année | Bilan | β | Hors β | R-hat max β | ESS bulk min β | ESS tail min β | Div. |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| H0A | 1962 | satisfaisant avec réserve | pass | caveat | 1,0072 | 2819 | 2080 | 0 |
| H0A | 1986 | satisfaisant avec réserve | pass | caveat | 1,0069 | 4206 | 2008 | 0 |
| H0A | 2022 | satisfaisant | pass | pass | 1,0085 | 5092 | 2036 | 0 |
| H1 | 1962 | satisfaisant avec réserve | caveat | caveat | 1,0102 | 581 | 358 | 0 |
| H1 | 1986 | satisfaisant | pass | pass | 1,0074 | 4216 | 1990 | 0 |
| H1 | 2022 | satisfaisant avec réserve | pass | caveat | 1,0077 | 2327 | 1707 | 0 |

![Diagnostics des contrastes agrégés](../figures/v2/priority_3000_final/estimand_diagnostics_3000_v1.png)

Les diagnostics du contraste complètent ceux des paramètres communaux. Ils ne remplacent pas le contrôle d'identification écologique.

## Identification écologique

| Hypothèse | Année | Statut | Largeur médiane max | P90 largeur max |
| --- | --- | --- | --- | --- |
| H0A | 1962 | caveat | 0,912 | 1,000 |
| H0A | 1986 | pass | 0,461 | 0,800 |
| H0A | 2022 | caveat | 1,000 | 1,000 |
| H1 | 1962 | caveat | 0,842 | 1,000 |
| H1 | 1986 | caveat | 1,000 | 1,000 |
| H1 | 2022 | caveat | 0,821 | 1,000 |

Une convergence MCMC satisfaisante signifie que l'échantillonneur explore correctement la distribution définie par le modèle. Elle ne garantit pas que les marges communales identifient seules les probabilités individuelles.

## Annexe - comparaison visuelle des densités communales

Les densités jointes portent sur les couples de moyennes postérieures communales `(b1_mean, b2_mean)`. Elles montrent l'hétérogénéité entre communes et non l'incertitude d'une moyenne nationale. Les axes et la bande passante sont communs aux trois années d'une même hypothèse ; la diagonale représente `β1=β2`.

### Communes équipondérées

![Densités jointes H0A - communes équipondérées](../figures/v2/priority_3000_final/densities/joint_beta_H0A_common_bandwidth_equal_communes.png)

Pour H0A, la masse est surtout du côté `β1<β2` en 1962, puis du côté `β1>β2` en 1986 et 2022.

![Densités jointes H1 - communes équipondérées](../figures/v2/priority_3000_final/densities/joint_beta_H1_common_bandwidth_equal_communes.png)

Pour H1, la distribution de 1962 reste la plus dispersée. La position relative des groupes s'inverse entre 1986 et 2022.

### Pondération par la taille électorale communale

![Densités jointes H0A - pondération par N total](../figures/v2/priority_3000_final/densities/joint_beta_H0A_common_bandwidth_N_total_weighted.png)

![Densités jointes H1 - pondération par N total](../figures/v2/priority_3000_final/densities/joint_beta_H1_common_bandwidth_N_total_weighted.png)

La pondération par le dénominateur communal conserve les positions générales. Les formes ne reposent donc pas seulement sur les petites communes, sans constituer pour autant un test de sensibilité aux priors.

### Densités marginales pondérées par les groupes

![Densités marginales H0A](../figures/v2/priority_3000_final/densities/marginal_beta_H0A_group_population_weighted.png)

![Densités marginales H1](../figures/v2/priority_3000_final/densities/marginal_beta_H1_group_population_weighted.png)

## Limites et travaux suivants

- Les résultats sont conditionnels au panel estimé V2, au recalibrage des marges, aux priors et à `king_lambda=0,5`.
- Les comparaisons NLS-KRT portent sur des modèles de nature différente ; la concordance de signe ne constitue pas un test de robustesse complet.
- L'intersection temporelle favorise les communes stables dans la géographie 2022 ; il s'agit d'un échantillon de communes, pas d'électeurs.
- Les posterior predictive checks complets restent à produire.
- La sensibilité aux priors, à `king_lambda`, au recalibrage et à plusieurs panels admissibles reste à mesurer.
- Les densités devront être comparées entre toutes les communes et le sous-ensemble `N1>0` et `N2>0`.
- Les comparaisons entre dates ne sont ni causales ni individuelles.

## Fichiers de référence

- [`release_manifest_3000_v1.json`](../outputs/v2/priority_3000_final/release_manifest_3000_v1.json) : paramètres, runs et empreintes ;
- [`within_period_contrasts_3000_v1.csv`](../outputs/v2/priority_3000_final/within_period_contrasts_3000_v1.csv) : résultats intra-période ;
- [`canonical_mcmc_diagnostics_3000_v1.csv`](../outputs/v2/priority_3000_final/canonical_mcmc_diagnostics_3000_v1.csv) : diagnostics centrés sur les β ;
- [`identification_separate_3000_v1.csv`](../outputs/v2/priority_3000_final/identification_separate_3000_v1.csv) : identification écologique ;
- [`nls_contrasts_3000_v1.csv`](../outputs/v2/priority_3000_final/nls_contrasts_3000_v1.csv) : résultats ponctuels des 12 NLS ;
- [`nls_model_diagnostics_3000_v1.csv`](../outputs/v2/priority_3000_final/nls_model_diagnostics_3000_v1.csv) : diagnostics numériques NLS ;
- [`nls_krt_comparison_3000_v1.csv`](../outputs/v2/priority_3000_final/nls_krt_comparison_3000_v1.csv) : comparaison H0A/H1 entre NLS et KRT ;
- [`future_panel_v3_manifest.json`](../outputs/v2/priority_3000_final/future_panel_v3_manifest.json) : construction du panel prévu pour les prochaines estimations.
