# Méthodologie, choix sensibles et règles d’interprétation — production KRT 3 000 communes

## Résumé méthodologique

Le travail estime, pour 1962, 1986 et 2022, deux tableaux écologiques 2×2 opposant les ouvriers et employés aux autres catégories socioprofessionnelles. H0A porte sur l’abstention parmi les inscrits ; H1 porte sur le vote à gauche parmi les suffrages exprimés. Les six fits utilisent le même panel de 3 000 communes et le modèle bayésien KRT/King99 implémenté par PyEI.

La chaîne complète est :

```text
archives électorales et CSP
  → harmonisation des communes dans la géographie de référence 2022
  → intersection admissible aux trois dates
  → tirage sans remise et porte d’équilibre
  → gel du panel et de son SHA-256
  → reconstruction des marges 2×2 pour chaque hypothèse
  → six MCMC KRT indépendantes
  → diagnostic MCMC publié sur les β communaux
  → agrégation draw-wise avec poids propres aux groupes
  → contrastes intra-période et comparaisons inter-périodes
  → diagnostic d’identification écologique séparé
  → densités communales, rapport et archive
```

Cette méthode permet une comparaison communale stable entre périodes, mais elle ne transforme pas des marges agrégées en observations individuelles. L’erreur écologique reste la limite conceptuelle centrale.

## Unités, groupes et dénominateurs

L’unité d’observation du modèle est la commune harmonisée. Pour la commune `i` :

- `xᵢ` est la fraction reconstruite d’ouvriers et employés ;
- `1−xᵢ` est la fraction des autres CSP ;
- `yᵢ` est la fraction observée de l’événement politique ;
- `Nᵢ` est le dénominateur électoral du scénario ;
- `β₁ᵢ` et `β₂ᵢ` sont les probabilités latentes de l’événement dans les deux groupes.

| Élément | H0A | H1 |
| --- | --- | --- |
| événement | abstention | vote à gauche (`voteG + voteCG`) |
| groupe 1 | ouvriers + employés | ouvriers + employés |
| groupe 2 | agriculteurs, indépendants, cadres, professions intermédiaires | mêmes autres CSP |
| dénominateur `Nᵢ` | inscrits | suffrages exprimés |
| complément politique | participation | non-gauche |

Les valeurs H0A et H1 ne sont donc pas deux mesures d’un même événement. Une différence de niveau entre elles n’a pas d’interprétation directe.

## Reconstruction des marges sociales et politiques

Les six comptes CSP disponibles ne sont pas directement des effectifs d’inscrits ou d’exprimés. Le pipeline conserve leurs parts relatives, puis les **recalibre au dénominateur électoral** de chaque commune par la méthode du plus fort reste :

1. calcul des effectifs théoriques de chaque groupe à partir des parts CSP ;
2. multiplication par `Nᵢ` ;
3. arrondi par plus fort reste afin que la somme des groupes soit exactement `Nᵢ`.

La même règle ferme la partition politique lorsque les données sources ne sont pas déjà des entiers exactement additifs. Avant arrondi, le pipeline vérifie que la cible politique est comprise dans son dénominateur.

Ce choix garantit des tableaux 2×2 entiers et cohérents, mais repose sur une hypothèse sensible : **la composition CSP observée est supposée applicable au dénominateur électoral**. Pour H1, cela revient notamment à transférer les parts sociales à la population des exprimés, dont la composition sociale réelle n’est pas observée directement.

Les tables `model_ready` doivent ensuite satisfaire :

- 3 000 lignes, sans commune dupliquée ;
- `N1ᵢ + N2ᵢ = Nᵢ` exactement ;
- les deux comptes politiques somment exactement à `Nᵢ` ;
- `xᵢ + (1−xᵢ) = 1` à la tolérance numérique ;
- aucune exclusion silencieuse entre le panel et les entrées finales.

Pour le modèle KRT, les fractions politiques strictement intérieures sont déplacées d’une unité de précision flottante lorsque nécessaire. Ce correctif évite qu’un calcul interne `floor(fraction × N)` perde une voix à cause d’un arrondi binaire ; le compte reconstitué est vérifié après correction.

## Modèle écologique KRT/King99

La relation écologique observée est :

`yᵢ = xᵢ β₁ᵢ + (1−xᵢ) β₂ᵢ`.

Le modèle utilisé par PyEI est :

`c₁, d₁, c₂, d₂ ~ Exponential(λ)` avec `λ = 0,5`

`β₁ᵢ ~ Beta(c₁, d₁)`

`β₂ᵢ ~ Beta(c₂, d₂)`

`Yᵢ ~ Binomial(Nᵢ, xᵢ β₁ᵢ + (1−xᵢ) β₂ᵢ)`.

Les paramètres `c₁`, `d₁`, `c₂` et `d₂` sont des **hyperparamètres de forme** des distributions Beta communales. Ils ne sont ni des communes, ni des chaînes, ni des estimations supplémentaires. Ils ne remplacent pas les métriques des β dans les tableaux et figures. En revanche, un diagnostic moins favorable sur ces paramètres impose la mention `satisfaisant avec réserve`.

Le choix `λ=0,5` correspond au réglage King99 retenu dans `config/run_settings.json`. Il induit un prior sur la forme et l’hétérogénéité des β. Aucune analyse de sensibilité complète à λ ou à une autre famille de priors n’est incluse dans la livraison finale : les résultats sont donc conditionnels à ce choix.

## Paramètres MCMC et justification

| Paramètre | Valeur | Rôle et justification |
| --- | ---: | --- |
| chaînes | 4 | permet R-hat et comparaison entre chaînes |
| chauffe par chaîne | 1 000 | adaptation NUTS et de la métrique |
| draws conservés par chaîne | 1 000 | 4 000 draws postérieurs au total |
| `target_accept` | 0,99 | réduit le risque de divergences dans une géométrie difficile |
| `max_treedepth` | 14 | autorise des trajectoires NUTS plus longues avant saturation |
| `cores` | 1 | chaînes calculées séquentiellement pour limiter la mémoire |
| graine | `20260802` | reproductibilité du tirage et du sampler |

Un `target_accept` élevé améliore souvent la stabilité, mais augmente le temps de calcul et ne garantit pas à lui seul la convergence. De même, l’absence de divergences ne suffit pas : R-hat, ESS, BFMI et profondeur d’arbre sont contrôlés conjointement.

## Diagnostic MCMC centré sur les β avec réserve conservatrice

Pour chaque fit, le statut publié est calculé sur **les 6 000 β communaux** : 3 000 valeurs de `b_1` et 3 000 valeurs de `b_2`. Le R-hat retenu est le plus grand parmi ces β ; les ESS bulk et tail sont les plus faibles. Les divergences, le BFMI et la profondeur d’arbre restent évalués sur le sampler entier.

Le fichier `mcmc_diagnostics_v2.json` de chaque run conserve aussi les métriques des hyperparamètres. Il constitue la trace d’audit complète. Le tableau `canonical_mcmc_diagnostics_3000_v1.csv` et la figure associée affichent les métriques β, puis appliquent la règle de synthèse suivante :

- `satisfaisant` si les β, les hyperparamètres et les contrôles du sampler passent ;
- `satisfaisant avec réserve` si au moins un de ces blocs est `caveat` sans échec ;
- `insuffisant` si au moins un bloc est `fail`.

| Critère | `pass` | `caveat` | `fail` |
| --- | ---: | ---: | ---: |
| R-hat maximal | ≤ 1,01 | (1,01 ; 1,05] | > 1,05 |
| ESS bulk minimal | ≥ 400 | [100 ; 400) | < 100 |
| ESS tail minimal | ≥ 400 | [100 ; 400) | < 100 |
| BFMI minimal | ≥ 0,30 | [0,20 ; 0,30) | < 0,20 |
| divergences | 0 | fraction dans ]0 ; 0,001] | fraction > 0,001 |
| saturation de profondeur | 0 | fraction dans ]0 ; 0,01] | fraction > 0,01 |

Le bilan final est de **2 satisfaisants**, **4 satisfaisants avec réserve** et **0 insuffisant**. H1–1962 est le seul cas où la réserve concerne les β. Pour H0A–1962, H0A–1986 et H1–2022, elle vient uniquement des hyperparamètres. Les six ajustements ont zéro divergence et zéro saturation de profondeur.

Le champ interne `selected_for_interpretation` correspond à une admissibilité automatique stricte. Il reste dans les JSON bruts mais n’est pas publié dans le CSV consolidé. Celui-ci indique à la place si l’ajustement est retenu pour le compte rendu descriptif et les réserves associées.

Les diagnostics des estimands sont calculés séparément sur β₁ agrégé, β₂ agrégé et `β₁−β₂`. Ils sont publiés dans `estimand_mcmc_diagnostics_3000_v1.csv`. Ils décrivent la précision Monte-Carlo des quantités commentées et complètent le diagnostic des paramètres β communaux.

Trois statuts différents ne doivent pas être confondus :

1. `fit_status` : le calcul s’est-il terminé et la trace est-elle sauvegardée ?
2. `mcmc_status` publié : les β, les paramètres hors β et les contrôles du sampler satisfont-ils les seuils numériques ?
3. `identification_status` : les marges écologiques et la variation de composition contraignent-elles suffisamment les β ?

Il y a donc bien **un bilan MCMC publié par estimation**. Les métriques β restent visibles et une faiblesse hors β est traduite par une réserve dans ce même bilan. Le statut d’identification est une autre question méthodologique, pas un diagnostic concurrent.

## Agrégation correcte des β

À chaque draw postérieur `s`, les estimands sont :

`β̄₁(s) = Σᵢ N1ᵢ β₁ᵢ(s) / Σᵢ N1ᵢ`

`β̄₂(s) = Σᵢ N2ᵢ β₂ᵢ(s) / Σᵢ N2ᵢ`.

Le contraste intra-période est ensuite :

`Δₜ(s) = β̄₁,ₜ(s) − β̄₂,ₜ(s)`.

Cette agrégation utilise un dénominateur propre à chaque groupe. L’ancienne variante utilisant un poids commun `N_total` est conservée uniquement dans `aggregate_comparison_v2.csv` comme audit ; elle ne contrôle pas les résultats publiés.

Le calcul draw-wise est important : calculer d’abord une moyenne communale puis ignorer la distribution postérieure sous-estimerait ou déformerait l’incertitude de l’agrégat.

## Comparaisons entre périodes

Les trois élections sont ajustées séparément. Pour comparer deux périodes, le pipeline tire 50 000 paires indépendantes de draws, avec la graine `20260804`, puis calcule la différence des contrastes.

Cette procédure propage l’incertitude de chaque fit, mais elle ne modélise pas :

- une corrélation postérieure entre années ;
- une trajectoire latente propre à chaque commune ;
- des transitions individuelles ;
- des changements de composition sociale non observés entre élections.

Le terme « longitudinal » désigne ici le panel communal commun et la comparaison répétée des périodes, pas un modèle longitudinal individuel ou hiérarchique temporel.

## Densités jointes et marginales

Les figures sont construites à partir des moyennes postérieures communales `b1_mean` et `b2_mean`.

- `equal_communes` : chaque commune compte une fois ;
- `N_total_weighted` : les grandes communes comptent davantage ;
- marginale β₁ : pondération par `N1` ;
- marginale β₂ : pondération par `N2`.

Une matrice de bandwidth commune est utilisée pour 1962, 1986 et 2022 à l’intérieur de chaque hypothèse et pondération. Ce choix évite qu’une date paraisse artificiellement plus lisse qu’une autre. Il ne corrige pas complètement le biais de bord de la KDE sur `[0,1]`, particulièrement visible pour H1–1962.

Les figures et leur audit sont détaillés dans [`COMPARAISON_DENSITES_JOINTES_3_PERIODES.md`](COMPARAISON_DENSITES_JOINTES_3_PERIODES.md).

## Identification écologique séparée

Le diagnostic d’identification mesure notamment :

- la variation de la fraction du groupe 1 entre communes ;
- le rang et le conditionnement du dessin écologique ;
- la largeur des bornes de tomographie pour β₁ et β₂ ;
- la part des communes dont les bornes maximales sont presque non informatives.

Les résultats sont : H0A–1986 `pass`; les cinq autres fits `caveat`, principalement à cause de bornes de tomographie presque non informatives. Ce statut ne modifie pas rétroactivement le diagnostic des chaînes. Il limite la force avec laquelle les β latents peuvent être interprétés comme comportements sociaux individuels.

## Choix sensibles, justification et risque associé

| Choix | Justification opérationnelle | Risque ou limite | Contrôle/sensibilité recommandé |
| --- | --- | --- | --- |
| panel commun aux trois dates | comparabilité exacte des communes | biais de survivance géographique | comparer à des panels spécifiques par date |
| tirage de communes équiprobable | représentation du territoire communal | grandes communes non proportionnelles à leur électorat | répéter avec PPS ou post-stratification |
| porte d’équilibre 2022 | évite un panel manifestement déséquilibré | sélection conditionnelle et équilibre non historique | plusieurs graines acceptées et covariables historiques |
| rescaling CSP vers `Nᵢ` | ferme les marges du tableau 2×2 | composition des inscrits/exprimés supposée | scénarios alternatifs de composition |
| H0A sur inscrits, H1 sur exprimés | cohérence avec l’événement | populations différentes entre hypothèses | ne pas comparer leurs niveaux directement |
| KRT King99, `λ=0,5` | modèle bayésien EI standard du projet | sensibilité aux hyperpriors | grille de λ et priors alternatifs |
| `target_accept=0,99` | géométrie MCMC plus prudente | calcul plus lent, convergence non garantie | conserver l’audit complet R-hat/ESS/BFMI |
| six fits séparés | reprise simple et coût raisonnable | pas de dépendance temporelle modélisée | modèle hiérarchique temporel en extension |
| 50 000 paires indépendantes | comparaison postérieure transparente | ignore une covariance interannuelle potentielle | modèle joint ou bootstrap longitudinal |
| densité des moyennes communales | lecture claire de l’hétérogénéité | incertitude intra-commune comprimée | figures de draws/intervalle pour cas ciblés |
| bandwidth commun | comparaison visuelle honnête | biais de bord et modes sensibles au lissage | bandwidths alternatifs et transformation logit |
| agrégation `N1/N2` draw-wise | estimand social correct | résultat dominé par les effectifs du panel | comparer communes égales et pondérations externes |

## Ce que les résultats permettent de dire

Formulations compatibles avec la méthode :

- « Dans le panel commun et sous le modèle KRT, le contraste écologique estimé est positif/négatif. »
- « La distribution communale se déplace entre 1962, 1986 et 2022. »
- « Le résultat est conditionnel au panel, aux marges reconstruites et aux priors. »
- « Quatre fits nécessitent une réserve MCMC et cinq une réserve d’identification. »

Formulations à éviter :

- « Les ouvriers individuels ont changé de comportement de telle façon. »
- « Le changement est causé par la période ou par une variable sociale. »
- « Le panel représente tous les électeurs français sans réserve. »
- « Un `pass` MCMC prouve l’identification individuelle. »
- « Une masse KDE est un intervalle crédible national. »

## Reproductibilité

Commandes principales :

```powershell
python -m code_longitudinal.build_common_panel_v2 --panel-size 3000 --initial-seed 20260802
python -m code_longitudinal.run_priority_production_v2 --scenario H0A --scenario H1
python -m code_longitudinal.finalize_priority_results_3000 --check-ready
python -m code_longitudinal.finalize_priority_results_3000
```

Fichiers de preuve :

- panel : `panel/panel_3000_common_1962_1986_2022_v2.csv` ;
- manifeste du panel : `panel/panel_3000_common_1962_1986_2022_v2_manifest.json` ;
- équilibre : `panel/panel_3000_common_1962_1986_2022_v2_balance.csv` ;
- entrées : `outputs/model_ready/*H0A*3000*.parquet` et `*H1*3000*.parquet` ;
- traces : `outputs/runs/<run_id>/trace.nc` ;
- diagnostic brut toutes variables : `outputs/runs/<run_id>/mcmc_diagnostics_v2.json` ;
- diagnostic publié des β : `outputs/v2/priority_3000_final/canonical_mcmc_diagnostics_3000_v1.csv` ;
- résultats consolidés : `outputs/v2/priority_3000_final/` ;
- figures : `figures/v2/priority_3000_final/` ;
- manifeste final : `outputs/v2/priority_3000_final/release_manifest_3000_v1.json`.

L’archive compacte destinée à ChatGPT conserve tous les résultats, diagnostics, latents, entrées, figures et documents, mais seulement deux traces NetCDF représentatives afin de rester sous 500 Mo. L’absence des quatre autres traces dans cette copie est une limite de réplication complète, pas une absence d’estimation.

## Vérifications encore prioritaires

1. posterior predictive checks des six fits ;
2. sensibilité à `λ`, aux hyperpriors et à une paramétrisation alternative ;
3. stabilité sur plusieurs panels équilibrés ;
4. évaluation spécifique de H1–1962 ;
5. sensibilité aux règles de reconstruction des marges CSP ;
6. comparaison avec un modèle temporel joint ou un bootstrap de communes ;
7. contrôle de robustesse des densités par transformation logit et bandwidth alternatif.
