# Récapitulatif global pour le professeur — législatives 1962, 1986 et 2022

## Synthèse technique

Le pipeline pilote est complet sur trois coupes législatives choisies pour leur rôle analytique : **1962** (début de série), **1986** (recomposition sous scrutin proportionnel) et **2022** (point récent). Les 34 partitions admissibles ferment exactement ; les cinq hypothèses ajoutées H0B/H0C/H2/H3/H4 atteignent n=3 000 pour King et KRT aux trois dates. Sur le registre pilote complet, **52 des 56 couples modèle–scénario atteignent n=3 000**, trois restent limités par les ressources et King-H5-1962 est structurellement inapplicable.

Le dossier conserve **674,654 lignes de bêtas communaux**, **370 traces NetCDF indexées** et **238 figures SVG**. RXC1/RXC2 NLS passent en 1986 et 2022 ; en 1962, les deux convergent mais échouent au diagnostic de rang à cause d’un bloc centre presque toujours nul.

La limite centrale doit rester visible : les PyEI du pilote utilisent **20 draws, 20 tune et une chaîne**. Les figures valident les données, l’extraction de b₁/b₂, les intersections, la montée à n=3 000 et le format de restitution ; elles ne constituent pas encore des estimations de production ni des comportements individuels observés.

## Les huit comparaisons canoniques entre les trois périodes

Les années sont des coupes discrètes. Chaque point est la moyenne non pondérée des moyennes postérieures communales ; chaque barre est P25–P75 entre communes, pas un intervalle de crédibilité. Aucun segment ne relie les dates afin de ne pas suggérer une trajectoire continue avec seulement trois observations temporelles.

### H0A — Abstention — ouvriers et employés vs autres CSP

Dénominateur : **inscrits**. Écart descriptif de la coupe 2022 à la coupe 1962 sur la moyenne communale : β₁ : King +0.140, KRT +0.235 ; β₂ : King +0.116, KRT +0.093. Ces écarts ne sont ni une trajectoire continue ni un effet causal. Les deux modèles utilisent l’intersection exacte au palier demandé n=3 000 pour les trois dates. Tous les points restent des calibrations PyEI 20/20/1 avec diagnostic `fail`.

![Comparaison canonique 1962–1986–2022 — H0A](../figures/professor_recap/comparison_interannuelle__H0A.svg)

| Année | Modèle | Communes | β₁ ouvriers + employés | β₂ agriculteurs + indépendants + cadres + professions intermédiaires | Diagnostic |
| --- | --- | --- | --- | --- | --- |
| 1962 | King — normale tronquée | 2 963 | 0.347 | 0.331 | fail |
| 1962 | KRT — King99 bêta-binomial | 2 963 | 0.235 | 0.376 | fail |
| 1986 | King — normale tronquée | 2 928 | 0.195 | 0.206 | fail |
| 1986 | KRT — King99 bêta-binomial | 2 928 | 0.159 | 0.208 | fail |
| 2022 | King — normale tronquée | 2 820 | 0.488 | 0.448 | fail |
| 2022 | KRT — King99 bêta-binomial | 2 820 | 0.470 | 0.469 | fail |

### H0B — Abstention — ouvriers vs autres CSP

Dénominateur : **inscrits**. Écart descriptif de la coupe 2022 à la coupe 1962 sur la moyenne communale : β₁ : King +0.107, KRT +0.266 ; β₂ : King +0.163, KRT +0.106. Ces écarts ne sont ni une trajectoire continue ni un effet causal. Les deux modèles utilisent l’intersection exacte au palier demandé n=3 000 pour les trois dates. Tous les points restent des calibrations PyEI 20/20/1 avec diagnostic `fail`.

![Comparaison canonique 1962–1986–2022 — H0B](../figures/professor_recap/comparison_interannuelle__H0B.svg)

| Année | Modèle | Communes | β₁ ouvriers | β₂ agriculteurs + indépendants + cadres + professions intermédiaires + employés | Diagnostic |
| --- | --- | --- | --- | --- | --- |
| 1962 | King — normale tronquée | 2 962 | 0.383 | 0.295 | fail |
| 1962 | KRT — King99 bêta-binomial | 2 962 | 0.225 | 0.360 | fail |
| 1986 | King — normale tronquée | 2 901 | 0.300 | 0.145 | fail |
| 1986 | KRT — King99 bêta-binomial | 2 901 | 0.197 | 0.176 | fail |
| 2022 | King — normale tronquée | 2 494 | 0.490 | 0.458 | fail |
| 2022 | KRT — King99 bêta-binomial | 2 494 | 0.491 | 0.467 | fail |

### H0C — Abstention — employés vs autres CSP

Dénominateur : **inscrits**. Écart descriptif de la coupe 2022 à la coupe 1962 sur la moyenne communale : β₁ : King +0.004, KRT +0.121 ; β₂ : King +0.173, KRT +0.161. Ces écarts ne sont ni une trajectoire continue ni un effet causal. Les deux modèles utilisent l’intersection exacte au palier demandé n=3 000 pour les trois dates. Tous les points restent des calibrations PyEI 20/20/1 avec diagnostic `fail`.

![Comparaison canonique 1962–1986–2022 — H0C](../figures/professor_recap/comparison_interannuelle__H0C.svg)

| Année | Modèle | Communes | β₁ employés | β₂ agriculteurs + indépendants + cadres + professions intermédiaires + ouvriers | Diagnostic |
| --- | --- | --- | --- | --- | --- |
| 1962 | King — normale tronquée | 2 798 | 0.487 | 0.288 | fail |
| 1962 | KRT — King99 bêta-binomial | 2 798 | 0.371 | 0.302 | fail |
| 1986 | King — normale tronquée | 2 824 | 0.415 | 0.131 | fail |
| 1986 | KRT — King99 bêta-binomial | 2 824 | 0.236 | 0.170 | fail |
| 2022 | King — normale tronquée | 2 592 | 0.491 | 0.461 | fail |
| 2022 | KRT — King99 bêta-binomial | 2 592 | 0.492 | 0.464 | fail |

### H1 — Vote à gauche — ouvriers et employés vs autres CSP

Dénominateur : **suffrages exprimés**. Écart descriptif de la coupe 2022 à la coupe 1962 sur la moyenne communale : β₁ : King -0.232, KRT -0.120 ; β₂ : King +0.060, KRT -0.075. Ces écarts ne sont ni une trajectoire continue ni un effet causal. Les deux modèles utilisent l’intersection exacte au palier demandé n=3 000 pour les trois dates. Tous les points restent des calibrations PyEI 20/20/1 avec diagnostic `fail`.

![Comparaison canonique 1962–1986–2022 — H1](../figures/professor_recap/comparison_interannuelle__H1.svg)

| Année | Modèle | Communes | β₁ ouvriers + employés | β₂ agriculteurs + indépendants + cadres + professions intermédiaires | Diagnostic |
| --- | --- | --- | --- | --- | --- |
| 1962 | King — normale tronquée | 2 925 | 0.558 | 0.257 | fail |
| 1962 | KRT — King99 bêta-binomial | 2 925 | 0.393 | 0.389 | fail |
| 1986 | King — normale tronquée | 2 935 | 0.414 | 0.456 | fail |
| 1986 | KRT — King99 bêta-binomial | 2 935 | 0.450 | 0.415 | fail |
| 2022 | King — normale tronquée | 2 813 | 0.326 | 0.317 | fail |
| 2022 | KRT — King99 bêta-binomial | 2 813 | 0.273 | 0.314 | fail |

### H2 — Vote à gauche — ouvriers vs autres CSP

Dénominateur : **suffrages exprimés**. Écart descriptif de la coupe 2022 à la coupe 1962 sur la moyenne communale : β₁ : King +0.105, KRT -0.122 ; β₂ : King -0.140, KRT -0.078. Ces écarts ne sont ni une trajectoire continue ni un effet causal. Les deux modèles utilisent l’intersection exacte au palier demandé n=3 000 pour les trois dates. Tous les points restent des calibrations PyEI 20/20/1 avec diagnostic `fail`.

![Comparaison canonique 1962–1986–2022 — H2](../figures/professor_recap/comparison_interannuelle__H2.svg)

| Année | Modèle | Communes | β₁ ouvriers | β₂ agriculteurs + indépendants + cadres + professions intermédiaires + employés | Diagnostic |
| --- | --- | --- | --- | --- | --- |
| 1962 | King — normale tronquée | 2 924 | 0.502 | 0.331 | fail |
| 1962 | KRT — King99 bêta-binomial | 2 924 | 0.416 | 0.374 | fail |
| 1986 | King — normale tronquée | 2 907 | 0.494 | 0.404 | fail |
| 1986 | KRT — King99 bêta-binomial | 2 907 | 0.450 | 0.423 | fail |
| 2022 | King — normale tronquée | 2 488 | 0.607 | 0.191 | fail |
| 2022 | KRT — King99 bêta-binomial | 2 488 | 0.293 | 0.295 | fail |

### H3 — Vote à gauche — employés vs autres CSP

Dénominateur : **suffrages exprimés**. Écart descriptif de la coupe 2022 à la coupe 1962 sur la moyenne communale : β₁ : King -0.093, KRT -0.074 ; β₂ : King -0.119, KRT -0.102. Ces écarts ne sont ni une trajectoire continue ni un effet causal. Les deux modèles utilisent l’intersection exacte au palier demandé n=3 000 pour les trois dates. Tous les points restent des calibrations PyEI 20/20/1 avec diagnostic `fail`.

![Comparaison canonique 1962–1986–2022 — H3](../figures/professor_recap/comparison_interannuelle__H3.svg)

| Année | Modèle | Communes | β₁ employés | β₂ agriculteurs + indépendants + cadres + professions intermédiaires + ouvriers | Diagnostic |
| --- | --- | --- | --- | --- | --- |
| 1962 | King — normale tronquée | 2 767 | 0.516 | 0.376 | fail |
| 1962 | KRT — King99 bêta-binomial | 2 767 | 0.380 | 0.391 | fail |
| 1986 | King — normale tronquée | 2 828 | 0.509 | 0.415 | fail |
| 1986 | KRT — King99 bêta-binomial | 2 828 | 0.471 | 0.424 | fail |
| 2022 | King — normale tronquée | 2 585 | 0.423 | 0.258 | fail |
| 2022 | KRT — King99 bêta-binomial | 2 585 | 0.306 | 0.288 | fail |

### H4 — Vote à droite — agriculteurs et indépendants vs salariés

Dénominateur : **suffrages exprimés**. Écart descriptif de la coupe 2022 à la coupe 1962 sur la moyenne communale : β₁ : King +0.108, KRT -0.101 ; β₂ : King -0.330, KRT -0.187. Ces écarts ne sont ni une trajectoire continue ni un effet causal. Les deux modèles utilisent l’intersection exacte au palier demandé n=3 000 pour les trois dates. Tous les points restent des calibrations PyEI 20/20/1 avec diagnostic `fail`.

![Comparaison canonique 1962–1986–2022 — H4](../figures/professor_recap/comparison_interannuelle__H4.svg)

| Année | Modèle | Communes | β₁ agriculteurs + indépendants | β₂ cadres + professions intermédiaires + employés + ouvriers | Diagnostic |
| --- | --- | --- | --- | --- | --- |
| 1962 | King — normale tronquée | 2 925 | 0.393 | 0.782 | fail |
| 1962 | KRT — King99 bêta-binomial | 2 925 | 0.563 | 0.643 | fail |
| 1986 | King — normale tronquée | 2 920 | 0.551 | 0.573 | fail |
| 1986 | KRT — King99 bêta-binomial | 2 920 | 0.596 | 0.553 | fail |
| 2022 | King — normale tronquée | 2 477 | 0.501 | 0.452 | fail |
| 2022 | KRT — King99 bêta-binomial | 2 477 | 0.463 | 0.456 | fail |

### H5 — Vote au centre — cadres vs autres CSP

Dénominateur : **suffrages exprimés**. Écart descriptif de la coupe 2022 à la coupe 1962 sur la moyenne communale : β₁ : KRT +0.090 ; β₂ : KRT +0.200. Ces écarts ne sont ni une trajectoire continue ni un effet causal. H5 n’est pas strictement comparable : King est inapplicable en 1962 et la vue commune 2022 reste à 15 communes. Tous les points restent des calibrations PyEI 20/20/1 avec diagnostic `fail`.

![Comparaison canonique 1962–1986–2022 — H5](../figures/professor_recap/comparison_interannuelle__H5.svg)

| Année | Modèle | Communes | β₁ cadres | β₂ agriculteurs + indépendants + professions intermédiaires + employés + ouvriers | Diagnostic |
| --- | --- | --- | --- | --- | --- |
| 1962 | KRT — King99 bêta-binomial | 2 985 | 0.180 | 0.005 | fail |
| 1986 | King — normale tronquée | 687 | 0.055 | 0.003 | fail |
| 1986 | KRT — King99 bêta-binomial | 687 | 0.159 | 0.004 | fail |
| 2022 | King — normale tronquée | 15 | 0.607 | 0.135 | fail |
| 2022 | KRT — King99 bêta-binomial | 15 | 0.270 | 0.205 | fail |

## Périmètre, groupes et dénominateurs

H0A/H0B/H0C étudient l’abstention sur les **inscrits**, avec `abstention = inscrits − votants`. H1–H7 et RXC1/RXC2 utilisent les **suffrages exprimés**. H6/H7 ne sont pas définis en 1962, faute de bloc FN/RN explicitement enregistré à cette date.

| Scénario | Vote cible | Groupe cible | Complément | Dénominateur | Périodes pilotes |
| --- | --- | --- | --- | --- | --- |
| H0A | abstention | ouvriers + employés | agriculteurs + indépendants + cadres + professions intermédiaires | inscrits | 1962/1986/2022 |
| H0B | abstention | ouvriers | agriculteurs + indépendants + cadres + professions intermédiaires + employés | inscrits | 1962/1986/2022 |
| H0C | abstention | employés | agriculteurs + indépendants + cadres + professions intermédiaires + ouvriers | inscrits | 1962/1986/2022 |
| H1 | gauche | ouvriers + employés | agriculteurs + indépendants + cadres + professions intermédiaires | suffrages exprimés | 1962/1986/2022 |
| H2 | gauche | ouvriers | agriculteurs + indépendants + cadres + professions intermédiaires + employés | suffrages exprimés | 1962/1986/2022 |
| H3 | gauche | employés | agriculteurs + indépendants + cadres + professions intermédiaires + ouvriers | suffrages exprimés | 1962/1986/2022 |
| H4 | droite | agriculteurs + indépendants | cadres + professions intermédiaires + employés + ouvriers | suffrages exprimés | 1962/1986/2022 |
| H5 | centre | cadres | agriculteurs + indépendants + professions intermédiaires + employés + ouvriers | suffrages exprimés | 1962/1986/2022 |
| H6 | fn_rn | ouvriers | agriculteurs + indépendants + cadres + professions intermédiaires + employés | suffrages exprimés | 1986/2022 |
| H7 | fn_rn | employés | agriculteurs + indépendants + cadres + professions intermédiaires + ouvriers | suffrages exprimés | 1986/2022 |
| RXC1 | 5 blocs politiques | 3 groupes sociaux | — | suffrages exprimés | 1962/1986/2022 |
| RXC2 | 5 blocs politiques | 6 CSP | — | suffrages exprimés | 1962/1986/2022 |

Le panel principal est un tirage fixe de 3 000 communes dans l’univers 2022. Les communes historiquement absentes ne sont ni imputées ni remplacées. Les effectifs affichés dans les figures sont donc les effectifs réellement comparables après filtres.

## Exemples commentés de chaque famille graphique

### 1. Balance du panel — distribution

Cette figure vérifie que la taille du corps électoral du panel ne s’écarte pas fortement de l’univers 2022. Elle documente la sélection du panel ; elle ne mesure aucun comportement électoral.

![Exemple de balance — log1p inscrits](../figures/panel_balance/continuous__log1p_inscrits.svg)

### 2. Densité principale — comparaison de distributions

La vue principale superpose King et KRT sur l’intersection exacte des communes. Chaque commune compte une fois ; la courbe porte sur les moyennes postérieures communales, pas sur l’empilement des draws.

![Exemple de densité principale — H4 2022](../figures/densities/curated/density_overlay__leg_2022_r1__H4__n3000.svg)

### 3. Densité marginale — un modèle à la fois

Cette variante sépare les distributions de b₁ et b₂ pour un modèle donné. Elle sert à contrôler la forme propre à King avant la comparaison entre modèles.

![Exemple de densité marginale — H4 King 2022](../figures/densities/marginal/leg_2022_r1__H4__king_truncated_normal__common__n3000.svg)

### 4. Relation jointe — b₁ contre b₂

Le nuage communal examine la relation entre les deux probabilités latentes estimées. Avec plusieurs milliers de communes, le scatter est suffisamment dense pour montrer dispersion, concentration et valeurs extrêmes.

![Exemple de relation jointe — H4 King 2022](../figures/densities/joint/leg_2022_r1__H4__king_truncated_normal__common__n3000.svg)

### 5. Comparaison exacte King/KRT — même population

Cette figure impose les mêmes identifiants communaux aux deux modèles. Elle répond à une question de sensibilité au modèle ; une divergence visible ne doit pas être attribuée à une différence de composition communale.

![Exemple d’intersection King/KRT — H4 2022](../figures/densities/comparisons/leg_2022_r1__H4__king_vs_krt__n3000__ed8fe0f95b02.svg)

### 6. Vue longitudinale disponible — écart entre groupes

Les figures longitudinales couvrent les runs disponibles par type d’élection. Elles servent à repérer les scénarios et périodes calculés ; les lignes ne transforment pas les calibrations en série de production.

![Exemple longitudinal — H1 King, législatives](../figures/longitudinal/gap__H1__king_truncated_normal__legislative.svg)

### 7. Diagnostic NLS 2022 — matrice groupe × vote

La matrice RXC2 traduit directement les coefficients softmax en probabilités par CSP et bloc politique. Elle se lit avec la qualité d’ajustement observé–prédit et le diagnostic de rang, pas isolément.

![Exemple NLS — matrice RXC2 2022](../figures/election_2022/nls_probability_matrix__RXC2.svg)

### 8. Comparaison interannuelle — points et dispersion

Le dot-and-interval est le format canonique pour trois dates discrètes : moyenne communale au point, P25–P75 entre communes sur la barre, King et KRT distingués par couleur et forme.

![Exemple interannuel — H0A](../figures/professor_recap/comparison_interannuelle__H0A.svg)

## Inventaire global des sorties analytiques

| Sortie | Lignes | Rôle |
| --- | --- | --- |
| longitudinal_estimates | 1706 | estimations agrégées avec clés et diagnostic |
| model_diagnostics | 385 | convergence, rang, ESS/R-hat/divergences et erreurs |
| commune_latent_summaries | 337327 | résumés communaux larges b₁/b₂ |
| commune_beta_estimates | 674654 | format long des bêtas, quantiles et groupes |
| beta_trace_index | 370 | index SHA-256 des traces NetCDF |
| beta_density_data | 577272 | points reproductibles des densités |
| density_marginal_data | 577272 | vues marginales natives et communes |
| density_joint_data | 634687 | vues jointes et intersections King/KRT |
| nls_coefficients | 172 | coefficients NLS RXC et robustesses |
| nls_start_diagnostics | 240 | audit des 20 départs déterministes |
| excluded_units | 23012 | communes exclues, étape et raison |
| run_registry | 960 | runs exécutés et combinaisons planifiées |
| all_elections_partition_integrity | 292 | 292 partitions admissibles auditées |
| pilot_model_coverage | 56 | 56 couples modèle–scénario explicitement suivis |
| pilot_density_selection | 55 | runs alimentant 28 densités principales |
| professor_canonical_comparisons | 94 | valeurs exactes des 8 comparaisons à trois périodes |
| validation_checks | 60 | contrôles machine-lisibles de livraison |

Les tables volumineuses existent en Parquet pour l’efficacité et, lorsque nécessaire, en CSV pour inspection. Les runs physiques restent immuables dans `outputs/runs/`; le registre relie chaque `run_id`, `run_key`, configuration, empreinte d’entrée et statut.

## Méthode et correspondance avec le code

Pour la commune i, le modèle 2×2 vérifie `yᵢ = xᵢβ₁ᵢ + (1−xᵢ)β₂ᵢ`. Les tirages b₁/b₂ sont lus directement dans les traces, résumés commune par commune, puis comparés sur l’intersection exacte des identifiants King/KRT. Les densités principales donnent le même poids à chaque commune.

- registre des scénarios et dénominateurs : `code_longitudinal/spec_registry.py` ;
- validation et fermeture des partitions : `prepare_inputs.py` ;
- King/KRT, traces et extraction communale : `run_2x2_batch.py` ;
- table longue des bêtas et index NetCDF : `beta_outputs.py` ;
- intersections et densités : `extract_latent_densities.py` ;
- NLS multi-départs et sandwich : `nls.py` ;
- comparaisons canoniques : `build_illustrated_report.py` et `build_professor_global_recap.py` ;
- contrôles de livraison : `validate_outputs.py`.

La correspondance formelle détaillée et les repères de ligne sont dans [`METHODOLOGY_CODE_MAP.md`](METHODOLOGY_CODE_MAP.md). Le catalogue de toutes les figures est [`FIGURE_CATALOG.md`](FIGURE_CATALOG.md).

## Contrôles, limites et robustesse

- Les tests automatisés couvrent panel, identifiants, partitions, extraction b₁/b₂, intersection exacte, bornes [0,1], NLS, reprise et déterminisme.
- Les 240 partitions 2×2 admissibles passent. Parmi 52 partitions RXC, 30 passent et 22 sont refusées parce que l’écart brut dépasse 0,01 voix ; aucune fermeture forcée ne les masque.
- Les diagnostics PyEI restent `fail` pour interprétation substantielle : une chaîne et 20 draws ne permettent ni R-hat inter-chaînes ni ESS de production.
- Les barres P25–P75 mesurent l’hétérogénéité entre communes, pas l’incertitude d’un changement temporel.
- Le panel rétrospectif est défini dans l’univers 2022 : il décrit un suivi de survivants communaux.
- L’inférence écologique relie des marges agrégées sous hypothèses de modèle ; elle n’observe pas les choix individuels et n’établit pas de causalité.

## Suite recommandée pour un résultat professoral substantiel

1. Produire d’abord H0A, H1 et un sous-ensemble discriminant H0B/H2/H4 en `4 chaînes × 1 000 draws`, avec 1 000 tune et `target_accept=0,99`.
2. N’étendre la production aux 26 scrutins qu’après diagnostics R-hat, ESS et divergences satisfaisants sur ces comparaisons canoniques.
3. Présenter séparément législatives et présidentielles, puis ajouter les robustesses une covariable à la fois.
4. Ne pas utiliser H5-1962, H5-2022 ou H7-1986 pour une conclusion temporelle sans résoudre leurs limites structurelles ou de taille commune.

## Questions encore ouvertes

- Les directions visibles survivent-elles au passage `4 × 1 000` et à une ESS suffisante ?
- Les écarts King/KRT diminuent-ils avec davantage de draws ou révèlent-ils une sensibilité structurelle au modèle ?
- Les comparaisons restent-elles stables en pondérant par les effectifs sociaux ?
- Quelle part des différences temporelles tient aux absences historiques du panel fixé en 2022 ?
