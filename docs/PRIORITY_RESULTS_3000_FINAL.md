# Résultats consolidés sur 3 000 communes — H0A et H1

## Périmètre

La production comprend six ajustements KRT : H0A et H1 pour 1962, 1986 et 2022. Ils utilisent le même panel de 3 000 communes. Les réglages sont fixes : 4 chaînes, 1 000 itérations de chauffe, 1 000 tirages par chaîne, `target_accept=0,99` et `max_treedepth=14`.

Le bilan conservateur compte **2 ajustements satisfaisants**, **4 satisfaisants avec réserve** et **0 insuffisant**. Les valeurs chiffrées présentées sont les pires parmi les β communaux ; une réserve est ajoutée si les quatre hyperparamètres sont moins bien échantillonnés. Les six ajustements ont zéro divergence et zéro saturation de profondeur d'arbre.

## Définition des deux hypothèses

- **H0A** oppose les ouvriers et employés aux autres groupes sociaux et modélise leur probabilité d'abstention parmi les inscrits ;
- **H1** utilise la même partition sociale et modélise la probabilité de vote à gauche parmi les suffrages exprimés.

`β₁` désigne la probabilité latente des ouvriers et employés ; `β₂` celle du groupe complémentaire.

## Résultats agrégés

Les agrégats sont calculés à chaque tirage avec les effectifs propres aux deux groupes : `Σ N1ᵢβ1ᵢ / ΣN1ᵢ` et `Σ N2ᵢβ2ᵢ / ΣN2ᵢ`. Le contraste est `β₁−β₂`.

| scenario_id | year | estimate | lower | upper | positive_draws |
| --- | --- | --- | --- | --- | --- |
| H0A | 1962 | -0.110 | -0.136 | -0.085 | 0 / 4000 |
| H0A | 1986 | 0.039 | 0.020 | 0.057 | 4000 / 4000 |
| H0A | 2022 | 0.088 | 0.071 | 0.106 | 4000 / 4000 |
| H1 | 1962 | 0.101 | 0.040 | 0.159 | 3999 / 4000 |
| H1 | 1986 | 0.156 | 0.113 | 0.199 | 4000 / 4000 |
| H1 | 2022 | -0.034 | -0.060 | -0.008 | 27 / 4000 |

Les changements entre dates utilisent 50 000 paires de tirages indépendants, avec la graine `20260804`. Les intervalles sont des intervalles postérieurs de comparaison sous indépendance des ajustements.

| scenario_id | earlier_year | later_year | estimate | lower | upper |
| --- | --- | --- | --- | --- | --- |
| H0A | 1962 | 1986 | 0.149 | 0.117 | 0.181 |
| H0A | 1962 | 2022 | 0.198 | 0.167 | 0.230 |
| H0A | 1986 | 2022 | 0.049 | 0.025 | 0.075 |
| H1 | 1962 | 1986 | 0.055 | -0.018 | 0.130 |
| H1 | 1962 | 2022 | -0.135 | -0.199 | -0.069 |
| H1 | 1986 | 2022 | -0.189 | -0.241 | -0.139 |

![Agrégats corrigés](../figures/v2/priority_3000_final/aggregate_drawwise_corrected_3000_v1.png)

![Contrastes intra-période](../figures/v2/priority_3000_final/within_period_contrasts_3000_v1.png)

## Diagnostics MCMC des β communaux

Le diagnostic publié retient le R-hat le plus élevé et les ESS les plus faibles parmi les 6 000 paramètres communaux `b_1` et `b_2`. Les divergences, le BFMI et la profondeur d'arbre restent contrôlés sur le sampler. Si les quatre hyperparamètres ont un R-hat ou un ESS moins favorable, le statut devient `satisfaisant avec réserve`, sans remplacer les métriques β affichées.

| scenario_id | year | mcmc_assessment_label | beta_diagnostic_status | non_beta_parameter_status | identification_status | max_rhat | min_ess_bulk | min_ess_tail | min_bfmi | divergences |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| H0A | 1962 | satisfaisant avec réserve | pass | caveat | caveat | 1.007 | 2818.985 | 2080.228 | 0.454 | 0 |
| H0A | 1986 | satisfaisant avec réserve | pass | caveat | pass | 1.007 | 4206.362 | 2008.060 | 0.551 | 0 |
| H0A | 2022 | satisfaisant | pass | pass | caveat | 1.009 | 5092.061 | 2035.653 | 0.542 | 0 |
| H1 | 1962 | satisfaisant avec réserve | caveat | caveat | caveat | 1.010 | 581.026 | 358.012 | 0.315 | 0 |
| H1 | 1986 | satisfaisant | pass | pass | caveat | 1.007 | 4215.814 | 1989.942 | 0.491 | 0 |
| H1 | 2022 | satisfaisant avec réserve | pass | caveat | caveat | 1.008 | 2327.187 | 1707.210 | 0.574 | 0 |

![Diagnostics des β communaux](../figures/v2/priority_3000_final/canonical_diagnostics_3000_v1.png)

Les diagnostics des estimands portent sur les deux agrégats et leur contraste. Ils complètent le diagnostic des paramètres β communaux.

| scenario_id | year | estimand_mcmc_status | rhat | ess_bulk | ess_tail | mcse_mean |
| --- | --- | --- | --- | --- | --- | --- |
| H0A | 1962 | pass | 1.008 | 936.902 | 1553.321 | 0.000 |
| H0A | 1986 | caveat | 1.012 | 519.283 | 1212.830 | 0.000 |
| H0A | 2022 | pass | 1.004 | 930.690 | 1697.402 | 0.000 |
| H1 | 1962 | pass | 1.003 | 1139.740 | 2135.177 | 0.001 |
| H1 | 1986 | pass | 1.008 | 595.064 | 1019.389 | 0.001 |
| H1 | 2022 | pass | 1.008 | 847.878 | 1456.055 | 0.000 |

![Diagnostics des contrastes agrégés](../figures/v2/priority_3000_final/estimand_diagnostics_3000_v1.png)

## Identification écologique

L'identification est évaluée séparément à partir des bornes de tomographie et de la variation de composition. H0A–1986 est `pass` ; les cinq autres ajustements sont `caveat`. Une bonne convergence MCMC ne suffit donc pas à identifier précisément des comportements individuels.

## Densités jointes

`joint_latent_3000_v1.csv` contient 18 000 lignes. Les densités utilisent un lissage commun aux trois dates à l'intérieur de chaque hypothèse.

### Communes équipondérées

![Densité jointe H0A — communes équipondérées](../figures/v2/priority_3000_final/densities/joint_beta_H0A_common_bandwidth_equal_communes.png)

![Densité jointe H1 — communes équipondérées](../figures/v2/priority_3000_final/densities/joint_beta_H1_common_bandwidth_equal_communes.png)

### Pondération par la taille communale

![Densité jointe H0A — pondération N total](../figures/v2/priority_3000_final/densities/joint_beta_H0A_common_bandwidth_N_total_weighted.png)

![Densité jointe H1 — pondération N total](../figures/v2/priority_3000_final/densities/joint_beta_H1_common_bandwidth_N_total_weighted.png)

### Densités marginales comparées

![Densités marginales H0A](../figures/v2/priority_3000_final/densities/marginal_beta_H0A_group_population_weighted.png)

![Densités marginales H1](../figures/v2/priority_3000_final/densities/marginal_beta_H1_group_population_weighted.png)

## Échantillonnage, portée et limites

Le panel provient d'un tirage sans remise dans 33 922 communes admissibles aux trois dates. La graine `20260802` est acceptée au premier essai après contrôle d'équilibre sur des variables 2022.

Les résultats sont conditionnels au panel, aux marges reconstruites et aux priors KRT. Ils ne propagent pas l'incertitude entre panels alternatifs. Les ajustements sont séparés par date : ils ne décrivent ni les mêmes électeurs suivis dans le temps, ni des transferts individuels.

## Prochaines vérifications

Les contrôles restant à faire sont les posterior predictive checks, la sensibilité aux priors et à `king_lambda`, puis la répétition sur plusieurs panels équilibrés.

La méthode de sélection et le contrat du panel sont détaillés dans `METHODE_ECHANTILLONNAGE_PANEL_3000.md`.

Le résumé autonome est dans `RESUME_TRAVAIL_ET_ANALYSES_3000.md`, le contrôle visuel des densités dans `COMPARAISON_DENSITES_JOINTES_3_PERIODES.md` et les choix méthodologiques sensibles dans `METHODOLOGIE_ET_CHOIX_SENSIBLES_3000.md`.

Le rapport tout-en-un destiné au professeur est `RESUME_GENERAL_PROFESSEUR_3000.md`.
