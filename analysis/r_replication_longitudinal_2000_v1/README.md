# Réplication R — `longitudinal_2000_v1`

Ce module est isolé du pipeline Python. Il lit directement les CSV `model-ready` produits pour le panel canonique et refuse toute estimation si les 2 000 `unit_id`, leur ordre, les codes de panel ou les fermetures de comptes ne correspondent pas exactement.

## Contrat vérifié

- panel : `longitudinal_2000_v1__strict_nested_3000__seed_20260803` ;
- échantillon : les 2 000 premières communes du tirage maître, dans le même ordre à chaque scrutin ;
- registre : 26 élections, 292 couples classés, 270 admissibles et 22 explicitement exclus ;
- marges : `sum(N__*) == N_g`, `sum(Y__*) == N_g` et `X__* == N__*/N_g` ;
- NLS : même paramétrisation softmax à catégorie de référence, même SSE non pondérée, 20 départs, tolérance `1e-9`, plafond de 5 000 évaluations et graine `20260802` ;
- KRT : modèle PyEI `king99` reproduit dans `krt_king99.stan`, avec quatre hyperparamètres exponentiels de taux `king_lambda=0.5`, effets communaux bêta et vraisemblance binomiale sur les mêmes comptes.

Le solveur NLS R est `stats::optim(BFGS)`, indépendant du solveur TRF de SciPy. Les objectifs et estimands sont identiques, mais les départs aléatoires utilisent le RNG R (les départs déterministes poolé et nul sont identiques). La comparaison mesure donc aussi la robustesse au solveur.

## Commandes

R n’est pas dans le `PATH` sur cette machine. Utiliser son chemin absolu depuis la racine du projet :

```powershell
& 'C:\Program Files\R\R-4.6.0\bin\Rscript.exe' analysis\r_replication_longitudinal_2000_v1\audit_inputs.R
& 'C:\Program Files\R\R-4.6.0\bin\Rscript.exe' analysis\r_replication_longitudinal_2000_v1\run_nls.R --election=leg_1962_r1 --scenario=H0A
& 'C:\Program Files\R\R-4.6.0\bin\Rscript.exe' analysis\r_replication_longitudinal_2000_v1\compare_nls_python.R --election=leg_1962_r1 --scenario=H0A
```

Pour lancer les 270 NLS admissibles :

```powershell
& 'C:\Program Files\R\R-4.6.0\bin\Rscript.exe' analysis\r_replication_longitudinal_2000_v1\run_nls.R --all
```

Le KRT R est préparé avec le contrat de production exact : 4 chaînes, 1 000 warmup, 1 000 draws, `target_accept=0.99`, `max_treedepth=14`, graine `20260802` et `king_lambda=0.5`.

```powershell
& 'C:\Program Files\R\R-4.6.0\bin\Rscript.exe' analysis\r_replication_longitudinal_2000_v1\run_krt.R --election=leg_1962_r1 --scenario=H0A --cores=4
```

À la création du module, aucun moteur Stan/JAGS ni compilateur Rtools n’est installé. Le lanceur écrit `results/krt_preflight.json` et s’arrête explicitement, sans substituer le paquet `ei`, car `ei` n’implémente pas le même KRT bêta-binomial. Aucun package n’est installé automatiquement.

## Sorties

- `results/input_contract.csv` : audit exact des 270 fichiers `model-ready` ;
- `results/nls/<élection>__<scénario>/` : estimations, coefficients, départs et diagnostics R ;
- `results/comparison/` : écarts R/Python par estimand et comparaison des SSE ;
- `results/krt/` : sorties communales et agrégées quand un moteur Stan compatible est disponible.
