# Tests de balance du panel fixe

## Conclusion

Le panel principal de 3 000 communes et le pilote emboîté de 2 000 communes satisfont tous les critères de balance prédéfinis dès la première tentative, avec la graine `20260802`.

| Panel | Communes | max \(|SMD|\) | Seuil | max écart catégoriel | Seuil | Catégorie vide | Verdict |
|---|---:|---:|---:|---:|---:|---|---|
| principal | 3 000 | 0,024499 | 0,10 | 0,009710 | 0,02 | aucune | accepté |
| pilote | 2 000 | 0,028289 | 0,10 | 0,012308 | 0,02 | aucune | accepté |

Ces diagnostics portent uniquement sur des caractéristiques territoriales et sociales observées en 2022. Aucun résultat électoral n'entre dans la sélection : le tirage est donc aveugle aux variables politiques à expliquer.

## Univers de référence

L'univers \(U\) contient 34 644 communes observables en 2022. Une unité est admissible si elle possède :

- un identifiant communal stable ;
- un nombre d'inscrits strictement positif ;
- une région et une catégorie VBBM renseignées ;
- six catégories socioprofessionnelles actives, toutes finies et non négatives, dont la somme est strictement positive.

La construction correspond à `code_longitudinal/data_io.py:169-203`. Les identifiants et la politique appliquée à Paris, Lyon et Marseille sont définis dans `code_longitudinal/utils.py:25-59`.

## Critères d'acceptation

### Variables continues

Pour une variable \(z\), le diagnostic principal est la différence moyenne standardisée :

\[
SMD(z)=\frac{\bar z_S-\bar z_U}{s_U},
\]

où \(S\) est le panel, \(U\) l'univers 2022 et \(s_U\) l'écart-type de population de l'univers (`ddof=0`). L'acceptation exige

\[
\max_z |SMD(z)| \leq 0{,}10.
\]

Les variables testées sont :

- `log1p_inscrits` : \(\log(1+\text{inscrits})\) ;
- `share_ouvr` : part des ouvriers dans les six CSP actives ;
- `share_empl` : part des employés ;
- `share_cadr` : part des cadres ;
- `share_agri_indp` : part agrégée des agriculteurs et indépendants.

Le code est dans `code_longitudinal/balance_checks.py:10-11,15-45`. La distance de Kolmogorov-Smirnov et les quantiles 5, 25, 50, 75 et 95 % y sont également calculés, mais ce sont des contrôles descriptifs : ils n'entrent pas dans la règle d'acceptation et aucune p-value n'est utilisée.

### Variables catégorielles

Pour chaque modalité \(k\) d'une variable catégorielle \(g\), on calcule

\[
\Delta_{gk}=\Pr_S(g=k)-\Pr_U(g=k).
\]

L'acceptation exige

\[
\max_{g,k}|\Delta_{gk}|\leq 0{,}02.
\]

Les variables concernées sont la région (`region13`) et la catégorie territoriale VBBM (`vbbm`). Le code vérifie aussi qu'aucune modalité représentant au moins 0,5 % de l'univers n'est vide dans le panel. Dans les sorties produites, aucune modalité n'est vide, y compris sous ce seuil. Implémentation : `code_longitudinal/balance_checks.py:46-88`.

## Résultats détaillés

| Variable | SMD, panel 3 000 | KS, panel 3 000 | SMD, pilote 2 000 | KS, pilote 2 000 |
|---|---:|---:|---:|---:|
| `log1p_inscrits` | -0,012586 | 0,021623 | 0,006131 | 0,016594 |
| `share_ouvr` | -0,024499 | 0,018551 | -0,028289 | 0,022336 |
| `share_empl` | -0,000032 | 0,011625 | 0,007240 | 0,010322 |
| `share_cadr` | 0,000375 | 0,011789 | -0,023228 | 0,016614 |
| `share_agri_indp` | 0,024191 | 0,015542 | 0,018517 | 0,015961 |

L'écart catégoriel maximal du panel principal concerne la Normandie : -0,009710 (7,64 % dans l'univers contre 6,67 % dans le panel). Celui du pilote concerne le Grand Est : +0,012308 (14,67 % contre 15,90 %).

Les valeurs exhaustives et les quantiles sont dans `panel/panel_balance_checks.csv`. La tentative de sélection est dans `panel/panel_balance_attempts.csv` et le verdict accompagné des empreintes des sources dans `panel/panel_manifest.json`.

## Algorithme de sélection

1. Une permutation sans remise de l'univers admissible est produite avec la graine courante.
2. Les 3 000 premiers identifiants forment le panel principal.
3. Les 2 000 premiers rangs de ce même tirage forment le pilote, ce qui garantit \(S_{2000}\subset S_{3000}\).
4. Les deux panels sont soumis aux critères ci-dessus.
5. En cas d'échec, la graine est incrémentée, dans la limite de 1 000 tentatives.

La boucle se trouve dans `code_longitudinal/build_panel.py:55-103`. Les seuils et la graine sont déclarés dans `config/run_settings.json`. La première tentative a été acceptée ; aucun choix opportuniste parmi plusieurs tirages n'a donc été nécessaire.

## Ce que ce test établit — et ce qu'il n'établit pas

Le test établit que l'échantillon fixe ressemble à l'univers communal 2022 sur les covariables déclarées, aux tolérances fixées avant analyse. Il ne prouve ni une sélection aléatoire parfaite sur toutes les caractéristiques non observées, ni l'absence de biais rétrospectif lié à l'utilisation de communes encore observables en 2022. Il ne valide pas non plus les modèles d'inférence écologique : ceux-ci possèdent leurs diagnostics propres.

