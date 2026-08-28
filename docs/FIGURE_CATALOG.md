# Catalogue exhaustif des figures

Ce catalogue est généré par `code_longitudinal/build_figure_catalog.py`. Il indexe les **238 figures SVG** présentes dans `figures/`.
Les PNG du dépôt de travail sont des aperçus ; le ZIP minimal conserve les SVG vectoriels.

## Règles de lecture

- `n` dans un nom est le palier demandé ; le titre donne l’effectif effectivement utilisé.
- Toute figure PyEI issue de 20 draws, 20 tune et une chaîne est une calibration non substantielle, même à n=3 000.
- Les densités principales donnent le même poids à chaque commune et portent sur les moyennes postérieures communales de b_1/b_2.
- Les valeurs numériques reproductibles sont dans les tables sources indiquées sous chaque famille.

## Synthèse par famille

| Famille | SVG | Source principale |
|---|---:|---|
| `densities/comparisons/` — Comparaisons King/KRT | 27 | `outputs/density_joint_data.parquet` |
| `densities/curated/` — Densités principales King/KRT | 28 | `outputs/pilot_density_selection.csv`, `outputs/beta_density_data.parquet` |
| `densities/joint/` — Relations jointes b_1/b_2 | 55 | `outputs/density_joint_data.parquet` |
| `densities/marginal/` — Densités marginales des bêtas | 55 | `outputs/density_marginal_data.parquet` |
| `election_2022/` — Diagnostic mono-élection 2022 | 7 | `outputs/election_2022_input_integrity.csv`, `outputs/election_2022_fit_quality.csv` |
| `illustrated_report/` — Comparaisons du rapport illustré | 5 | `outputs/illustrated_report_estimates.csv` |
| `longitudinal/` — Figures longitudinales | 46 | `outputs/longitudinal_estimates.parquet` |
| `panel_balance/` — Balance du panel | 7 | `panel/panel_balance_checks.csv` |
| `professor_recap/` — Comparaisons canoniques du récapitulatif professeur | 8 | `outputs/professor_canonical_comparisons.csv` |

## Comparaisons King/KRT — `densities/comparisons/` (27)

Source : `outputs/density_joint_data.parquet`

Interprétation : Calibration non substantielle sur l’intersection exacte des communes utilisées.

| Figure | Portée identifiée par le nom |
|---|---|
| [`leg_1962_r1__H0A__king_vs_krt__n3000__f9f15aa719f8.svg`](../figures/densities/comparisons/leg_1962_r1__H0A__king_vs_krt__n3000__f9f15aa719f8.svg) | scrutin `leg_1962_r1`; scénario `H0A`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_1962_r1__H0B__king_vs_krt__n3000__f765c81fa69c.svg`](../figures/densities/comparisons/leg_1962_r1__H0B__king_vs_krt__n3000__f765c81fa69c.svg) | scrutin `leg_1962_r1`; scénario `H0B`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_1962_r1__H0C__king_vs_krt__n3000__3f6d5cddbe57.svg`](../figures/densities/comparisons/leg_1962_r1__H0C__king_vs_krt__n3000__3f6d5cddbe57.svg) | scrutin `leg_1962_r1`; scénario `H0C`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_1962_r1__H1__king_vs_krt__n3000__a7b940298745.svg`](../figures/densities/comparisons/leg_1962_r1__H1__king_vs_krt__n3000__a7b940298745.svg) | scrutin `leg_1962_r1`; scénario `H1`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_1962_r1__H2__king_vs_krt__n3000__28bce788e338.svg`](../figures/densities/comparisons/leg_1962_r1__H2__king_vs_krt__n3000__28bce788e338.svg) | scrutin `leg_1962_r1`; scénario `H2`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_1962_r1__H3__king_vs_krt__n3000__23f924fa9892.svg`](../figures/densities/comparisons/leg_1962_r1__H3__king_vs_krt__n3000__23f924fa9892.svg) | scrutin `leg_1962_r1`; scénario `H3`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_1962_r1__H4__king_vs_krt__n3000__036eb0583c1c.svg`](../figures/densities/comparisons/leg_1962_r1__H4__king_vs_krt__n3000__036eb0583c1c.svg) | scrutin `leg_1962_r1`; scénario `H4`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_1986_r1__H0A__king_vs_krt__n3000__a7c1f854fc1d.svg`](../figures/densities/comparisons/leg_1986_r1__H0A__king_vs_krt__n3000__a7c1f854fc1d.svg) | scrutin `leg_1986_r1`; scénario `H0A`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_1986_r1__H0B__king_vs_krt__n3000__7c9cc9e38f91.svg`](../figures/densities/comparisons/leg_1986_r1__H0B__king_vs_krt__n3000__7c9cc9e38f91.svg) | scrutin `leg_1986_r1`; scénario `H0B`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_1986_r1__H0C__king_vs_krt__n3000__675e322f7a34.svg`](../figures/densities/comparisons/leg_1986_r1__H0C__king_vs_krt__n3000__675e322f7a34.svg) | scrutin `leg_1986_r1`; scénario `H0C`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_1986_r1__H1__king_vs_krt__n3000__83e4ceebc0b4.svg`](../figures/densities/comparisons/leg_1986_r1__H1__king_vs_krt__n3000__83e4ceebc0b4.svg) | scrutin `leg_1986_r1`; scénario `H1`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_1986_r1__H2__king_vs_krt__n3000__2f452f707ea5.svg`](../figures/densities/comparisons/leg_1986_r1__H2__king_vs_krt__n3000__2f452f707ea5.svg) | scrutin `leg_1986_r1`; scénario `H2`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_1986_r1__H3__king_vs_krt__n3000__91e2b0b92125.svg`](../figures/densities/comparisons/leg_1986_r1__H3__king_vs_krt__n3000__91e2b0b92125.svg) | scrutin `leg_1986_r1`; scénario `H3`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_1986_r1__H4__king_vs_krt__n3000__764168d8fbeb.svg`](../figures/densities/comparisons/leg_1986_r1__H4__king_vs_krt__n3000__764168d8fbeb.svg) | scrutin `leg_1986_r1`; scénario `H4`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_1986_r1__H5__king_vs_krt__n3000__6adec5b97c30.svg`](../figures/densities/comparisons/leg_1986_r1__H5__king_vs_krt__n3000__6adec5b97c30.svg) | scrutin `leg_1986_r1`; scénario `H5`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_1986_r1__H6__king_vs_krt__n500__ced175e6a020.svg`](../figures/densities/comparisons/leg_1986_r1__H6__king_vs_krt__n500__ced175e6a020.svg) | scrutin `leg_1986_r1`; scénario `H6`; vue `king_vs_krt`; palier demandé `500` |
| [`leg_1986_r1__H7__king_vs_krt__n25__c2d069cda0a6.svg`](../figures/densities/comparisons/leg_1986_r1__H7__king_vs_krt__n25__c2d069cda0a6.svg) | scrutin `leg_1986_r1`; scénario `H7`; vue `king_vs_krt`; palier demandé `25` |
| [`leg_2022_r1__H0A__king_vs_krt__n3000__e1c03753926c.svg`](../figures/densities/comparisons/leg_2022_r1__H0A__king_vs_krt__n3000__e1c03753926c.svg) | scrutin `leg_2022_r1`; scénario `H0A`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_2022_r1__H0B__king_vs_krt__n3000__07c6b71c7077.svg`](../figures/densities/comparisons/leg_2022_r1__H0B__king_vs_krt__n3000__07c6b71c7077.svg) | scrutin `leg_2022_r1`; scénario `H0B`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_2022_r1__H0C__king_vs_krt__n3000__d455dbc4709c.svg`](../figures/densities/comparisons/leg_2022_r1__H0C__king_vs_krt__n3000__d455dbc4709c.svg) | scrutin `leg_2022_r1`; scénario `H0C`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_2022_r1__H1__king_vs_krt__n3000__bd781e586982.svg`](../figures/densities/comparisons/leg_2022_r1__H1__king_vs_krt__n3000__bd781e586982.svg) | scrutin `leg_2022_r1`; scénario `H1`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_2022_r1__H2__king_vs_krt__n3000__d0fc04399398.svg`](../figures/densities/comparisons/leg_2022_r1__H2__king_vs_krt__n3000__d0fc04399398.svg) | scrutin `leg_2022_r1`; scénario `H2`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_2022_r1__H3__king_vs_krt__n3000__4eccf3192292.svg`](../figures/densities/comparisons/leg_2022_r1__H3__king_vs_krt__n3000__4eccf3192292.svg) | scrutin `leg_2022_r1`; scénario `H3`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_2022_r1__H4__king_vs_krt__n3000__ed8fe0f95b02.svg`](../figures/densities/comparisons/leg_2022_r1__H4__king_vs_krt__n3000__ed8fe0f95b02.svg) | scrutin `leg_2022_r1`; scénario `H4`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_2022_r1__H5__king_vs_krt__n25__c0480636417d.svg`](../figures/densities/comparisons/leg_2022_r1__H5__king_vs_krt__n25__c0480636417d.svg) | scrutin `leg_2022_r1`; scénario `H5`; vue `king_vs_krt`; palier demandé `25` |
| [`leg_2022_r1__H6__king_vs_krt__n3000__4c8888f7a7d0.svg`](../figures/densities/comparisons/leg_2022_r1__H6__king_vs_krt__n3000__4c8888f7a7d0.svg) | scrutin `leg_2022_r1`; scénario `H6`; vue `king_vs_krt`; palier demandé `3000` |
| [`leg_2022_r1__H7__king_vs_krt__n3000__777a65b9ac8e.svg`](../figures/densities/comparisons/leg_2022_r1__H7__king_vs_krt__n3000__777a65b9ac8e.svg) | scrutin `leg_2022_r1`; scénario `H7`; vue `king_vs_krt`; palier demandé `3000` |

## Densités principales King/KRT — `densities/curated/` (28)

Source : `outputs/pilot_density_selection.csv`, `outputs/beta_density_data.parquet`

Interprétation : Calibration non substantielle : une commune = un poids, plus grand palier commun ou vue native explicitée.

| Figure | Portée identifiée par le nom |
|---|---|
| [`density_overlay__leg_1962_r1__H0A__n3000.svg`](../figures/densities/curated/density_overlay__leg_1962_r1__H0A__n3000.svg) | scrutin `leg_1962_r1`; scénario `H0A`; palier demandé `3000` |
| [`density_overlay__leg_1962_r1__H0B__n3000.svg`](../figures/densities/curated/density_overlay__leg_1962_r1__H0B__n3000.svg) | scrutin `leg_1962_r1`; scénario `H0B`; palier demandé `3000` |
| [`density_overlay__leg_1962_r1__H0C__n3000.svg`](../figures/densities/curated/density_overlay__leg_1962_r1__H0C__n3000.svg) | scrutin `leg_1962_r1`; scénario `H0C`; palier demandé `3000` |
| [`density_overlay__leg_1962_r1__H1__n3000.svg`](../figures/densities/curated/density_overlay__leg_1962_r1__H1__n3000.svg) | scrutin `leg_1962_r1`; scénario `H1`; palier demandé `3000` |
| [`density_overlay__leg_1962_r1__H2__n3000.svg`](../figures/densities/curated/density_overlay__leg_1962_r1__H2__n3000.svg) | scrutin `leg_1962_r1`; scénario `H2`; palier demandé `3000` |
| [`density_overlay__leg_1962_r1__H3__n3000.svg`](../figures/densities/curated/density_overlay__leg_1962_r1__H3__n3000.svg) | scrutin `leg_1962_r1`; scénario `H3`; palier demandé `3000` |
| [`density_overlay__leg_1962_r1__H4__n3000.svg`](../figures/densities/curated/density_overlay__leg_1962_r1__H4__n3000.svg) | scrutin `leg_1962_r1`; scénario `H4`; palier demandé `3000` |
| [`density_overlay__leg_1962_r1__H5__n3000.svg`](../figures/densities/curated/density_overlay__leg_1962_r1__H5__n3000.svg) | scrutin `leg_1962_r1`; scénario `H5`; palier demandé `3000` |
| [`density_overlay__leg_1986_r1__H0A__n3000.svg`](../figures/densities/curated/density_overlay__leg_1986_r1__H0A__n3000.svg) | scrutin `leg_1986_r1`; scénario `H0A`; palier demandé `3000` |
| [`density_overlay__leg_1986_r1__H0B__n3000.svg`](../figures/densities/curated/density_overlay__leg_1986_r1__H0B__n3000.svg) | scrutin `leg_1986_r1`; scénario `H0B`; palier demandé `3000` |
| [`density_overlay__leg_1986_r1__H0C__n3000.svg`](../figures/densities/curated/density_overlay__leg_1986_r1__H0C__n3000.svg) | scrutin `leg_1986_r1`; scénario `H0C`; palier demandé `3000` |
| [`density_overlay__leg_1986_r1__H1__n3000.svg`](../figures/densities/curated/density_overlay__leg_1986_r1__H1__n3000.svg) | scrutin `leg_1986_r1`; scénario `H1`; palier demandé `3000` |
| [`density_overlay__leg_1986_r1__H2__n3000.svg`](../figures/densities/curated/density_overlay__leg_1986_r1__H2__n3000.svg) | scrutin `leg_1986_r1`; scénario `H2`; palier demandé `3000` |
| [`density_overlay__leg_1986_r1__H3__n3000.svg`](../figures/densities/curated/density_overlay__leg_1986_r1__H3__n3000.svg) | scrutin `leg_1986_r1`; scénario `H3`; palier demandé `3000` |
| [`density_overlay__leg_1986_r1__H4__n3000.svg`](../figures/densities/curated/density_overlay__leg_1986_r1__H4__n3000.svg) | scrutin `leg_1986_r1`; scénario `H4`; palier demandé `3000` |
| [`density_overlay__leg_1986_r1__H5__n3000.svg`](../figures/densities/curated/density_overlay__leg_1986_r1__H5__n3000.svg) | scrutin `leg_1986_r1`; scénario `H5`; palier demandé `3000` |
| [`density_overlay__leg_1986_r1__H6__n500.svg`](../figures/densities/curated/density_overlay__leg_1986_r1__H6__n500.svg) | scrutin `leg_1986_r1`; scénario `H6`; palier demandé `500` |
| [`density_overlay__leg_1986_r1__H7__n25.svg`](../figures/densities/curated/density_overlay__leg_1986_r1__H7__n25.svg) | scrutin `leg_1986_r1`; scénario `H7`; palier demandé `25` |
| [`density_overlay__leg_2022_r1__H0A__n3000.svg`](../figures/densities/curated/density_overlay__leg_2022_r1__H0A__n3000.svg) | scrutin `leg_2022_r1`; scénario `H0A`; palier demandé `3000` |
| [`density_overlay__leg_2022_r1__H0B__n3000.svg`](../figures/densities/curated/density_overlay__leg_2022_r1__H0B__n3000.svg) | scrutin `leg_2022_r1`; scénario `H0B`; palier demandé `3000` |
| [`density_overlay__leg_2022_r1__H0C__n3000.svg`](../figures/densities/curated/density_overlay__leg_2022_r1__H0C__n3000.svg) | scrutin `leg_2022_r1`; scénario `H0C`; palier demandé `3000` |
| [`density_overlay__leg_2022_r1__H1__n3000.svg`](../figures/densities/curated/density_overlay__leg_2022_r1__H1__n3000.svg) | scrutin `leg_2022_r1`; scénario `H1`; palier demandé `3000` |
| [`density_overlay__leg_2022_r1__H2__n3000.svg`](../figures/densities/curated/density_overlay__leg_2022_r1__H2__n3000.svg) | scrutin `leg_2022_r1`; scénario `H2`; palier demandé `3000` |
| [`density_overlay__leg_2022_r1__H3__n3000.svg`](../figures/densities/curated/density_overlay__leg_2022_r1__H3__n3000.svg) | scrutin `leg_2022_r1`; scénario `H3`; palier demandé `3000` |
| [`density_overlay__leg_2022_r1__H4__n3000.svg`](../figures/densities/curated/density_overlay__leg_2022_r1__H4__n3000.svg) | scrutin `leg_2022_r1`; scénario `H4`; palier demandé `3000` |
| [`density_overlay__leg_2022_r1__H5__n25.svg`](../figures/densities/curated/density_overlay__leg_2022_r1__H5__n25.svg) | scrutin `leg_2022_r1`; scénario `H5`; palier demandé `25` |
| [`density_overlay__leg_2022_r1__H6__n3000.svg`](../figures/densities/curated/density_overlay__leg_2022_r1__H6__n3000.svg) | scrutin `leg_2022_r1`; scénario `H6`; palier demandé `3000` |
| [`density_overlay__leg_2022_r1__H7__n3000.svg`](../figures/densities/curated/density_overlay__leg_2022_r1__H7__n3000.svg) | scrutin `leg_2022_r1`; scénario `H7`; palier demandé `3000` |

## Relations jointes b_1/b_2 — `densities/joint/` (55)

Source : `outputs/density_joint_data.parquet`

Interprétation : Calibration non substantielle ; vue native ou intersection exacte selon le nom.

| Figure | Portée identifiée par le nom |
|---|---|
| [`leg_1962_r1__H0A__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_1962_r1__H0A__king_truncated_normal__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H0A`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H0A__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_1962_r1__H0A__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H0A`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H0B__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_1962_r1__H0B__king_truncated_normal__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H0B`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H0B__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_1962_r1__H0B__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H0B`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H0C__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_1962_r1__H0C__king_truncated_normal__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H0C`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H0C__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_1962_r1__H0C__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H0C`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H1__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_1962_r1__H1__king_truncated_normal__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H1`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H1__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_1962_r1__H1__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H1`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H2__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_1962_r1__H2__king_truncated_normal__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H2`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H2__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_1962_r1__H2__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H2`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H3__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_1962_r1__H3__king_truncated_normal__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H3`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H3__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_1962_r1__H3__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H3`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H4__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_1962_r1__H4__king_truncated_normal__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H4`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H4__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_1962_r1__H4__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H4`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H5__krt_beta_binomial__n3000.svg`](../figures/densities/joint/leg_1962_r1__H5__krt_beta_binomial__n3000.svg) | scrutin `leg_1962_r1`; scénario `H5`; modèle `krt_beta_binomial`; palier demandé `3000` |
| [`leg_1986_r1__H0A__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_1986_r1__H0A__king_truncated_normal__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H0A`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H0A__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_1986_r1__H0A__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H0A`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H0B__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_1986_r1__H0B__king_truncated_normal__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H0B`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H0B__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_1986_r1__H0B__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H0B`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H0C__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_1986_r1__H0C__king_truncated_normal__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H0C`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H0C__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_1986_r1__H0C__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H0C`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H1__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_1986_r1__H1__king_truncated_normal__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H1`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H1__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_1986_r1__H1__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H1`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H2__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_1986_r1__H2__king_truncated_normal__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H2`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H2__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_1986_r1__H2__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H2`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H3__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_1986_r1__H3__king_truncated_normal__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H3`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H3__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_1986_r1__H3__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H3`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H4__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_1986_r1__H4__king_truncated_normal__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H4`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H4__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_1986_r1__H4__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H4`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H5__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_1986_r1__H5__king_truncated_normal__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H5`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H5__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_1986_r1__H5__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H5`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H6__king_truncated_normal__common__n500.svg`](../figures/densities/joint/leg_1986_r1__H6__king_truncated_normal__common__n500.svg) | scrutin `leg_1986_r1`; scénario `H6`; modèle `king_truncated_normal`; vue `common`; palier demandé `500` |
| [`leg_1986_r1__H6__krt_beta_binomial__common__n500.svg`](../figures/densities/joint/leg_1986_r1__H6__krt_beta_binomial__common__n500.svg) | scrutin `leg_1986_r1`; scénario `H6`; modèle `krt_beta_binomial`; vue `common`; palier demandé `500` |
| [`leg_1986_r1__H7__king_truncated_normal__common__n25.svg`](../figures/densities/joint/leg_1986_r1__H7__king_truncated_normal__common__n25.svg) | scrutin `leg_1986_r1`; scénario `H7`; modèle `king_truncated_normal`; vue `common`; palier demandé `25` |
| [`leg_1986_r1__H7__krt_beta_binomial__common__n25.svg`](../figures/densities/joint/leg_1986_r1__H7__krt_beta_binomial__common__n25.svg) | scrutin `leg_1986_r1`; scénario `H7`; modèle `krt_beta_binomial`; vue `common`; palier demandé `25` |
| [`leg_2022_r1__H0A__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_2022_r1__H0A__king_truncated_normal__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H0A`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H0A__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_2022_r1__H0A__krt_beta_binomial__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H0A`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H0B__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_2022_r1__H0B__king_truncated_normal__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H0B`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H0B__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_2022_r1__H0B__krt_beta_binomial__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H0B`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H0C__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_2022_r1__H0C__king_truncated_normal__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H0C`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H0C__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_2022_r1__H0C__krt_beta_binomial__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H0C`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H1__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_2022_r1__H1__king_truncated_normal__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H1`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H1__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_2022_r1__H1__krt_beta_binomial__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H1`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H2__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_2022_r1__H2__king_truncated_normal__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H2`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H2__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_2022_r1__H2__krt_beta_binomial__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H2`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H3__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_2022_r1__H3__king_truncated_normal__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H3`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H3__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_2022_r1__H3__krt_beta_binomial__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H3`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H4__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_2022_r1__H4__king_truncated_normal__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H4`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H4__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_2022_r1__H4__krt_beta_binomial__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H4`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H5__king_truncated_normal__common__n25.svg`](../figures/densities/joint/leg_2022_r1__H5__king_truncated_normal__common__n25.svg) | scrutin `leg_2022_r1`; scénario `H5`; modèle `king_truncated_normal`; vue `common`; palier demandé `25` |
| [`leg_2022_r1__H5__krt_beta_binomial__common__n25.svg`](../figures/densities/joint/leg_2022_r1__H5__krt_beta_binomial__common__n25.svg) | scrutin `leg_2022_r1`; scénario `H5`; modèle `krt_beta_binomial`; vue `common`; palier demandé `25` |
| [`leg_2022_r1__H6__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_2022_r1__H6__king_truncated_normal__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H6`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H6__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_2022_r1__H6__krt_beta_binomial__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H6`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H7__king_truncated_normal__common__n3000.svg`](../figures/densities/joint/leg_2022_r1__H7__king_truncated_normal__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H7`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H7__krt_beta_binomial__common__n3000.svg`](../figures/densities/joint/leg_2022_r1__H7__krt_beta_binomial__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H7`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |

## Densités marginales des bêtas — `densities/marginal/` (55)

Source : `outputs/density_marginal_data.parquet`

Interprétation : Calibration non substantielle ; moyenne postérieure communale de b_1 ou b_2.

| Figure | Portée identifiée par le nom |
|---|---|
| [`leg_1962_r1__H0A__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_1962_r1__H0A__king_truncated_normal__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H0A`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H0A__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_1962_r1__H0A__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H0A`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H0B__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_1962_r1__H0B__king_truncated_normal__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H0B`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H0B__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_1962_r1__H0B__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H0B`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H0C__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_1962_r1__H0C__king_truncated_normal__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H0C`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H0C__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_1962_r1__H0C__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H0C`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H1__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_1962_r1__H1__king_truncated_normal__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H1`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H1__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_1962_r1__H1__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H1`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H2__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_1962_r1__H2__king_truncated_normal__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H2`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H2__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_1962_r1__H2__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H2`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H3__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_1962_r1__H3__king_truncated_normal__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H3`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H3__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_1962_r1__H3__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H3`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H4__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_1962_r1__H4__king_truncated_normal__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H4`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H4__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_1962_r1__H4__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1962_r1`; scénario `H4`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1962_r1__H5__krt_beta_binomial__n3000.svg`](../figures/densities/marginal/leg_1962_r1__H5__krt_beta_binomial__n3000.svg) | scrutin `leg_1962_r1`; scénario `H5`; modèle `krt_beta_binomial`; palier demandé `3000` |
| [`leg_1986_r1__H0A__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_1986_r1__H0A__king_truncated_normal__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H0A`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H0A__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_1986_r1__H0A__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H0A`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H0B__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_1986_r1__H0B__king_truncated_normal__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H0B`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H0B__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_1986_r1__H0B__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H0B`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H0C__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_1986_r1__H0C__king_truncated_normal__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H0C`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H0C__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_1986_r1__H0C__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H0C`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H1__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_1986_r1__H1__king_truncated_normal__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H1`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H1__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_1986_r1__H1__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H1`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H2__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_1986_r1__H2__king_truncated_normal__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H2`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H2__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_1986_r1__H2__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H2`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H3__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_1986_r1__H3__king_truncated_normal__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H3`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H3__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_1986_r1__H3__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H3`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H4__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_1986_r1__H4__king_truncated_normal__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H4`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H4__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_1986_r1__H4__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H4`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H5__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_1986_r1__H5__king_truncated_normal__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H5`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H5__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_1986_r1__H5__krt_beta_binomial__common__n3000.svg) | scrutin `leg_1986_r1`; scénario `H5`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_1986_r1__H6__king_truncated_normal__common__n500.svg`](../figures/densities/marginal/leg_1986_r1__H6__king_truncated_normal__common__n500.svg) | scrutin `leg_1986_r1`; scénario `H6`; modèle `king_truncated_normal`; vue `common`; palier demandé `500` |
| [`leg_1986_r1__H6__krt_beta_binomial__common__n500.svg`](../figures/densities/marginal/leg_1986_r1__H6__krt_beta_binomial__common__n500.svg) | scrutin `leg_1986_r1`; scénario `H6`; modèle `krt_beta_binomial`; vue `common`; palier demandé `500` |
| [`leg_1986_r1__H7__king_truncated_normal__common__n25.svg`](../figures/densities/marginal/leg_1986_r1__H7__king_truncated_normal__common__n25.svg) | scrutin `leg_1986_r1`; scénario `H7`; modèle `king_truncated_normal`; vue `common`; palier demandé `25` |
| [`leg_1986_r1__H7__krt_beta_binomial__common__n25.svg`](../figures/densities/marginal/leg_1986_r1__H7__krt_beta_binomial__common__n25.svg) | scrutin `leg_1986_r1`; scénario `H7`; modèle `krt_beta_binomial`; vue `common`; palier demandé `25` |
| [`leg_2022_r1__H0A__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_2022_r1__H0A__king_truncated_normal__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H0A`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H0A__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_2022_r1__H0A__krt_beta_binomial__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H0A`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H0B__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_2022_r1__H0B__king_truncated_normal__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H0B`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H0B__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_2022_r1__H0B__krt_beta_binomial__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H0B`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H0C__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_2022_r1__H0C__king_truncated_normal__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H0C`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H0C__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_2022_r1__H0C__krt_beta_binomial__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H0C`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H1__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_2022_r1__H1__king_truncated_normal__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H1`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H1__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_2022_r1__H1__krt_beta_binomial__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H1`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H2__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_2022_r1__H2__king_truncated_normal__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H2`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H2__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_2022_r1__H2__krt_beta_binomial__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H2`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H3__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_2022_r1__H3__king_truncated_normal__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H3`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H3__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_2022_r1__H3__krt_beta_binomial__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H3`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H4__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_2022_r1__H4__king_truncated_normal__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H4`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H4__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_2022_r1__H4__krt_beta_binomial__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H4`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H5__king_truncated_normal__common__n25.svg`](../figures/densities/marginal/leg_2022_r1__H5__king_truncated_normal__common__n25.svg) | scrutin `leg_2022_r1`; scénario `H5`; modèle `king_truncated_normal`; vue `common`; palier demandé `25` |
| [`leg_2022_r1__H5__krt_beta_binomial__common__n25.svg`](../figures/densities/marginal/leg_2022_r1__H5__krt_beta_binomial__common__n25.svg) | scrutin `leg_2022_r1`; scénario `H5`; modèle `krt_beta_binomial`; vue `common`; palier demandé `25` |
| [`leg_2022_r1__H6__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_2022_r1__H6__king_truncated_normal__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H6`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H6__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_2022_r1__H6__krt_beta_binomial__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H6`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H7__king_truncated_normal__common__n3000.svg`](../figures/densities/marginal/leg_2022_r1__H7__king_truncated_normal__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H7`; modèle `king_truncated_normal`; vue `common`; palier demandé `3000` |
| [`leg_2022_r1__H7__krt_beta_binomial__common__n3000.svg`](../figures/densities/marginal/leg_2022_r1__H7__krt_beta_binomial__common__n3000.svg) | scrutin `leg_2022_r1`; scénario `H7`; modèle `krt_beta_binomial`; vue `common`; palier demandé `3000` |

## Diagnostic mono-élection 2022 — `election_2022/` (7)

Source : `outputs/election_2022_input_integrity.csv`, `outputs/election_2022_fit_quality.csv`

Interprétation : Figures d’intégrité et d’ajustement ; les NLS sans intervalle ne portent pas d’incertitude validée.

| Figure | Portée identifiée par le nom |
|---|---|
| [`input_margins__all_2x2_scenarios.svg`](../figures/election_2022/input_margins__all_2x2_scenarios.svg) | vue `all_2x2_scenarios` |
| [`nls_composition__RXC1.svg`](../figures/election_2022/nls_composition__RXC1.svg) | scénario `RXC1` |
| [`nls_composition__RXC2.svg`](../figures/election_2022/nls_composition__RXC2.svg) | scénario `RXC2` |
| [`nls_observed_vs_predicted__RXC1.svg`](../figures/election_2022/nls_observed_vs_predicted__RXC1.svg) | scénario `RXC1` |
| [`nls_observed_vs_predicted__RXC2.svg`](../figures/election_2022/nls_observed_vs_predicted__RXC2.svg) | scénario `RXC2` |
| [`nls_probability_matrix__RXC1.svg`](../figures/election_2022/nls_probability_matrix__RXC1.svg) | scénario `RXC1` |
| [`nls_probability_matrix__RXC2.svg`](../figures/election_2022/nls_probability_matrix__RXC2.svg) | scénario `RXC2` |

## Comparaisons du rapport illustré — `illustrated_report/` (5)

Source : `outputs/illustrated_report_estimates.csv`

Interprétation : Comparaisons descriptives ; les PyEI 20/20/1 restent non substantiels.

| Figure | Portée identifiée par le nom |
|---|---|
| [`comparison_interannuelle__H0A.svg`](../figures/illustrated_report/comparison_interannuelle__H0A.svg) | scénario `H0A` |
| [`comparison_interannuelle__H1.svg`](../figures/illustrated_report/comparison_interannuelle__H1.svg) | scénario `H1` |
| [`comparison_interannuelle__H5.svg`](../figures/illustrated_report/comparison_interannuelle__H5.svg) | scénario `H5` |
| [`comparison_interannuelle__H6.svg`](../figures/illustrated_report/comparison_interannuelle__H6.svg) | scénario `H6` |
| [`comparison_interannuelle__H7.svg`](../figures/illustrated_report/comparison_interannuelle__H7.svg) | scénario `H7` |

## Figures longitudinales — `longitudinal/` (46)

Source : `outputs/longitudinal_estimates.parquet`

Interprétation : Séparer législatives et présidentielles ; vérifier le modèle et son statut diagnostique avant interprétation.

| Figure | Portée identifiée par le nom |
|---|---|
| [`gap__H0A__king_truncated_normal__legislative.svg`](../figures/longitudinal/gap__H0A__king_truncated_normal__legislative.svg) | scénario `H0A`; modèle `king_truncated_normal`; vue `legislative` |
| [`gap__H0A__krt_beta_binomial__legislative.svg`](../figures/longitudinal/gap__H0A__krt_beta_binomial__legislative.svg) | scénario `H0A`; modèle `krt_beta_binomial`; vue `legislative` |
| [`gap__H0B__king_truncated_normal__legislative.svg`](../figures/longitudinal/gap__H0B__king_truncated_normal__legislative.svg) | scénario `H0B`; modèle `king_truncated_normal`; vue `legislative` |
| [`gap__H0B__krt_beta_binomial__legislative.svg`](../figures/longitudinal/gap__H0B__krt_beta_binomial__legislative.svg) | scénario `H0B`; modèle `krt_beta_binomial`; vue `legislative` |
| [`gap__H0C__king_truncated_normal__legislative.svg`](../figures/longitudinal/gap__H0C__king_truncated_normal__legislative.svg) | scénario `H0C`; modèle `king_truncated_normal`; vue `legislative` |
| [`gap__H0C__krt_beta_binomial__legislative.svg`](../figures/longitudinal/gap__H0C__krt_beta_binomial__legislative.svg) | scénario `H0C`; modèle `krt_beta_binomial`; vue `legislative` |
| [`gap__H1__king_truncated_normal__legislative.svg`](../figures/longitudinal/gap__H1__king_truncated_normal__legislative.svg) | scénario `H1`; modèle `king_truncated_normal`; vue `legislative` |
| [`gap__H1__krt_beta_binomial__legislative.svg`](../figures/longitudinal/gap__H1__krt_beta_binomial__legislative.svg) | scénario `H1`; modèle `krt_beta_binomial`; vue `legislative` |
| [`gap__H2__king_truncated_normal__legislative.svg`](../figures/longitudinal/gap__H2__king_truncated_normal__legislative.svg) | scénario `H2`; modèle `king_truncated_normal`; vue `legislative` |
| [`gap__H2__krt_beta_binomial__legislative.svg`](../figures/longitudinal/gap__H2__krt_beta_binomial__legislative.svg) | scénario `H2`; modèle `krt_beta_binomial`; vue `legislative` |
| [`gap__H3__king_truncated_normal__legislative.svg`](../figures/longitudinal/gap__H3__king_truncated_normal__legislative.svg) | scénario `H3`; modèle `king_truncated_normal`; vue `legislative` |
| [`gap__H3__krt_beta_binomial__legislative.svg`](../figures/longitudinal/gap__H3__krt_beta_binomial__legislative.svg) | scénario `H3`; modèle `krt_beta_binomial`; vue `legislative` |
| [`gap__H4__king_truncated_normal__legislative.svg`](../figures/longitudinal/gap__H4__king_truncated_normal__legislative.svg) | scénario `H4`; modèle `king_truncated_normal`; vue `legislative` |
| [`gap__H4__krt_beta_binomial__legislative.svg`](../figures/longitudinal/gap__H4__krt_beta_binomial__legislative.svg) | scénario `H4`; modèle `krt_beta_binomial`; vue `legislative` |
| [`gap__H5__king_truncated_normal__legislative.svg`](../figures/longitudinal/gap__H5__king_truncated_normal__legislative.svg) | scénario `H5`; modèle `king_truncated_normal`; vue `legislative` |
| [`gap__H5__krt_beta_binomial__legislative.svg`](../figures/longitudinal/gap__H5__krt_beta_binomial__legislative.svg) | scénario `H5`; modèle `krt_beta_binomial`; vue `legislative` |
| [`gap__H6__king_truncated_normal__legislative.svg`](../figures/longitudinal/gap__H6__king_truncated_normal__legislative.svg) | scénario `H6`; modèle `king_truncated_normal`; vue `legislative` |
| [`gap__H6__krt_beta_binomial__legislative.svg`](../figures/longitudinal/gap__H6__krt_beta_binomial__legislative.svg) | scénario `H6`; modèle `krt_beta_binomial`; vue `legislative` |
| [`gap__H7__king_truncated_normal__legislative.svg`](../figures/longitudinal/gap__H7__king_truncated_normal__legislative.svg) | scénario `H7`; modèle `king_truncated_normal`; vue `legislative` |
| [`gap__H7__krt_beta_binomial__legislative.svg`](../figures/longitudinal/gap__H7__krt_beta_binomial__legislative.svg) | scénario `H7`; modèle `krt_beta_binomial`; vue `legislative` |
| [`gap__RXC1__rosen_multinomial_dirichlet__legislative.svg`](../figures/longitudinal/gap__RXC1__rosen_multinomial_dirichlet__legislative.svg) | scénario `RXC1`; vue `rosen_multinomial_dirichlet`; vue `legislative` |
| [`gap__RXC1__rosen_nls__legislative.svg`](../figures/longitudinal/gap__RXC1__rosen_nls__legislative.svg) | scénario `RXC1`; modèle `rosen_nls`; vue `legislative` |
| [`gap__RXC2__rosen_nls__legislative.svg`](../figures/longitudinal/gap__RXC2__rosen_nls__legislative.svg) | scénario `RXC2`; modèle `rosen_nls`; vue `legislative` |
| [`probabilities__H0A__king_truncated_normal__legislative.svg`](../figures/longitudinal/probabilities__H0A__king_truncated_normal__legislative.svg) | scénario `H0A`; modèle `king_truncated_normal`; vue `legislative` |
| [`probabilities__H0A__krt_beta_binomial__legislative.svg`](../figures/longitudinal/probabilities__H0A__krt_beta_binomial__legislative.svg) | scénario `H0A`; modèle `krt_beta_binomial`; vue `legislative` |
| [`probabilities__H0B__king_truncated_normal__legislative.svg`](../figures/longitudinal/probabilities__H0B__king_truncated_normal__legislative.svg) | scénario `H0B`; modèle `king_truncated_normal`; vue `legislative` |
| [`probabilities__H0B__krt_beta_binomial__legislative.svg`](../figures/longitudinal/probabilities__H0B__krt_beta_binomial__legislative.svg) | scénario `H0B`; modèle `krt_beta_binomial`; vue `legislative` |
| [`probabilities__H0C__king_truncated_normal__legislative.svg`](../figures/longitudinal/probabilities__H0C__king_truncated_normal__legislative.svg) | scénario `H0C`; modèle `king_truncated_normal`; vue `legislative` |
| [`probabilities__H0C__krt_beta_binomial__legislative.svg`](../figures/longitudinal/probabilities__H0C__krt_beta_binomial__legislative.svg) | scénario `H0C`; modèle `krt_beta_binomial`; vue `legislative` |
| [`probabilities__H1__king_truncated_normal__legislative.svg`](../figures/longitudinal/probabilities__H1__king_truncated_normal__legislative.svg) | scénario `H1`; modèle `king_truncated_normal`; vue `legislative` |
| [`probabilities__H1__krt_beta_binomial__legislative.svg`](../figures/longitudinal/probabilities__H1__krt_beta_binomial__legislative.svg) | scénario `H1`; modèle `krt_beta_binomial`; vue `legislative` |
| [`probabilities__H2__king_truncated_normal__legislative.svg`](../figures/longitudinal/probabilities__H2__king_truncated_normal__legislative.svg) | scénario `H2`; modèle `king_truncated_normal`; vue `legislative` |
| [`probabilities__H2__krt_beta_binomial__legislative.svg`](../figures/longitudinal/probabilities__H2__krt_beta_binomial__legislative.svg) | scénario `H2`; modèle `krt_beta_binomial`; vue `legislative` |
| [`probabilities__H3__king_truncated_normal__legislative.svg`](../figures/longitudinal/probabilities__H3__king_truncated_normal__legislative.svg) | scénario `H3`; modèle `king_truncated_normal`; vue `legislative` |
| [`probabilities__H3__krt_beta_binomial__legislative.svg`](../figures/longitudinal/probabilities__H3__krt_beta_binomial__legislative.svg) | scénario `H3`; modèle `krt_beta_binomial`; vue `legislative` |
| [`probabilities__H4__king_truncated_normal__legislative.svg`](../figures/longitudinal/probabilities__H4__king_truncated_normal__legislative.svg) | scénario `H4`; modèle `king_truncated_normal`; vue `legislative` |
| [`probabilities__H4__krt_beta_binomial__legislative.svg`](../figures/longitudinal/probabilities__H4__krt_beta_binomial__legislative.svg) | scénario `H4`; modèle `krt_beta_binomial`; vue `legislative` |
| [`probabilities__H5__king_truncated_normal__legislative.svg`](../figures/longitudinal/probabilities__H5__king_truncated_normal__legislative.svg) | scénario `H5`; modèle `king_truncated_normal`; vue `legislative` |
| [`probabilities__H5__krt_beta_binomial__legislative.svg`](../figures/longitudinal/probabilities__H5__krt_beta_binomial__legislative.svg) | scénario `H5`; modèle `krt_beta_binomial`; vue `legislative` |
| [`probabilities__H6__king_truncated_normal__legislative.svg`](../figures/longitudinal/probabilities__H6__king_truncated_normal__legislative.svg) | scénario `H6`; modèle `king_truncated_normal`; vue `legislative` |
| [`probabilities__H6__krt_beta_binomial__legislative.svg`](../figures/longitudinal/probabilities__H6__krt_beta_binomial__legislative.svg) | scénario `H6`; modèle `krt_beta_binomial`; vue `legislative` |
| [`probabilities__H7__king_truncated_normal__legislative.svg`](../figures/longitudinal/probabilities__H7__king_truncated_normal__legislative.svg) | scénario `H7`; modèle `king_truncated_normal`; vue `legislative` |
| [`probabilities__H7__krt_beta_binomial__legislative.svg`](../figures/longitudinal/probabilities__H7__krt_beta_binomial__legislative.svg) | scénario `H7`; modèle `krt_beta_binomial`; vue `legislative` |
| [`probabilities__RXC1__rosen_multinomial_dirichlet__legislative.svg`](../figures/longitudinal/probabilities__RXC1__rosen_multinomial_dirichlet__legislative.svg) | scénario `RXC1`; vue `rosen_multinomial_dirichlet`; vue `legislative` |
| [`probabilities__RXC1__rosen_nls__legislative.svg`](../figures/longitudinal/probabilities__RXC1__rosen_nls__legislative.svg) | scénario `RXC1`; modèle `rosen_nls`; vue `legislative` |
| [`probabilities__RXC2__rosen_nls__legislative.svg`](../figures/longitudinal/probabilities__RXC2__rosen_nls__legislative.svg) | scénario `RXC2`; modèle `rosen_nls`; vue `legislative` |

## Balance du panel — `panel_balance/` (7)

Source : `panel/panel_balance_checks.csv`

Interprétation : Diagnostic descriptif de représentativité du tirage fixe 2022.

| Figure | Portée identifiée par le nom |
|---|---|
| [`categorical__region13.svg`](../figures/panel_balance/categorical__region13.svg) | vue `region13` |
| [`categorical__vbbm.svg`](../figures/panel_balance/categorical__vbbm.svg) | vue `vbbm` |
| [`continuous__log1p_inscrits.svg`](../figures/panel_balance/continuous__log1p_inscrits.svg) | vue `log1p_inscrits` |
| [`continuous__share_agri_indp.svg`](../figures/panel_balance/continuous__share_agri_indp.svg) | vue `share_agri_indp` |
| [`continuous__share_cadr.svg`](../figures/panel_balance/continuous__share_cadr.svg) | vue `share_cadr` |
| [`continuous__share_empl.svg`](../figures/panel_balance/continuous__share_empl.svg) | vue `share_empl` |
| [`continuous__share_ouvr.svg`](../figures/panel_balance/continuous__share_ouvr.svg) | vue `share_ouvr` |

## Comparaisons canoniques du récapitulatif professeur — `professor_recap/` (8)

Source : `outputs/professor_canonical_comparisons.csv`

Interprétation : Trois coupes discrètes ; moyenne communale et P25–P75 entre communes, sans interprétation causale.

| Figure | Portée identifiée par le nom |
|---|---|
| [`comparison_interannuelle__H0A.svg`](../figures/professor_recap/comparison_interannuelle__H0A.svg) | scénario `H0A` |
| [`comparison_interannuelle__H0B.svg`](../figures/professor_recap/comparison_interannuelle__H0B.svg) | scénario `H0B` |
| [`comparison_interannuelle__H0C.svg`](../figures/professor_recap/comparison_interannuelle__H0C.svg) | scénario `H0C` |
| [`comparison_interannuelle__H1.svg`](../figures/professor_recap/comparison_interannuelle__H1.svg) | scénario `H1` |
| [`comparison_interannuelle__H2.svg`](../figures/professor_recap/comparison_interannuelle__H2.svg) | scénario `H2` |
| [`comparison_interannuelle__H3.svg`](../figures/professor_recap/comparison_interannuelle__H3.svg) | scénario `H3` |
| [`comparison_interannuelle__H4.svg`](../figures/professor_recap/comparison_interannuelle__H4.svg) | scénario `H4` |
| [`comparison_interannuelle__H5.svg`](../figures/professor_recap/comparison_interannuelle__H5.svg) | scénario `H5` |
