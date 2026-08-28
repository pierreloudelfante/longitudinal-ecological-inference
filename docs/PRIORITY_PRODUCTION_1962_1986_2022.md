# Production MCMC prioritaire — législatives 1962, 1986 et 2022

## Périmètre

- Hypothèses principales : H0A, H1, H2 et H4 (quatre par année).
- Modèles : King — normale tronquée et KRT — bêta-binomial.
- Paramètres : 4 chaînes, 1 000 tune, 1 000 draws par chaîne, `target_accept=0,99`, profondeur d'arbre maximale 12.
- Taille du panel demandée : 500 communes.

## Verdict diagnostique

1/2 ajustements passent simultanément les critères : zéro divergence, R-hat max ≤ 1,01,
ESS bulk et tail min ≥ 400, BFMI min ≥ 0,30, aucune atteinte de la profondeur d'arbre maximale,
et présence exacte des 4 × 1 000 tirages attendus.

- `leg_1986_r1/H2/krt_beta_binomial` : R-hat max=1.0110716626623513; ESS bulk min=243.339765503277; ESS tail min=378.5503792029044

## Sources reproductibles

- `outputs/priority_production_diagnostics.csv` : diagnostic détaillé par ajustement ;
- `outputs/runs/<run_id>/trace.nc` : traces postérieures complètes ;
- `outputs/runs/<run_id>/longitudinal_estimates.csv` : estimations agrégées ;
- `outputs/runs/<run_id>/commune_latent_summaries.parquet` : résumés communaux.
