# Paquet compact pour ChatGPT — moins de 500 Mo

## Objet

`longitudinal_priority_results_v2_3000_H0A_H1_compact_lt500mo.zip` est une copie de revue de la livraison scientifique complète. Elle est conçue pour rester sous la limite d’upload de 500 Mo sans retirer les résultats nécessaires à la lecture et à l’audit documentaire.

Ordre de lecture recommandé :

1. `README_PRODUCTION_3000_H0A_H1.md` — point d’entrée ;
2. `RESUME_GENERAL_PROFESSEUR_3000.md` — rapport tout-en-un à transmettre ;
3. `RESUME_TRAVAIL_ET_ANALYSES_3000.md` — résumé des analyses ;
4. `COMPARAISON_DENSITES_JOINTES_3_PERIODES.md` — contrôle visuel des densités jointes ;
5. `METHODE_ECHANTILLONNAGE_PANEL_3000.md` — tirage des communes ;
6. `METHODOLOGIE_ET_CHOIX_SENSIBLES_3000.md` — choix méthodologiques sensibles ;
7. `PRIORITY_RESULTS_3000_FINAL.md` — tables et figures consolidées.

## Contenu conservé pour les six estimations

- résultats agrégés corrigés draw par draw ;
- contrastes intra-période et changements inter-périodes ;
- diagnostics MCMC canoniques et métriques par variable/bloc ;
- diagnostics d’identification séparés ;
- 18 000 lignes de moyennes postérieures communales ;
- six fichiers de latents communaux en Parquet ;
- six entrées modèle ;
- six manifests de run et six diagnostics JSON ;
- panel commun, balance, méthode d’échantillonnage et empreintes ;
- rapport Markdown, guide général, figures PNG/SVG et code de post-traitement.

## Traces NetCDF conservées

Deux traces complètes sont incluses :

| Hypothèse | Année | Run | Statut | Pourquoi cette trace |
| --- | ---: | --- | --- | --- |
| H0A | 2022 | `20260804T144933Z__4830d0298ccd` | pass | exemple récent avec diagnostics satisfaisants |
| H1 | 1962 | `20260804T150252Z__2df1cacde040` | caveat | cas diagnostique le plus fragile, utile pour contrôler R-hat et ESS |

Les traces H0A‑1962, H0A‑1986, H1‑1986 et H1‑2022 ne sont pas incluses dans cette copie compacte. Leurs diagnostics, agrégats, latents, manifests et résultats restent présents. Les quatre traces complètes sont disponibles dans `longitudinal_priority_results_v2_3000_H0A_H1_complete.zip`.

## Limite d’interprétation du paquet compact

Cette réduction ne modifie aucun résultat scientifique. Elle limite seulement la possibilité de recalculer intégralement depuis NetCDF quatre des six fits. Pour une reproduction complète de tous les diagnostics et agrégats, utiliser le ZIP complet. Pour une lecture, une revue par ChatGPT ou une vérification ciblée des meilleurs/pire cas MCMC, le paquet compact suffit.

Le fichier `chatgpt_package_manifest.json` placé à la racine du ZIP donne la liste exacte des traces incluses et omises, l’empreinte de l’archive complète source et le plafond de taille appliqué.
