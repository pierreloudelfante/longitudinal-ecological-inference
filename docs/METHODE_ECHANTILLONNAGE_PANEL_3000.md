# Méthode d’échantillonnage du panel longitudinal commun de 3 000 communes

## Résumé technique

Le panel a été préparé pour les douze entrées prioritaires H0A, H1, H2 et H4 sur 1962, 1986 et 2022. La production finale documentée ici en utilise six : H0A et H1 aux trois dates. Il ne s’agit ni d’un sous-panel de 500 communes, ni d’un tirage stratifié, mais d’un **tirage aléatoire sans remise, conditionné par une porte d’équilibre**, dans un univers de 33 922 communes admissibles aux trois élections.

La graine `20260802` a été acceptée au premier essai. Le panel contient exactement 3 000 identifiants communaux uniques, soit 8,84 % de l’univers commun admissible. Le même ensemble de communes et le même ordre sont réutilisés pour toutes les hypothèses et les trois dates.

## Pourquoi ce plan d’échantillonnage a été retenu

| Choix | Justification | Ce que ce choix ne garantit pas |
| --- | --- | --- |
| mêmes communes aux trois dates | évite qu’un changement de composition du panel soit confondu avec un changement temporel | ne suit pas les mêmes individus |
| tirage sans remise | garantit 3 000 communes distinctes et une probabilité initiale identique dans le cadre admissible | ne donne pas le même poids initial à chaque électeur |
| porte d’équilibre | empêche de retenir un panel manifestement atypique sur les variables contrôlées | ne garantit pas l’équilibre sur toutes les variables, surtout historiques |
| contrôle sur `log(1+inscrits)` | limite l’influence extrême des très grandes communes tout en contrôlant la taille | ne produit pas un tirage proportionnel à la population |
| double référence d’équilibre | compare le panel à l’univers commun et à l’univers communal 2022 | ne corrige pas les communes absentes de l’intersection temporelle |
| graine et SHA-256 figés | rend le panel contrôlable et identique pour tous les fits | ne propage pas l’incertitude entre panels possibles |

Le choix est adapté à une comparaison territoriale écologique. Il ne doit pas être présenté comme un sondage représentatif d’individus. Les agrégats finaux pondèrent ensuite les communes par les effectifs propres aux groupes, mais cette pondération interne au panel n’est pas un poids d’enquête corrigeant l’inclusion dans l’univers national.

## Construction de l’univers admissible

L’unité statistique est la commune harmonisée dans l’univers de référence de 2022. Une commune entre dans le cadre d’échantillonnage seulement si elle est présente dans cet univers et satisfait, pour chacune des élections `leg_1962_r1`, `leg_1986_r1` et `leg_2022_r1`, les règles suivantes :

L’identifiant harmonisé privilégie `codecommune2` lorsqu’il est valide, avec repli sur `codecommune`. Paris, Lyon et Marseille sont traitées comme communes entières : les arrondissements sont agrégés lorsqu’aucune ligne communale globale n’est disponible. Cette convention évite de mélanger communes et arrondissements dans le même panel.

1. les marges électorales requises sont renseignées ;
2. le nombre d’inscrits est strictement positif ;
3. le nombre de votants est compris entre zéro et le nombre d’inscrits ;
4. le nombre d’exprimés est strictement positif ;
5. les agrégats gauche et droite sont compris entre zéro et le nombre d’exprimés ;
6. les six comptes CSP sont renseignés et non négatifs ;
7. la somme des six comptes CSP est strictement positive.

Les effectifs admissibles avant intersection sont :

| Élection | Communes admissibles |
| --- | ---: |
| 1962 | 36 283 |
| 1986 | 35 987 |
| 2022 | 34 645 |
| Intersection dans l’univers de référence 2022 | 33 922 |

L’intersection brute des trois ensembles électoraux contient 33 923 identifiants. Une commune supplémentaire est écartée lors du rattachement à l’univers de référence 2022, qui exige également les variables territoriales et sociales servant aux contrôles d’équilibre. Le cadre final représente 97,916 % des 34 644 communes de l’univers 2022.

L’éligibilité utilise donc la présence et la validité des marges agrégées. À l’intérieur de ce cadre admissible, le niveau du vote n’intervient ni dans l’ordre aléatoire ni dans la probabilité d’inclusion.

## Tirage sans remise et porte d’équilibre

Pour une tentative de graine donnée, le générateur `numpy.random.default_rng` produit une permutation de l’univers admissible. Les 3 000 premières communes de cette permutation constituent le panel candidat ; aucune commune ne peut donc être sélectionnée deux fois.

Le candidat est ensuite comparé à deux références :

- l’univers commun admissible de 33 922 communes ;
- l’univers communal complet de référence de 2022, qui contient 34 644 communes.

Les variables continues contrôlées sont le logarithme du nombre d’inscrits et les parts des ouvriers, employés, cadres, ainsi que des agriculteurs et indépendants. Les variables catégorielles sont la région à 13 modalités et la catégorie VBBM.

Pour une variable continue `x`, le contrôle emploie l'écart moyen standardisé

`SMD = (moyenne_panel(x) − moyenne_univers(x)) / écart-type_univers(x)`,

avec l'écart-type de population (`ddof=0`) dans l'univers de comparaison. Pour une modalité catégorielle `k`, l'écart est `proportion_panel(k) − proportion_univers(k)`. La distance KS et les quantiles 5 %, 25 %, 50 %, 75 % et 95 % sont descriptifs : ils ne constituent pas une condition supplémentaire d'acceptation.

L’acceptation impose simultanément :

- un écart moyen standardisé maximal `|SMD| ≤ 0,10` pour les variables continues ;
- un écart absolu de proportion maximal `≤ 0,02` pour chaque modalité catégorielle ;
- aucune modalité territoriale représentant au moins 0,5 % de l’univers vide.

Si un candidat échoue, la graine est incrémentée et un nouveau tirage complet est effectué. Cette procédure est une forme de ré-randomisation sous contraintes d’équilibre : **conditionnellement à son acceptation, le panel n’est pas un sondage aléatoire simple pur**.

## Résultats des contrôles d’équilibre

La première tentative, avec la graine `20260802`, a satisfait toutes les règles.

| Référence | Maximum `|SMD|` | Variable du maximum | Maximum de l’écart catégoriel | Modalité du maximum | Maximum KS | Verdict |
| --- | ---: | --- | ---: | --- | ---: | --- |
| Univers commun admissible | 0,01939 | agriculteurs + indépendants | 0,01032 | VBBM 1 | 0,01694 | accepté |
| Univers complet de référence 2022 | 0,01846 | agriculteurs + indépendants | 0,00959 | VBBM 1 | 0,01643 | accepté |

Ces écarts sont nettement inférieurs aux seuils de 0,10 et 0,02. Les quantiles, distances de Kolmogorov–Smirnov et proportions par région/VBBM sont fournis dans `panel_3000_common_1962_1986_2022_v2_balance.csv` comme contrôles descriptifs supplémentaires.

### Composition territoriale

| Région | Panel | Univers commun | Univers 2022 |
| --- | ---: | ---: | ---: |
| Île-de-France | 108 | 1 212 | 1 267 |
| Centre-Val de Loire | 156 | 1 728 | 1 755 |
| Bourgogne-Franche-Comté | 326 | 3 587 | 3 675 |
| Normandie | 234 | 2 596 | 2 646 |
| Hauts-de-France | 342 | 3 747 | 3 777 |
| Grand Est | 441 | 4 941 | 5 082 |
| Pays de la Loire | 119 | 1 199 | 1 234 |
| Bretagne | 89 | 1 197 | 1 207 |
| Nouvelle-Aquitaine | 352 | 4 240 | 4 303 |
| Occitanie | 406 | 4 310 | 4 397 |
| Auvergne-Rhône-Alpes | 332 | 3 952 | 4 005 |
| Provence-Alpes-Côte d’Azur | 73 | 920 | 938 |
| Corse | 22 | 293 | 358 |

| VBBM | Panel | Univers commun | Univers 2022 |
| --- | ---: | ---: | ---: |
| 1 | 2 327 | 25 962 | 26 540 |
| 2 | 504 | 5 986 | 6 073 |
| 3 | 167 | 1 924 | 1 977 |
| 4 | 2 | 50 | 54 |

La modalité VBBM 4 est donc présente, mais seulement avec deux communes. Les résultats propres aux contextes métropolitains les plus rares ne doivent pas être surinterprétés.

### Taille électorale des communes

| Inscrits en 2022 | Panel | Univers commun | Univers 2022 |
| --- | ---: | ---: | ---: |
| Moyenne | 1 141,49 | 1 264,83 | 1 274,89 |
| 1er centile | 34 | 36 | 36 |
| 5e centile | 69 | 65 | 64 |
| Médiane | 359 | 363 | 360 |
| 95e centile | 3 963,55 | 4 464,90 | 4 486,85 |
| 99e centile | 14 706,73 | 15 734,51 | 15 845,12 |
| Total | 3 424 470 | 42 905 504 | 44 167 208 |

Le panel contient 30 communes au-dessus du 99e centile de taille de l’univers commun. Il représente 8,844 % des communes mais 7,981 % de leurs inscrits. Cet écart est cohérent avec un tirage équiprobable de communes et un contrôle sur `log(1 + inscrits)`, et non avec un tirage proportionnel au nombre d’électeurs.

## Invariants imposés aux estimations

Avant chaque MCMC, le pipeline vérifie :

- exactement 3 000 lignes incluses ;
- des identifiants communaux non nuls et uniques ;
- une permutation exacte des rangs 1 à 3 000 ;
- un seul `sample_id` ;
- le SHA-256 du fichier de panel ;
- aucune exclusion silencieuse dans les douze jeux d’entrée modèle ;
- le même panel pour toutes les dates et hypothèses.

Le panel figé est identifié par `panel_3000_common_1962_1986_2022_seed_20260802_v2` et son SHA-256 est `d70810a1add048d4823274e182f3adf8735d6f881bd32564a550c78988e8cd3f`.

## Population à laquelle les résultats se rapportent

La cible empirique est l’univers des communes de référence 2022 qui disposent de marges électorales et sociales valides aux trois dates. Les estimations ne doivent donc pas être présentées comme représentatives sans réserve :

- de toutes les communes existant séparément en 1962, 1986 ou 2022 ;
- des communes disparues, fusionnées ou non raccordées à la géographie de référence ;
- des communes dont les données CSP ou électorales sont incomplètes ;
- directement des individus, puisque l’analyse reste une inférence écologique.

## Limites de l’échantillonnage

1. Les variables d’équilibre sont mesurées dans l’univers de référence 2022 ; l’équilibre historique sur ces mêmes caractéristiques n’est pas directement observé.
2. L’intersection temporelle peut induire un biais de stabilité ou de survivance géographique.
3. Les intervalles postérieurs sont conditionnels à ce panel particulier. Ils ne comprennent pas l’incertitude entre plusieurs panels équilibrés possibles.
4. La validité/disponibilité des marges électorales intervient dans l’éligibilité, même si le niveau du vote n’intervient pas dans le tirage au sein du cadre admissible.
5. La porte d’équilibre améliore la comparabilité descriptive, mais ne garantit ni l’identification individuelle ni l’absence de tout biais non mesuré.
6. La modalité VBBM 4 ne contient que deux communes ; sa présence ne suffit pas à assurer une estimation segmentée stable.
7. La reconstruction dépend des versions logicielles ; les versions NumPy/Pandas et les empreintes des quatre archives sources sont donc conservées dans le manifeste.

## Reproductibilité et fichiers de preuve

La construction est implémentée dans `code_longitudinal/build_common_panel_v2.py`. Elle peut être rejouée depuis la racine du **projet complet**, avec les modules auxiliaires et les quatre archives sources accessibles, au moyen de :

```powershell
python -m code_longitudinal.build_common_panel_v2 --panel-size 3000 --initial-seed 20260802
```

Fichiers d’audit :

- `panel/panel_3000_common_1962_1986_2022_v2.csv` : panel figé ;
- `panel/panel_3000_common_1962_1986_2022_v2_manifest.json` : définition, graine, effectifs et empreinte ;
- `panel/panel_3000_common_1962_1986_2022_v2_attempts.csv` : historique des tentatives ;
- `panel/panel_3000_common_1962_1986_2022_v2_balance.csv` : SMD, écarts de proportions, KS et quantiles ;
- `outputs/v2/priority_model_ready_3000_audit.csv` : preuve que les douze entrées contiennent chacune 3 000 communes sans exclusion.

La livraison complète finale contient le panel, ses preuves d’équilibre, les six entrées H0A/H1 utilisées, les traces, les latents et le code principal de post-traitement. Elle ne contient pas les quatre archives brutes ni l’environnement logiciel complet : une reconstruction depuis les sources exige donc le projet complet et les données d’origine. La copie compacte sous 500 Mo conserve les mêmes preuves de panel et les six entrées, mais seulement deux traces NetCDF représentatives ; cette réduction ne change pas le panel ni les résultats publiés.
