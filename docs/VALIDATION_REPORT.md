# Rapport de validation longitudinale

Validation générée le `2026-08-04T02:04:30.749154+00:00`.

**Verdict : pass_with_warnings** — 57 contrôles réussis, 3 avertissement(s), 0 échec(s).

Les avertissements MCMC des calibrations 20/20/1 sont attendus, y compris lorsque le palier demandé atteint 3 000 : ils qualifient le pipeline et le coût du calcul, pas des résultats substantiels. Le NLS 2022 à 3 000 communes est validé séparément.

## Contrôles non réussis

- `warning` — **mcmc::substantive_diagnostics** : observé `375` ; attendu : no diagnostic failure for substantive interpretation. Expected for calibration smoke tests (20 draws, one chain); these runs remain explicitly non-substantive.
- `warning` — **snapshot_2022::pyei_production_coverage** : observé `0/20 scenario-model pairs` ; attendu : King and KRT production n=3000 pass for all ten 2x2 scenarios. The resource ladder and the 12-hour/80%-memory guards remain binding; missing pairs are not silently replaced by smoke tests.
- `warning` — **partitions_1962_2022::full_rxc_source_coverage** : observé `22 RXC partitions rejected` ; attendu : all five-block source margins satisfy the absolute 0.01-vote tolerance. No closure was forced for the rejected sources; see all_elections_partition_integrity.csv.

## Portée

Le contrôle couvre les tailles et l'emboîtement des panels, la balance, le registre de présence des 26 scrutins, la fermeture exacte des partitions préparées, les schémas consolidés, les clés uniques, les bornes et quantiles latents, les intersections King/KRT, les 20 départs NLS et la traçabilité des runs.

Le détail machine-lisible se trouve dans `outputs/validation_checks.csv` et `outputs/validation_summary.json`.
