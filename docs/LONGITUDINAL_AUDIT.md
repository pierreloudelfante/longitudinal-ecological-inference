# Audit du pipeline longitudinal

## Verdict

Le dépôt antérieur couvrait correctement plusieurs briques 2022, mais pas leur orchestration longitudinale. La présente implémentation les rassemble sans modifier les données brutes ni les sorties historiques.

## Composants réutilisés ou adaptés

| Besoin | Source historique réelle | Décision |
|---|---|---|
| Préparation des scénarios 2022 | `../baseline_2022/scripts/prepare_priority_specs.py` | conventions et contrôles repris dans un registre longitudinal court |
| King/KRT PyEI | `../baseline_2022/scripts/run_pyei_king_priority_models.py` | appels PyEI et diagnostics adaptés ; extraction communale corrigée depuis les traces |
| NLS de Rosen | `../imports/NLS_ROSEN_RESUME_LEGER_20260727/01_CODE/run_rosen_article_nls.py` | objectif, softmax, solveur et sandwich préservés ; cas sans Z ajouté |
| NLS sans Z rapide | `../imports/NLS_ROSEN_RESUME_LEGER_20260727/01_CODE/run_rosen_nls_rapide.py` | utilisé comme référence de performance et de paramétrisation |
| Rosen RxC PyEI | `../baseline_2022/scripts/run_pyei_multinomial_dirichlet_ei.py` | wrapper généralisé aux élections pilotes |
| Identifiants et PLM | `../export_chat_pop6_ie_2022_resultats_pop6_nls_king_20260721/src/ei2022/geography.py` | fonctions courtes migrées dans le module canonique |
| Arrondi des marges | `../export_chat_pop6_ie_2022_resultats_pop6_nls_king_20260721/src/ei2022/registered_margin.py` | algorithme des plus forts restes repris et testé |
| Consolidation | `../baseline_2022/scripts/build_final_2022_reports.py` | principe conservé, schéma longitudinal ajouté |

## Éléments qui manquaient

- panel fixe de 3 000 communes avec tentatives et balance checks ;
- registre unique des 26 élections et des hypothèses H0A–H7/RXC1–RXC2 ;
- table explicite FN/RN par scrutin ;
- identifiants de run reproductibles et reprise sans écrasement ;
- extraction des distributions communales de `b_1` et `b_2` ;
- vues King/KRT natives et sur intersection commune ;
- NLS sans covariable avec diagnostics complets des 20 départs ;
- robustesses à une covariable, tables longitudinales et paquet professeur.

## État après implémentation

- Les 292 partitions admissibles ont été tentées à partir du panel fixe de
  3 000 : les 240 partitions 2×2 et 30 partitions RXC sont valides ; 22 RXC
  sont refusées sur écart brut supérieur à 0,01 voix.
- Le pilote King/KRT 1962/1986/2022 conserve 160 traces sélectionnées et 22
  couples au palier demandé 3 000. Trois KRT sont limités par la mémoire et un
  King H5 1962 n'a aucune observation intérieure.
- Les densités sont choisies au plus grand palier commun et leur provenance est
  exportée, au lieu d'afficher toutes les tailles sans hiérarchie.
- Le NLS RXC1 passe en 1986 et 2022 ; l'échec de rang 1962 est conservé.

## Point statistique important

Les effectifs CSP ne sont pas des effectifs d'inscrits ou de suffrages exprimés. Le pipeline conserve l'hypothèse historique M0 : les parts des six CSP actives sont recalées proportionnellement sur le dénominateur électoral, puis arrondies de façon déterministe. Cette hypothèse est inscrite dans chaque table model-ready et doit accompagner toute interprétation.

Le test local des modèles montre que coût et mémoire dépendent à la fois du
modèle et de la géométrie du scénario. Les calibrations `20/20/1`, y compris
celles qui atteignent 3 000 communes demandées, restent des tests techniques et
ne sont jamais assimilées à une production `4 × 1 000`.
