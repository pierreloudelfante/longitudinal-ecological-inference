# Contrôles prédictifs postérieurs KRT — méthode V2

Ce contrôle est **additif et non destructif**. Il lit les traces et entrées
existantes, puis écrit uniquement dans `outputs/v2/ppc_krt/` et
`figures/v2/ppc_krt/`. Les dossiers de runs, tableaux et figures historiques
ne sont jamais modifiés.

## Mapping exact trace → communes

Pour chaque run KRT réussi, `code_longitudinal.ppc_v2` vérifie successivement :

1. que `manifest.json` désigne bien un modèle `krt_beta_binomial` réussi ;
2. que l'unique parquet modèle-ready listé dans `input_sha256` existe et que
   son SHA256 est inchangé ;
3. que le nombre de positions de `b_1` et `b_2` correspond au nombre de lignes
   du parquet ;
4. que l'ordre des communes est celui de `commune_latent_summaries.csv`, export
   créé directement à partir du `fit_frame` utilisé pour l'estimation ;
5. que les moyennes de `b_1` et `b_2` recalculées depuis la trace coïncident
   avec cet export ordonné ;
6. que `observed_data/votes_count` de la trace coïncide avec le premier compte
   politique `Y__...` du parquet dans cet ordre, à l'exception documentée d'un
   écart maximal d'une voix lié au passage flottant `(Y/N) × N` dans PyEI.

Si une autre vérification échoue, ou si l'écart de compte dépasse une voix,
aucun résultat PPC n'est produit. Les sorties conservent le compte source et le
compte effectivement ajusté, plus le nombre et la somme de leurs différences.

## Loi prédictive et métriques

Pour le tirage postérieur `s` et la commune `i`, la probabilité prédite de la
première catégorie politique est

```text
theta[s,i] = (N1[i] * b1[s,i] + N2[i] * b2[s,i]) / N[i]
```

avec `N[i] = N1[i] + N2[i]`. Une réplique est tirée selon
`y_rep[s,i] ~ Binomial(N[i], theta[s,i])`, conformément à la vraisemblance du
modèle PyEI `king99` utilisé par le projet.

Les métriques utilisent `observed_data/votes_count`, c'est-à-dire les comptes
réellement vus par la vraisemblance. Le compte entier du parquet est également
exporté pour rendre visibles les rares retraits d'une voix causés par la
conversion flottante des traces historiques.

Les sorties contiennent : erreur moyenne, RMSE et MAE des parts communales
prédites ; couverture communale de l'intervalle prédictif à 95 % ; intervalle
prédictif de la part agrégée, avec indicateur de couverture ; et p-value
bayésienne en queue supérieure pour une statistique de discordance de Pearson.
Cette dernière est un diagnostic de calibration, pas un test fréquentiste ni
une preuve d'identification écologique.

## Exécution

```powershell
python -m code_longitudinal.ppc_v2 --priority-all --max-draws 4000
```

`--run-id` permet de cibler un ou plusieurs runs. L'échantillonnage prédictif
est reproductible grâce à une graine dérivée de la graine globale et du
`run_id`. Lorsque plus de 4 000 tirages sont disponibles, un sous-ensemble
déterministe régulièrement espacé est utilisé et les nombres disponible/utilisé
sont enregistrés dans les métadonnées.
