# Résultats longitudinaux prioritaires — correction V2 et production 3 000 communes

## Résumé technique

- **Le contenu V1 est conservé bit à bit.** Le manifeste de préservation contrôle 129 fichiers; état actuel : `integrity_ok=True`. L’archive V1 originale est incluse telle quelle dans l’archive V2.
- **L’erreur d’agrégation est corrigée sans réestimer les traces V1.** Chaque tirage utilise désormais `Σ N₁ᵢβ₁ᵢ / ΣN₁ᵢ` et `Σ N₂ᵢβ₂ᵢ / ΣN₂ᵢ`. L’écart maximal constaté face à l’export V1 est de 1.95 points, pour H1 en 1962 (b_1).
- **Il n’existe plus deux diagnostics concurrents.** Le verdict officiel V2 porte sur toutes les variables postérieures, BFMI, divergences et profondeur d’arbre. 7/12 traces passent, 3 ont une réserve et 2 échouent.
- **Les 12 jeux d’entrée à 3 000 communes sont prêts, mais les 12 MCMC ne sont pas terminées.** Exactement 3000 communes sont présentes dans chaque hypothèse/date, sans exclusion. État réel : 2/12 estimations terminées, 10 en attente, 0 en échec; exécution `paused_by_user`. Temps restant si la production reprend au rythme observé : environ 3.3 h.
- **Le benchmark NLS 2×2 est exécuté sur les mêmes 12 entrées à 3 000 communes.** État : `executed=True`, résultats : `{'success': 12}`.

## Les contrastes corrigés montrent un basculement net pour H0A

| year | estimate | lower | upper | probability_gt_zero | mcmc_status | identification_status |
| --- | --- | --- | --- | --- | --- | --- |
| 1962 | -0.109 | -0.175 | -0.046 | 0.001 | pass | caveat |
| 1986 | 0.014 | -0.031 | 0.057 | 0.740 | pass | pass |
| 2022 | 0.116 | 0.072 | 0.161 | 1.000 | pass | caveat |

Pour H0A, le contraste `ouvriers+employés − autres CSP` passe d’un niveau négatif en 1962 à positif en 2022. Cette lecture reste une inférence écologique : les diagnostics d’identification quantifient la largeur des bornes de tomographie et imposent une réserve lorsque celles-ci sont larges.

![Contrastes intra-période](../figures/v2/priority_500_reanalysis/within_period_contrasts_v2.png)

## H1 varie moins nettement entre les périodes

| year | estimate | lower | upper | probability_gt_zero | mcmc_status | identification_status |
| --- | --- | --- | --- | --- | --- | --- |
| 1962 | 0.107 | -0.033 | 0.241 | 0.931 | pass | caveat |
| 1986 | 0.119 | 0.019 | 0.225 | 0.990 | pass | caveat |
| 2022 | -0.019 | -0.079 | 0.044 | 0.274 | pass | caveat |

Les changements 1962→2022 sont calculés par rééchantillonnage indépendant des deux postérieures électorales; ils ne constituent pas une trajectoire individuelle.

| scenario_id | estimate | lower | upper | probability_gt_zero |
| --- | --- | --- | --- | --- |
| H0A | 0.225 | 0.147 | 0.305 | 1.000 |
| H1 | -0.126 | -0.271 | 0.028 | 0.055 |
| H2 | -0.178 | -0.364 | 0.007 | 0.030 |
| H4 | -0.043 | -0.179 | 0.095 | 0.271 |

## La correction des poids modifie matériellement certains agrégats

![Effet de la correction des poids](../figures/v2/priority_500_reanalysis/aggregation_correction_shift_v2.png)

Les probabilités sont conditionnelles au groupe social. Le dénominateur pertinent est donc l’effectif du groupe, et non l’effectif communal total. Les anciens nombres restent disponibles uniquement comme comparaison historique et ne sont plus étiquetés comme estimateur canonique.

## Un seul diagnostic MCMC gouverne chaque trace

![Diagnostic officiel V2](../figures/v2/priority_500_reanalysis/official_diagnostics_v2.png)

Les métriques par bloc (`hyperparameters`, `latent_preferences`) servent à localiser un problème mais ne portent aucun second verdict. En particulier, plusieurs H2/H4 ont des β communaux apparemment stables alors que leurs hyperparamètres et/ou le BFMI échouent : ils restent exploratoires.

`b_1` et `b_2` sont les probabilités latentes communales étudiées. `c_1`, `c_2`, `d_1` et `d_2` sont seulement des hyperparamètres internes de la même estimation KRT; ils ne correspondent ni à d’autres communes, ni à une seconde estimation, ni à un second diagnostic. Chaque run possède un seul verdict officiel dans `mcmc_diagnostics_v2.json`.

## Les contrôles prédictifs sont rassurants mais ne prouvent pas l’identification

Les 12 PPC couvrent la part agrégée observée; RMSE communale de 0.0102 à 0.0218, couverture de 99.60% à 100.00%, p-value de Pearson de 0.372 à 0.555.

Les traces historiques présentent aussi un écart d’une voix dans 11 à 32 communes par run, dû au retour flottant `(Y/N)×N` de PyEI. Le PPC utilise le compte effectivement ajusté; le nouveau pipeline V2 stabilise ce retour numérique pour les futures traces.

## Périmètre, données et définitions

- Hypothèses principales : H0A, H1, H2 et H4, pour 1962, 1986 et 2022.
- Réanalyse immédiate : 12 traces KRT V1, panel 500/494/500, sans modification des traces.
- Production V2 : panel commun exact de 3 000 communes observables et analytiquement valides aux trois dates.
- Catégorie cible : première catégorie politique déclarée par le scénario; β₁ et β₂ sont les probabilités latentes de cette catégorie dans chacun des deux groupes sociaux.
- Densités jointes : distribution entre communes des moyennes postérieures `(β₁,β₂)`; elles ne sont pas la postérieure bivariée d’une commune unique.

## Méthode et robustesse

1. Vérification SHA256 des 129 fichiers V1 protégés.
2. Recalcul draw-wise des agrégats avec poids de groupe.
3. Contrastes intra-période et changements entre périodes avec incertitude.
4. Diagnostic MCMC officiel unique sur toutes les variables.
5. Bornes de tomographie et variation de la composition sociale comme diagnostic d’identification.
6. PPC binomial par commune et agrégé.
7. Bootstrap descriptif des communes, sans prétendre remplacer une réestimation de panel.
8. Nouveau panel longitudinal commun de 3 000 communes; contrôles d’équilibre contre l’univers commun et l’univers 2022 complet.

## Limites et questions encore ouvertes

- La réanalyse V2 sur 500/494/500 communes corrige l’estimateur mais ne remplace pas les relances sur 3 000 communes. À l’état de cette archive, seules H0A-1962 et H0A-1986 sont terminées à 3 000.
- Les densités jointes déjà livrées comparent les trois périodes à partir des traces historiques 500/494/500. Une comparaison complète à 3 000 communes exigera les dix MCMC encore en attente.
- Une bonne calibration PPC n’établit pas l’identification des comportements individuels.
- Les H2/H4 qui échouent au diagnostic complet nécessitent une paramétrisation moyenne/concentration ou une sensibilité de prior avant interprétation forte.
- Le bootstrap de communes ne refait pas le modèle; il mesure seulement la sensibilité descriptive au panel observé.
- King doit rester un benchmark séquentiel ciblé, pas être confondu avec la production KRT principale.

## Prochaines étapes suivies

1. Terminer les 12 fits KRT sur 3 000 communes avec 4 chaînes, 1 000 tune, 1 000 draws et `target_accept=0,99`.
2. Auditer chaque fit avec le verdict V2 et conserver les échecs au lieu de les masquer.
3. Relancer seulement les H2/H4 problématiques sous paramétrisation améliorée.
4. Ajouter le benchmark King limité; les 12 NLS 2×2 intercept-only sont déjà produits et clairement étiquetés.
5. Remplacer dans le rapport final les résultats 500 par les résultats 3 000 lorsqu’ils sont disponibles.

## Fichiers d’audit

- `outputs/v2/priority_500_reanalysis/` : agrégats corrigés, contrastes, diagnostics, identification et bootstrap.
- `outputs/v2/ppc_krt/` : métriques et détails PPC.
- `outputs/v2/nls_priority/` : 12 benchmarks NLS sur le panel commun de 3 000 communes.
- `panel/panel_3000_common_1962_1986_2022_v2*` : panel exact, équilibre et manifeste.
- `outputs/v2/preservation_manifest_v1.json` : empreintes du contenu protégé.
- `deliverables/longitudinal_priority_results_v2_corrige_3000_en_cours.zip` : archive versionnée incluant l’archive V1 intacte et les deux runs KRT déjà terminés à 3 000 communes.
