# Législatives 2022 à 3 000 communes — calculs, figures et intégrité

## Verdict synthétique

Les douze scénarios autorisés en 2022 ont une entrée modèle distincte sur le
panel fixe demandé : H0A–H0C, H1–H7, RXC1 et RXC2. Les dix partitions 2×2 ont
3 000 identifiants uniques, aucune duplication et une fermeture entière exacte
des marges sociales et politiques. RXC1 et RXC2 ont été estimés par NLS sur les
3 000 communes ; les deux optimisations convergent avec 20 départs sur 20 et un
diagnostic `pass`.

Ce verdict établit l'intégrité comptable et algorithmique des résultats
disponibles. Il ne transforme pas les probabilités écologiques en comportements
individuels observés. Le diagnostic NLS `pass` signifie que l'optimisation et
les contrôles numériques passent ; il ne signifie pas que le modèle sans
covariable prédit parfaitement toutes les marges communales.

<!-- PYEI_PRODUCTION_STATUS_START -->
Il n'existe aucun ajustement PyEI de production validé à 3 000 communes dans
cette livraison. Une tentative King H0A en `4 chaînes × 1 000 draws` a été
interrompue par la mise en veille de la machine puis enregistrée comme échec ;
elle n'est pas présentée comme un résultat.

Les calibrations `20 draws + 20 tune, 1 chaîne` atteignent le palier demandé
3 000 pour King et KRT sur H0A, H1, H6 et H7. Sur H5, King atteint 3 000 mais
KRT reste au palier 25, le palier suivant ayant été bloqué par le seuil de 80 %
de la mémoire disponible. Ces traces et leurs densités testent le pipeline à
grande taille mais tous leurs diagnostics restent `fail` pour un usage
substantiel.
<!-- PYEI_PRODUCTION_STATUS_END -->

## 1. Périmètre réellement préparé

Élection : premier tour des législatives 2022 (`leg_2022_r1`). Échantillon :
`panel_3000_seed_20260802`.

| Famille | Scénarios | Dénominateur | Communes | Total électoral |
|---|---|---|---:|---:|
| abstention 2×2 | H0A, H0B, H0C | inscrits | 3 000 chacune | 3 646 372 |
| vote 2×2 | H1–H7 | exprimés | 3 000 chacune | 1 746 196 |
| vote RXC | RXC1, RXC2 | exprimés | 3 000 chacune | 1 746 196 |

Pour chaque scénario 2×2, la table
`outputs/election_2022_input_integrity.csv` atteste :

- `n_rows = n_unique_units = 3000` ;
- `n_duplicate_units = 0` ;
- `maximum_social_count_gap = 0` voix ;
- `maximum_vote_count_gap = 0` voix ;
- aucun remplacement d'une commune filtrée ou absente.

Les tables sources sont les fichiers
`outputs/model_ready/leg_2022_r1__<SCENARIO>__panel_3000_seed_20260802__n3000.parquet`.
Le recalage des six CSP sur le dénominateur électoral et l'arrondi par plus
forts restes sont donc réalisés avant l'estimation, pas corrigés a posteriori.

## 2. Estimations RXC NLS

### Configuration commune

Pour la commune \(i\), le groupe \(r\) et le bloc \(c\), le modèle sans
covariable pose une probabilité constante par groupe :

\[
\pi_{rc}=\operatorname{softmax}(\eta_{r1},\ldots,\eta_{r,C-1},0)_c,
\qquad
\widehat t_{ic}=\sum_r x_{ir}\pi_{rc}.
\]

La dernière catégorie, `droite`, est la référence. La SSE non pondérée porte
sur les quatre premières catégories. L'optimiseur est
`least_squares(method="trf", loss="linear")`, avec au plus 5 000 évaluations,
tolérances `1e-9` et 20 départs déterministes.

| Scénario | Run | Paramètres | Départs convergés | SSE | Temps |
|---|---|---:|---:|---:|---:|
| RXC1 | `20260802T220413Z__ea57452fd9b7` | 12 | 20/20 | 158,3481 | 3,74 s |
| RXC2 | `20260802T215318Z__eb18ee00138c` | 24 | 20/20 | 157,0379 | 11,38 s |

Les matrices sandwich et d'information ont leur rang complet (12/12 pour RXC1,
24/24 pour RXC2). Les probabilités sont finies, dans `[0,1]`, et somment à un
pour chaque groupe. Aucun intervalle agrégé NLS n'est présenté comme validé.

### RXC1 : trois groupes sociaux

| Groupe | gauche | centre_gauche | centre | centre_droit | droite |
|---|---:|---:|---:|---:|---:|
| ouvriers | 0,225 | 0,050 | 0,221 | 0,192 | 0,312 |
| employés | 0,221 | 0,070 | 0,228 | 0,175 | 0,306 |
| autres CSP | 0,228 | 0,075 | 0,255 | 0,179 | 0,263 |

Les valeurs complètes, non arrondies, restent dans
`outputs/longitudinal_estimates.{csv,parquet}`.

## 3. Ajustement des marges communales

Le contrôle reconstruit les marges par \(\widehat T=X\widehat\Pi\), puis calcule
RMSE, MAE et erreur absolue maximale, séparément pour chaque bloc politique.

| Scénario | Étendue RMSE | Étendue MAE | Erreur absolue maximale observée |
|---|---:|---:|---:|
| RXC1 | 0,096–0,142 | 0,061–0,111 | 0,701 |
| RXC2 | 0,096–0,141 | 0,061–0,110 | 0,711 |

Les moyennes prédites reproduisent les moyennes observées pour chaque bloc,
mais certaines erreurs communales sont importantes. C'est cohérent avec un
modèle sans covariable où les différences entre communes ne passent que par
leur composition sociale. RXC2 réduit légèrement la SSE, sans supprimer cette
limitation. Il serait incorrect de résumer `diagnostic=pass` par « prédiction
communale parfaite ».

La preuve numérique est dans `outputs/election_2022_fit_quality.csv`. Les
figures `nls_observed_vs_predicted` montrent directement la dispersion autour
de la diagonale.

## 4. PyEI 2×2 et bêta communaux

Pour chaque commune, PyEI estime les latents de l'identité :

\[
y_i=x_i\beta_{1i}+(1-x_i)\beta_{2i}.
\]

Les paliers H0A King/KRT 25, 100, 250, 500, 1 000, 2 000 et 3 000 ont été
exécutés pour calibrer temps et mémoire. Au palier demandé 3 000, l'intersection
exacte contient 2 820 communes, King ayant appliqué son filtre de tomographie.
H1, H6 et H7 atteignent aussi un palier commun demandé de 3 000. Ils utilisent
20 draws, 20 tune et une chaîne : ils sont volontairement **non substantiels**,
même lorsque l'appel technique réussit.

Un ajustement de production exige exactement quatre chaînes, 1 000 draws,
1 000 tune et `target_accept=0.99`. Il ne peut être lancé que si la projection
reste sous 12 heures et 80 % de la mémoire disponible. Les petits paliers ne
sont jamais substitués silencieusement à ce standard.

Lorsqu'un run PyEI est achevé, les tirages `b_1` et `b_2` sont conservés dans
`trace.nc`; leurs moyenne, écart-type et quantiles communaux sont exportés dans
`commune_beta_estimates`. Les densités portent sur les moyennes postérieures
entre communes, une commune comptant une fois. Une vue King/KRT comparable
emploie l'intersection exacte des identifiants.

## 5. Figures produites

Le dossier `figures/election_2022/` contient en PNG et SVG :

1. deux matrices annotées groupe × bloc (`RXC1`, `RXC2`) ;
2. deux compositions en barres empilées ;
3. deux diagnostics communaux observé-prédit ;
4. une vue des marges d'entrée des dix hypothèses 2×2.

La quatrième figure est explicitement marquée « ce graphique n'est pas une
estimation écologique ». Les figures de densité restent dans
`figures/densities/` et ne sont générées que pour des traces réellement
présentes.

## 6. Correspondance formalisme ↔ algorithme

| Concept | Réalisation | Code |
|---|---|---|
| registre des 12 scénarios 2022 | groupes, blocs, dénominateurs et modèles autorisés | `code_longitudinal/spec_registry.py`, `SCENARIOS` |
| fermeture sociale et politique | recalage, plus forts restes, validation stricte | `code_longitudinal/prepare_inputs.py`, `validate_model_ready` |
| NLS \(\widehat\Pi\) | softmax, résidus C−1, multi-départs | `code_longitudinal/nls.py`, `fit_nls` |
| reconstruction \(X\widehat\Pi\) | produit matriciel communal | `code_longitudinal/plot_election_2022.py:97-121`, `_fit_quality` |
| métriques et figures | RMSE/MAE, matrices, hexbins | `code_longitudinal/plot_election_2022.py:64-140` |
| audit des dix entrées | unicité et écarts de fermeture | `code_longitudinal/plot_election_2022.py:143-184` |
| critères de livraison | contrôles RXC, figures et couverture PyEI | `code_longitudinal/validate_outputs.py:253-362` |
| bêta et traces | extraction directe `b_1`/`b_2`, NetCDF | `code_longitudinal/run_2x2_batch.py`, `extract_latent_summaries` |

Les repères de fonction sont contractuels ; les numéros de ligne facilitent la
revue de cette version et peuvent évoluer après une modification du fichier.

## 7. Niveaux de validité

| Niveau | Verdict 2022 | Ce qu'il autorise |
|---|---|---|
| panel et balance | validé | utiliser le même échantillon fixe |
| identités comptables | validées sur 12/12 entrées | lancer les modèles sans correction manuelle |
| optimisation RXC | validée sur RXC1 et RXC2 | décrire les probabilités NLS avec leurs limites |
| ajustement des marges | mesuré, imparfait | comparer les résidus et motiver des robustesses |
| MCMC 2×2 de production | voir section d'état PyEI | utiliser seulement les paires dont le diagnostic passe |
| vérité individuelle | non observable ici | aucune conclusion individuelle directe |

Le verdict global est donc « structure et RXC 2022 exploitables avec réserves ;
couverture PyEI à lire scénario par scénario ». La généralisation 1962–2022 ne
doit commencer qu'après acceptation de ce paquet et des limites explicites.
