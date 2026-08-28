# Carte des figures V2

| Figure | Question | Forme | Source | Limite |
| --- | --- | --- | --- | --- |
| `corrected_H0A_v2` | Quels niveaux H0A après correction des poids ? | points + intervalles | `corrected_estimates_v2.csv` | traces V1, panel 500/494/500 |
| `corrected_H1_v2` | Quels niveaux H1 après correction des poids ? | points + intervalles | `corrected_estimates_v2.csv` | traces V1, panel 500/494/500 |
| `aggregation_correction_shift_v2` | De combien le mauvais dénominateur déplaçait-il les résultats ? | barres divergentes | `aggregate_comparison_v2.csv` | comparaison historique seulement |
| `within_period_contrasts_v2` | β₁−β₂ est-il positif ou négatif ? | points + intervalles | `within_period_contrasts_v2.csv` | l’inférence reste écologique |
| `official_diagnostics_v2` | Quels runs passent le verdict complet ? | nuage R-hat/ESS | `official_diagnostics_v2.csv` | BFMI et raisons dans le tableau |
| `figures/v2/ppc_krt/*` | Le modèle reproduit-il les marges observées ? | PPC quatre panneaux | `outputs/v2/ppc_krt/*` | calibration ≠ identification |
| `figures/v2/densities/*` | Comment (β₁,β₂) varie-t-il entre périodes ? | KDE commune + HDR | `priority_joint_beta_data.csv` | moyenne postérieure par commune |
