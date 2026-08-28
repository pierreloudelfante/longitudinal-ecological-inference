# Formalisme statistique et correspondance avec le code

Ce document relie les objets conceptuels, les équations et leur réalisation algorithmique. Les numéros de ligne correspondent à la livraison `release_01` ; les noms de fonctions constituent les repères les plus stables.

## 1. Notation et panel longitudinal

Soit \(U_{2022}\) l'univers communal admissible en 2022 et \(S_{3000}\subset U_{2022}\) le panel principal. Le pilote est un sous-ensemble emboîté \(S_{2000}\subset S_{3000}\). Pour une élection \(e\), le panel effectivement observable est

\[
S_e=\{i\in S_{3000}: i\text{ est présent et possède des marges valides à }e\}.
\]

Une commune absente à une date n'est jamais remplacée. Cette convention sépare la composition fixe du panel de la disponibilité historique.

| Objet formel | Traduction algorithmique | Code |
|---|---|---|
| \(U_{2022}\) | jointure électorale/CSP/VBBM, filtres de validité | `code_longitudinal/data_io.py:169-203`, `load_reference_universe` |
| \(S_{3000}\) | permutation sans remise, 3 000 premiers rangs | `code_longitudinal/build_panel.py:55-103`, `build_panel` |
| \(S_{2000}\subset S_{3000}\) | 2 000 premiers rangs du même tirage, balance contrôlée conjointement | `code_longitudinal/build_panel.py:80-88,111-113`, `build_panel` |
| présence \(i\in S_e\) | table commune × élection, sans remplacement | `code_longitudinal/build_panel.py`, `panel_election_presence.csv` |
| identifiant stable | normalisation INSEE et traitement PLM | `code_longitudinal/utils.py:25-59` |

Les règles de balance sont détaillées dans `docs/BALANCE_TESTS.md` et réalisées dans `code_longitudinal/balance_checks.py:10-88`.

## 2. Fermeture des marges

Pour la commune \(i\), soient \(N_i\) le dénominateur électoral et \(a_{ir}\geq0\) les six effectifs CSP bruts. Les comptes sociaux cibles sont d'abord recalés proportionnellement :

\[
\widetilde n_{ir}=N_i\frac{a_{ir}}{\sum_s a_{is}}.
\]

Comme les modèles requièrent des comptes entiers fermant exactement sur \(N_i\), l'algorithme des plus forts restes pose

\[
n_{ir}=\lfloor\widetilde n_{ir}\rfloor + I\{r\text{ reçoit l'un des plus grands restes}\},
\qquad \sum_r n_{ir}=N_i.
\]

Les égalités politiques sont d'abord contrôlées sur les données brutes avec une tolérance absolue de 0,01 voix, puis fermées exactement par la même méthode. Une différence supérieure entraîne l'échec explicite de la préparation.

| Opération | Code |
|---|---|
| plus forts restes déterministes | `code_longitudinal/utils.py:62-88`, `largest_remainder` |
| validation brute adaptée à H0/H1–H7/RXC | `code_longitudinal/prepare_inputs.py:67`, `_validate_raw_political_partition` |
| construction des blocs politiques | `code_longitudinal/prepare_inputs.py:153`, `_vote_values` |
| recalage des marges sociales | `code_longitudinal/prepare_inputs.py:178`, `_social_values` |
| validation et fermeture exacte | `code_longitudinal/prepare_inputs.py:183`, `validate_model_ready` |
| parcours des 292 couples admissibles | `code_longitudinal/prepare_all_partitions.py`, `prepare_all_partitions` |

## 3. Modèles 2 × 2 et bêta communaux

Pour une commune \(i\), \(x_i\) est la part du groupe social 1 et \(y_i\) la part du résultat politique 1. L'identité comptable de l'inférence écologique est

\[
y_i=x_i\beta_{1i}+(1-x_i)\beta_{2i},
\]

où \(\beta_{1i}\) et \(\beta_{2i}\) sont les probabilités communales latentes de produire le résultat 1 dans chacun des deux groupes sociaux. Elles sont contraintes à \([0,1]\), mais ne sont pas observées individuellement.

Le modèle `king_truncated_normal` appelle PyEI `truncated_normal`; `krt_beta_binomial` appelle PyEI `king99`. Les deux reçoivent les mêmes entrées et le même ordre de communes pour une comparaison donnée.

Les traces NetCDF conservent les tirages postérieurs. Pour chaque commune et chaque bêta, on extrait directement de `b_1` et `b_2` : moyenne, écart-type, quantiles 2,5 %, 5 %, 25 %, 50 %, 75 %, 95 % et 97,5 %. La table longue correspondante est `outputs/commune_beta_estimates.{csv,parquet}` et l'index des traces est `outputs/beta_trace_index.csv`.

| Opération | Code |
|---|---|
| appel des modèles PyEI | `code_longitudinal/run_2x2_batch.py` |
| extraction directe de `b_1`/`b_2` | `code_longitudinal/run_2x2_batch.py:133-171` |
| table bêta longue et index des traces | `code_longitudinal/beta_outputs.py:42-116` |
| diagnostic MCMC | `code_longitudinal/run_2x2_batch.py:101-130` |

### Densité des estimations communales

Pour un bêta donné, la densité principale porte sur les moyennes postérieures communales \(\widehat\beta_i=E(\beta_i\mid\text{marges})\). Sa mesure empirique non pondérée est

\[
\widehat F(b)=\frac1{|S_e|}\sum_{i\in S_e}I(\widehat\beta_i\le b).
\]

Chaque commune compte donc une fois. Une variante pondérée par la population sociale est aussi exportée, mais elle répond à une autre question descriptive. Les données de densité sont dans `outputs/beta_density_data.{csv,parquet}` ; leur construction KDE, avec repli histogramme lorsque nécessaire, est dans `code_longitudinal/extract_latent_densities.py:35-51,123-203`.

King et KRT sont présentés :

- dans leur vue native, avec toutes les communes propres à chaque ajustement ;
- sur l'intersection exacte \(S_e^{King}\cap S_e^{KRT}\), afin que l'écart de modèle ne soit pas confondu avec un écart de composition.

La construction de cette intersection est dans
`code_longitudinal/extract_latent_densities.py:91`, `_with_scopes`. Le choix du
plus grand palier commun pour les figures est séparé et explicite à la ligne
216, `_select_largest_plot_views`.

### Comparaison interannuelle des mêmes hypothèses

Le rapport 1962/1986/2022 ne relie pas les dates par une trajectoire supposée.
Pour le modèle `m`, l'hypothèse `h`, le groupe `g` et l'année `t`, il
trace la moyenne à poids communal égal :

\[
\bar\beta_{gthm}=\frac{1}{|I_{th}|}\sum_{i\in I_{th}}\widehat\beta_{igthm},
\]

avec `I[t,h] = S[t,h,King] ∩ S[t,h,KRT]` lorsqu'une vue commune existe.
P25–P75 résume la dispersion des moyennes postérieures entre communes ; ce
n'est pas un intervalle de crédibilité.

| Objet formel | Traduction algorithmique | Code |
|---|---|---|
| `I[t,h]` exact | comparaison des ensembles d'identifiants King/KRT et échec explicite s'ils diffèrent | `code_longitudinal/build_illustrated_report.py:75-135`, `build_comparison_table` |
| `β̂[i,g]` | lecture de `b1_mean`/`b2_mean`, bornes `[0,1]` et une ligne par commune | `code_longitudinal/build_illustrated_report.py:137-183` |
| `β̄[g,t,h,m]` | moyenne non pondérée ; moyenne pondérée sociale conservée séparément | `code_longitudinal/build_illustrated_report.py:184-218` |
| P25, médiane, P75 | quantiles entre communes, stockés avec l'écart-type | `code_longitudinal/build_illustrated_report.py:202-211` |
| dates discrètes | deux panneaux β₁/β₂, points non reliés, échelle probabiliste commune | `code_longitudinal/build_illustrated_report.py:236-382`, `plot_interannual_comparisons` |
| rapport analytique auditable | tables exactes, 18 références SVG, limites et provenance | `code_longitudinal/build_illustrated_report.py:509-650` |
| sélection H0A–H5 | ordre fermé des huit scénarios canoniques, sans inclure H6/H7 non définis en 1962 | `code_longitudinal/build_professor_global_recap.py:17-20` |
| variations 2022−1962 | différence descriptive des moyennes communales, séparée par β et modèle | `code_longitudinal/build_professor_global_recap.py:54-74` |
| inventaire global | comptage des tables consolidées et explicitation de leur rôle | `code_longitudinal/build_professor_global_recap.py:133-153` |
| rapport professeur | assemblage de 8 comparaisons, 8 exemples, méthodes, limites et questions ouvertes | `code_longitudinal/build_professor_global_recap.py:163-284` |

La table résultante est `outputs/illustrated_report_estimates.csv`. Les deux
tests dédiés vérifient la moyenne communale, les huit scénarios et le rejet d'une fausse
intersection dans `tests/test_illustrated_report.py`.

## 4. Modèle \(R\times C\) NLS

Soient \(x_{ir}\) la part observée du groupe social \(r\) dans la commune \(i\), \(t_{ic}\) la part observée du vote \(c\), et \(\pi_{irc}\) la probabilité latente de ce vote pour ce groupe. Sans covariable, les paramètres ne varient pas entre communes :

\[
\pi_{rc}=\frac{\exp(\eta_{rc})}{1+\sum_{d=1}^{C-1}\exp(\eta_{rd})},\quad c<C,
\qquad
\pi_{rC}=\frac{1}{1+\sum_{d=1}^{C-1}\exp(\eta_{rd})}.
\]

La dernière catégorie politique est la référence. Les marges prédites sont

\[
\widehat t_{ic}=\sum_{r=1}^{R}x_{ir}\pi_{rc}.
\]

L'objectif non pondéré évite la redondance de la dernière colonne :

\[
SSE(\eta)=\sum_i\sum_{c=1}^{C-1}(t_{ic}-\widehat t_{ic})^2.
\]

Il est minimisé avec `least_squares(method="trf", loss="linear")`, 5 000 évaluations au plus et des tolérances `1e-9`. Vingt départs sont employés : un départ construit lorsque possible, le vecteur nul et 18 perturbations pseudo-aléatoires déterministes. Le meilleur coût convergé est retenu et tous les départs restent audités.

| Élément formel | Code |
|---|---|
| softmax et catégorie de référence | `code_longitudinal/nls.py:35-48` |
| résidus sur \(C-1\), SSE non pondérée | `code_longitudinal/nls.py:51-58` |
| 20 départs et optimisation | `code_longitudinal/nls.py:105-160` |
| sandwich, rang et conditionnement | `code_longitudinal/nls.py:163-204` |
| agrégat pondéré par les effectifs sociaux | `code_longitudinal/nls.py:207-210` |

Les coefficients et les diagnostics par départ sont respectivement dans `outputs/nls_coefficients.csv` et `outputs/nls_start_diagnostics.csv`. Aucun intervalle agrégé NLS n'est présenté comme validé tant qu'une méthode d'incertitude adéquate n'est pas établie.

### Contrôle observé-prédit sur les législatives 2022

Après estimation, le code reconstruit pour chacune des 3 000 communes et chaque
bloc politique :

\[
\widehat t_{ic}=\sum_r x_{ir}\widehat\pi_{rc},\qquad
RMSE_c=\sqrt{\frac1n\sum_i(\widehat t_{ic}-t_{ic})^2},\qquad
MAE_c=\frac1n\sum_i|\widehat t_{ic}-t_{ic}|.
\]

| Objet formel | Traduction algorithmique | Code |
|---|---|---|
| \(\widehat\pi_{rc}\) | pivot de l'estimation consolidée vers une matrice groupe × vote ordonnée par le registre | `code_longitudinal/plot_election_2022.py:55-63`, `_probability_matrix` |
| \(\widehat t=X\widehat\pi\) | produit matriciel des parts sociales communales et des probabilités estimées | `code_longitudinal/plot_election_2022.py:97-121`, `_fit_quality` |
| RMSE/MAE | résumé des résidus communaux, une commune par ligne | `code_longitudinal/plot_election_2022.py:103-120` |
| fermeture des dix entrées 2×2 | sommes des comptes sociaux et politiques comparées exactement à `N_g` | `code_longitudinal/plot_election_2022.py:143-184`, `_plot_input_margins` |
| critères de livraison 2022 | contrôles des 3 000 clés, matrices RXC, métriques, figures et couverture PyEI | `code_longitudinal/validate_outputs.py:253-362`, `_validate_2022_snapshot` |

Ces diagnostics vérifient l'algorithme et la capacité du modèle à reconstruire
les marges agrégées. Ils ne fournissent pas de validation individuelle externe,
car les tableaux individuels groupe × vote ne sont pas observés.

## 5. Diagnostics et statut substantiel

Pour les modèles MCMC, un avertissement est produit dès une divergence, un \(\widehat R>1{,}01\) ou une ESS inférieure à 400. Le résultat échoue substantiellement si les divergences dépassent 5 %, si \(\widehat R>1{,}10\), si l'ESS est inférieure à 100, si la postérieure contient des valeurs non finies ou si l'ajustement lève une exception.

Un petit palier de calibration peut être techniquement réussi tout en restant non substantiel. Les figures conservent ce statut ; l'existence d'une courbe ne constitue donc pas à elle seule une validation.

Avant chaque nouveau palier PyEI, le pipeline estime la durée et la mémoire. Il
ne poursuit que si chaque ajustement projeté reste sous 12 heures et 80 % de la
mémoire disponible. Si des ajustements comparables existent pour le même modèle,
les mêmes draws/tune/chaînes et une taille au moins égale à la taille demandée,
la projection est

\[
\widehat M(n')=1{,}10\max_{j:\,m_j=m,\,n_j\ge n'} M_j.
\]

Cette enveloppe incorpore une marge de sécurité de 10 % sans contourner le
plafond. En l'absence de comparable, le repli est
\(\widehat M(n')=M(n)n'/n\). La décision pré-run est dans
`code_longitudinal/run_2x2_batch.py:260` (`_preflight_ladder_gate`) et le repli
dans `run_2x2_batch.py:655` (`next_ladder_gate`) ; les paramètres sont dans
`config/run_settings.json`. Chaque mesure est isolée par
`run_pilot_ladder.py:41` (`_run_isolated_fit`) et la reprise ciblée est dans
`run_pilot_ladder.py:203` (`retry_extension_resource_limited`).

## 6. Reproductibilité, reprise et consolidation

Une configuration statistique et les empreintes de ses entrées déterminent un `run_key`. Chaque exécution reçoit aussi un `run_id` horodaté. Un succès existant est repris sans écrasement ; les répertoires immuables permettent d'auditer les essais antérieurs. La sélection du dernier succès pertinent et le calcul de la clé sont dans `code_longitudinal/run_registry.py:54-109`.

La consolidation ne mélange pas silencieusement les exécutions : elle choisit un succès par configuration, conserve les clés complètes et produit les tables contractuelles via `code_longitudinal/build_outputs.py:102-151`. Le point d'entrée des stages est `code_longitudinal/run_pipeline.py:53-158`.

## 7. Contrôles automatisés

Les vérifications couvrent notamment l'emboîtement des panels, les identifiants, la présence historique, les partitions, l'extraction des bêta, les intersections de modèles, les bornes probabilistes, le NLS et l'immutabilité des runs. Les validations de panel et de données prêtes pour modèle sont réalisées dans `code_longitudinal/validate_outputs.py:73-113`. Les tests exécutables se trouvent dans `tests/`.

## 8. Limite d'interprétation

Les \(\beta\) sont des quantités latentes compatibles avec les marges et les hypothèses du modèle. Elles ne sont pas des comportements individuels observés. Toute conclusion individuelle directe à partir des associations agrégées exposerait à l'erreur écologique. Les résultats MCMC de petit palier ou dont le diagnostic est `warning`/`fail` ne doivent pas être utilisés comme estimations de production.
