# Partitions politiques et sociales sur les 26 scrutins

## Verdict

Le registre contient 292 couples élection–scénario admissibles sur les 15
législatives et 11 présidentielles de 1962 à 2022. La préparation exhaustive à
partir du panel fixe demandé de 3 000 communes donne :

| Famille | Attendues | Matérialisées et valides | Refusées |
|---|---:|---:|---:|
| scénarios 2×2 H0A–H7 | 240 | 240 | 0 |
| scénarios RXC1/RXC2 | 52 | 30 | 22 |
| **total** | **292** | **270** | **22** |

Toutes les tables matérialisées ont des identifiants uniques, des valeurs
non négatives, des parts sociales qui somment à 1 à `1e-10` près et des comptes
sociaux et politiques qui ferment exactement sur `N_g` en nombres entiers.

Les 22 refus ne sont pas des erreurs masquées : RXC1 et RXC2 sont arrêtés sur
11 scrutins dont les cinq blocs politiques bruts diffèrent des exprimés de plus
de la tolérance absolue fixée à `0,01` voix : législatives 1993, 2002, 2007,
2012, 2017 ; présidentielles 1974, 1995, 2007, 2012, 2017, 2022. Aucun arrondi
forcé n'est appliqué à ces sources.

## Contrôle adapté à chaque scénario

Le contrôle porte sur la partition réellement consommée par le modèle :

| Scénario | Marge brute contrôlée | Fermeture construite |
|---|---|---|
| H0A–H0C | `0 ≤ votants ≤ inscrits` | abstention + participation = inscrits |
| H1–H3 | `0 ≤ voteG + voteCG ≤ exprimés` | gauche + complément = exprimés |
| H4 | `0 ≤ voteCD + voteD ≤ exprimés` | droite + complément = exprimés |
| H5 | `0 ≤ voteC ≤ exprimés` | centre + complément = exprimés |
| H6–H7 | colonnes FN/RN déclarées pour le scrutin, comprises dans les exprimés | FN/RN + complément = exprimés |
| RXC1–RXC2 | somme brute de `voteG`, `voteCG`, `voteC`, `voteCD`, `voteD` | fermeture à cinq blocs autorisée seulement si l'écart brut est ≤ 0,01 voix |

Cette distinction empêche une incohérence d'un bloc inutilisé de bloquer H0,
tout en conservant la contrainte stricte pour RXC qui utilise réellement les
cinq colonnes.

## Correspondance formalisme–code

Pour une commune (i), les comptes sociaux bruts (a_{ir}) sont recalés vers
le dénominateur électoral (N_i), puis fermés par plus forts restes :

\[
\widetilde n_{ir}=N_i\frac{a_{ir}}{\sum_s a_{is}},\qquad
\sum_r n_{ir}=N_i.
\]

La validation politique spécifique au scénario est implémentée dans
`code_longitudinal/prepare_inputs.py:67`, fonction
`_validate_raw_political_partition`. La construction des comptes politiques et
sociaux se trouve aux lignes 153 et 178. La fonction
`validate_model_ready`, ligne 183, impose les deux fermetures exactes,
l'unicité et la non-négativité. Le lot qui parcourt les 26 élections sans
interrompre les autres scénarios en cas d'échec est
`code_longitudinal/prepare_all_partitions.py`.

## Preuves et reproduction

- `outputs/all_elections_partition_preparation.json` : statut et erreur brute
  de chacun des 292 couples ;
- `outputs/all_elections_partition_integrity.csv` : contrôle compact,
  élection par élection et scénario par scénario ;
- `outputs/model_ready/` : 270 Parquet, listes d'exclusion et manifestes ;
- `outputs/validation_checks.csv` : contrôles de livraison agrégés.

Commande de reconstruction, avec les archives brutes du dépôt parent :

```powershell
python -m code_longitudinal.prepare_all_partitions --sample-size 3000
```

Une commune absente à une date reste absente et figure parmi les exclusions ;
aucune commune de remplacement n'est tirée.
