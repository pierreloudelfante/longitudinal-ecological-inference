# Guide de la production KRT consolidée — 3 000 communes, H0A et H1

## Résumé technique

La production intermédiaire consolidée contient six ajustements KRT : `H0A` et `H1` pour les législatives de 1962, 1986 et 2022. Chaque ajustement utilise le même panel de 3 000 communes, quatre chaînes, 1 000 itérations de chauffe et 1 000 tirages conservés par chaîne, avec `target_accept=0,99` et `max_treedepth=14`.

Le bilan MCMC conservateur compte **2 satisfaisants**, **4 satisfaisants avec réserve** et **0 insuffisant**. Les valeurs chiffrées restent les pires R-hat et ESS parmi les 6 000 β communaux. Une réserve est ajoutée lorsque les quatre hyperparamètres sont moins bien échantillonnés. Les six ajustements ont zéro divergence et zéro saturation de profondeur d’arbre. L’identification écologique est évaluée séparément.

Ce document est le point d’entrée du sous-dossier `priority_3000_final`. Les documents nommés `ARCHIVE_V2`, `en_cours`, `500` ou `pilote` décrivent des étapes antérieures.

Pour une lecture ciblée :

- [`RESUME_GENERAL_PROFESSEUR_3000.md`](RESUME_GENERAL_PROFESSEUR_3000.md) rassemble l’échantillonnage, les résultats, les dix figures, les diagnostics et les outputs dans un seul rapport ;
- [`RESUME_TRAVAIL_ET_ANALYSES_3000.md`](RESUME_TRAVAIL_ET_ANALYSES_3000.md) résume les six fits, les résultats, les diagnostics et les limites ;
- [`COMPARAISON_DENSITES_JOINTES_3_PERIODES.md`](COMPARAISON_DENSITES_JOINTES_3_PERIODES.md) compare visuellement et quantitativement les densités de β₁ et β₂ ;
- [`METHODE_ECHANTILLONNAGE_PANEL_3000.md`](METHODE_ECHANTILLONNAGE_PANEL_3000.md) documente le tirage et la porte d’équilibre ;
- [`METHODOLOGIE_ET_CHOIX_SENSIBLES_3000.md`](METHODOLOGIE_ET_CHOIX_SENSIBLES_3000.md) explicite les choix de modèle, de marges, d’agrégation et de diagnostic.

## Résultats principaux et figures

Le contraste publié est `β₁ − β₂`, calculé à chaque draw après agrégation avec les dénominateurs propres aux groupes.

| Hypothèse | 1962 | 1986 | 2022 | Changement 1962–2022 |
| --- | ---: | ---: | ---: | ---: |
| H0A | −0,110 | +0,039 | +0,088 | +0,198 [0,167 ; 0,230] |
| H1 | +0,101 | +0,156 | −0,034 | −0,135 [−0,199 ; −0,069] |

![Agrégats KRT corrigés](../figures/v2/priority_3000_final/aggregate_drawwise_corrected_3000_v1.png)

![Contrastes intra-période](../figures/v2/priority_3000_final/within_period_contrasts_3000_v1.png)

Le rapport illustré complet, avec les densités jointes et marginales, est [`PRIORITY_RESULTS_3000_FINAL.md`](PRIORITY_RESULTS_3000_FINAL.md).

## Périmètre, unités et définitions

- **H0A** : ouvriers et employés contre les autres CSP ; événement modélisé = abstention parmi les inscrits.
- **H1** : même partition sociale ; événement modélisé = vote à gauche parmi les suffrages exprimés.
- **β₁** : probabilité latente du premier groupe, ouvriers + employés.
- **β₂** : probabilité latente du groupe complémentaire.
- **Unité du panel** : commune harmonisée dans la géographie de référence 2022.
- **Périodes** : trois ajustements séparés, pour 1962, 1986 et 2022.
- **Comparaison temporelle** : comparaison de distributions postérieures issues de fits séparés ; elle ne suit pas des individus dans le temps.

## Processus effectivement exécuté

```text
archives électorales et CSP
  -> harmonisation des identifiants communaux
  -> intersection admissible 1962/1986/2022
  -> tirage sans remise de 3 000 communes
  -> porte d’équilibre et gel du SHA-256 du panel
  -> préparation de six entrées modèle H0A/H1
  -> six MCMC KRT, exécutées séquentiellement
  -> diagnostic MCMC publié sur les β communaux de chaque trace
  -> agrégation corrigée draw par draw
  -> contrastes intra-période et changements inter-périodes
  -> diagnostics MCMC des agrégats et contrastes
  -> diagnostics d’identification séparés
  -> densités jointes et marginales
  -> rapport, manifeste, ZIP et SHA-256
```

Les commandes utilisées pour la reprise et la finalisation sont :

```powershell
python -m code_longitudinal.run_priority_production_v2 --scenario H0A --scenario H1
python -m code_longitudinal.finalize_priority_results_3000 --check-ready
python -m code_longitudinal.finalize_priority_results_3000
```

Le runner conserve un plan de douze items (`H0A`, `H1`, `H2`, `H4` × trois dates). La présente livraison retient uniquement les six ajustements `H0A/H1`. Les résultats `H2/H4`, les tentatives interrompues et les anciens runs à 500 communes sont exclus.

## Échantillonnage des communes

Le cadre final contient 33 922 communes admissibles aux trois élections. Le tirage utilise `numpy.random.default_rng(seed).permutation` et conserve les 3 000 premiers identifiants : il est donc sans remise et sans duplication. Le candidat est ensuite soumis à une porte d’équilibre sur des variables mesurées en 2022.

- graine initiale et retenue : `20260802` ;
- tentative retenue : première tentative ;
- fraction de sondage : 8,844 % des communes admissibles ;
- maximum `|SMD|` contre l’univers commun : 0,019393 ;
- maximum d’écart catégoriel : 0,010323 ;
- SHA-256 du panel : `d70810a1add048d4823274e182f3adf8735d6f881bd32564a550c78988e8cd3f`.

Il ne s’agit pas d’un tirage stratifié. Conditionnellement à l’acceptation par la porte d’équilibre, il ne s’agit pas non plus d’un sondage aléatoire simple pur. La méthode, les formules, les distributions régionales/VBBM et les limites sont détaillées dans [`METHODE_ECHANTILLONNAGE_PANEL_3000.md`](METHODE_ECHANTILLONNAGE_PANEL_3000.md).

## Modèle, agrégation et incertitude

Pour chaque draw postérieur `s`, les deux estimands agrégés sont :

`β̄₁(s) = Σᵢ N₁ᵢ β₁ᵢ(s) / Σᵢ N₁ᵢ`

`β̄₂(s) = Σᵢ N₂ᵢ β₂ᵢ(s) / Σᵢ N₂ᵢ`

Le contraste intra-période est ensuite `Δₜ(s) = β̄₁,ₜ(s) − β̄₂,ₜ(s)`. Les changements entre périodes utilisent 50 000 paires de draws indépendants, avec la graine `20260804`, car les trois élections ont été ajustées séparément.

Les densités communales ont une autre interprétation : elles décrivent la distribution entre communes des moyennes postérieures `b1_mean` et `b2_mean`. Deux versions de densité jointe sont publiées, communes équipondérées et pondération par la taille communale. Un bandwidth commun est utilisé entre les trois dates au sein de chaque hypothèse.

## Diagnostic des β et identification séparée

Le tableau publié `canonical_mcmc_diagnostics_3000_v1.csv` reprend, pour chaque run, le pire R-hat et les plus faibles ESS parmi les 3 000 `b_1` et les 3 000 `b_2`. Les divergences, le BFMI et la profondeur d’arbre restent des contrôles du sampler entier. Le statut final est abaissé à `satisfaisant avec réserve` si les quatre hyperparamètres ont un R-hat ou un ESS moins favorable. Le fichier brut `mcmc_diagnostics_v2.json` conserve toutes les métriques pour audit. Les anciens `model_diagnostics.csv` ne sont ni utilisés ni inclus dans le ZIP.

| Hypothèse | Année | Bilan | β | Hors β | R-hat max β | ESS bulk min β | ESS tail min β |
| --- | ---: | --- | --- | --- | ---: | ---: | ---: |
| H0A | 1962 | satisfaisant avec réserve | pass | caveat | 1,0072 | 2 819,0 | 2 080,2 |
| H0A | 1986 | satisfaisant avec réserve | pass | caveat | 1,0069 | 4 206,4 | 2 008,1 |
| H0A | 2022 | satisfaisant | pass | pass | 1,0085 | 5 092,1 | 2 035,7 |
| H1 | 1962 | satisfaisant avec réserve | caveat | caveat | 1,0102 | 581,0 | 358,0 |
| H1 | 1986 | satisfaisant | pass | pass | 1,0074 | 4 215,8 | 1 989,9 |
| H1 | 2022 | satisfaisant avec réserve | pass | caveat | 1,0077 | 2 327,2 | 1 707,2 |

`identification_separate_3000_v1.csv` décrit séparément la variation de composition et les largeurs des bornes de tomographie. Un `pass` MCMC ne signifie donc pas automatiquement une identification écologique forte, et un diagnostic d’identification ne remplace pas le diagnostic des chaînes.

Le champ interne `selected_for_interpretation` est conservé dans les JSON bruts. Il n’est pas repris dans le CSV consolidé, car il correspond à une règle automatique stricte différente du choix de présenter un résultat descriptif avec réserve. Le CSV utilise `retained_for_descriptive_reporting`, `reporting_status` et `reporting_reasons`.

`estimand_mcmc_diagnostics_3000_v1.csv` donne R-hat, ESS et MCSE pour β₁ agrégé, β₂ agrégé et leur contraste. Cinq contrastes sont `pass`; H0A–1986 est `caveat` avec R-hat 1,0118.

## Outputs canoniques

Tous les outputs finals se trouvent dans `outputs/v2/priority_3000_final/`.

| Fichier | Lignes | Rôle |
| --- | ---: | --- |
| `aggregate_drawwise_corrected_3000_v1.csv` | 12 | deux agrégats corrigés par fit |
| `within_period_contrasts_3000_v1.csv` | 6 | un contraste `β₁−β₂` par fit |
| `between_period_contrast_changes_3000_v1.csv` | 6 | trois changements par hypothèse |
| `canonical_mcmc_diagnostics_3000_v1.csv` | 6 | métriques β et bilan conservateur avec réserve hors β |
| `estimand_mcmc_diagnostics_3000_v1.csv` | 18 | diagnostics de β₁, β₂ et du contraste agrégés |
| `identification_separate_3000_v1.csv` | 6 | diagnostic d’identification distinct |
| `joint_latent_3000_v1.csv` | 18 000 | deux hypothèses × trois dates × 3 000 communes |
| `density_bandwidths_3000_v1.csv` | 8 | paramètres de lissage des figures |
| `release_manifest_3000_v1.json` | — | paramètres, run IDs et empreintes des traces |

Le dictionnaire détaillé de ce sous-dossier est dans [`../outputs/v2/priority_3000_final/README.md`](../outputs/v2/priority_3000_final/README.md).

## Figures produites

Le dossier `figures/v2/priority_3000_final/` contient dix figures, chacune en PNG et SVG :

- agrégats corrigés ;
- contrastes intra-période ;
- diagnostics MCMC centrés sur les β avec réserves hors β ;
- diagnostics MCMC des contrastes agrégés ;
- quatre densités jointes : H0A/H1 × équipondérée/pondérée ;
- deux figures de densités marginales : H0A et H1.

Le catalogue exact est dans [`../figures/v2/priority_3000_final/README.md`](../figures/v2/priority_3000_final/README.md).

## Livraison et validation

La livraison finale est `deliverables/longitudinal_priority_results_v2_3000_H0A_H1_complete.zip`, accompagnée du fichier `.sha256`. Elle contient notamment les six traces NetCDF, six fichiers de latents communaux, six diagnostics canoniques, les entrées modèle, les résultats, les figures, le panel, les méthodes et le code de post-traitement.

Contrôles effectués :

- CRC ZIP intégral : aucune entrée corrompue ;
- six traces et six diagnostics canoniques ;
- aucun `model_diagnostics.csv` historique ;
- aucune entrée issue de `diagnostic_audits/` ;
- aucun doublon dans le ZIP ;
- 79 tests Python définis et validés, dont un test dédié vérifiant que les hyperparamètres ne remplacent pas le pire diagnostic des β.

## Limites et suites recommandées

Les intervalles sont conditionnels au panel retenu et ne propagent pas l’incertitude entre panels alternatifs. La restriction aux communes raccordées et admissibles aux trois dates peut induire un biais de stabilité ou de survivance géographique. Les variables de la porte d’équilibre sont mesurées en 2022. La modalité VBBM 4 ne contient que deux communes. Enfin, les résultats restent des inférences écologiques : ils ne démontrent pas des transitions individuelles.

Les prochaines vérifications prioritaires sont les posterior predictive checks, la sensibilité aux priors et à `king_lambda`, puis l’incertitude entre plusieurs panels équilibrés.
