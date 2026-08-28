# Dépendances R de réplication et de miroir

Les scripts R du projet couvrent trois usages distincts : réplication NLS, robustesse King classique et miroir exact du modèle KRT Python. Les versions ci-dessous sont celles observées dans la bibliothèque locale du projet le 25 août 2026.

| Paquet | Version | Usage |
| --- | --- | --- |
| `ei` | 1.3.3 | réplication du modèle de King |
| `eiPack` | 0.2.2 | modèles écologiques alternatifs, notamment RxC avec `ei.MD.bayes` |
| `jsonlite` | 2.0.0 | lecture et écriture des manifestes |
| `digest` | 0.6.39 | SHA-256 des entrées |
| `data.table` | 1.18.4 | réplication NLS |
| `cmdstanr` | 0.9.0 | miroir exact KRT à partir du programme Stan |
| `posterior` | 1.7.1 | diagnostics et résumés des chaînes Stan |
| `nimble` | 1.4.2 | moteur R alternatif pour le miroir exact KRT |
| `coda` | 0.19-4.1 | diagnostics MCMC pour NIMBLE |

Version de R utilisée : `4.6.0`.

Installation indicative :

```r
install.packages(c(
  "ei", "eiPack", "jsonlite", "digest", "data.table",
  "posterior", "nimble", "coda"
))
# cmdstanr suit sa procédure d'installation officielle et nécessite CmdStan.
```

Le script Python recherche `Rscript` dans `LONGITUDINAL_RSCRIPT`, puis dans le `PATH`, puis dans les emplacements historiques documentés. Les paquets peuvent être installés dans la bibliothèque du projet `.cache/R/library` ou dans une bibliothèque R accessible.

## État de compatibilité observé

- `eiPack`, `cmdstanr`, `posterior`, `nimble`, `coda`, `jsonlite`, `digest` et `data.table` se chargent dans l'environnement local.
- `ei` est installé mais son chargement est actuellement bloqué par la stratégie Windows Application Control sur `gmm.dll`. La voie de robustesse King classique ne doit pas être relancée tant que ce blocage n'est pas levé ou contourné sur une machine autorisée.
- Plusieurs paquets ont été construits sous R 4.6.1 alors que le binaire local est R 4.6.0. Le plan miroir impose donc de figer et d'enregistrer la version complète de R, de CmdStan et des paquets avant production.
- `eiPack::ei.MD.bayes` est un modèle RxC de Rosen et al. (2001). Il ne constitue pas une réplication mathématiquement identique du `TwoByTwoEI("king99")` de Python. La parité exacte reste assurée par le même programme Stan ou son équivalent NIMBLE.
