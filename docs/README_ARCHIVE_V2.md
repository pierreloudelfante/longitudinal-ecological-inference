# Guide de lecture de l’archive V2 corrigée

Cette documentation porte sur le gel du 4 août 2026 de `longitudinal_priority_results_v2_corrige_3000_en_cours.zip`.

## Statut en une phrase

La correction des 12 traces historiques et les 12 benchmarks NLS à 3 000 communes sont présents ; la nouvelle production KRT à 3 000 communes est partielle, avec H0A-1962 et H0A-1986 terminés sur 12 fits planifiés.

## Ordre de lecture

1. `RECAPITULATIF_OUTPUTS_ARCHIVE_V2.md` — inventaire exact des outputs et de leur portée ;
2. `ETAT_ARCHIVE_CORRIGEE_3000.md` — état des deux runs KRT à 3 000 inclus ;
3. `PRIORITY_RESULTS_FOR_PROFESSOR_V2.md` — synthèse des résultats et limites ;
4. `METHODE_ECHANTILLONNAGE_PANEL_3000.md` — univers, tirage, équilibre et représentativité ;
5. `PROCESSUS_PROJET_ARCHIVE_V2.md` — chaîne complète des scripts vers les outputs ;
6. `PPC_V2_METHOD.md` — méthode des contrôles prédictifs ;
7. `PRIORITY_CHART_MAP_V2.md` — correspondance entre figures, sources et limites.

## Distinction indispensable

- « historique corrigé » signifie : post-traitement des traces V1 sur 500/494/500 communes ;
- « NLS 3 000 » signifie : benchmark non linéaire sur le panel commun ;
- « KRT 3 000 » signifie : nouvelle estimation bayésienne, dont seulement 2/12 sont dans ce gel.

Les traces NetCDF, les données brutes et les douze Parquet modèle-ready ne sont pas inclus. Cette archive est une livraison de résultats et d’audit, pas un environnement autonome de recalcul.
