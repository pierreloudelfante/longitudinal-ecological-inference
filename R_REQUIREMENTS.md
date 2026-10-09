# Environnement R inclus

Le recalcul principal utilise **R 4.6.0** et les paquets suivants :

| Paquet | Version | Usage |
| --- | --- | --- |
| `ei` | 1.3.3 | 240 réplications King en R |
| `eiPack` | 0.2.2 | dépendance et contrôle de l'environnement King |
| `jsonlite` | 2.0.0 | lecture et écriture des manifestes |
| `digest` | 0.6.39 | empreintes SHA-256 |
| `data.table` | 1.18.4 | utilitaires des scripts R fournis |
| `MASS` | 7.3-65 | figures de densité |
| `coda` | 0.19-4.1 | diagnostics MCMC |

Une bibliothèque R Windows minimale et figée est fournie dans `.cache/R/library`, avec toutes les dépendances non intégrées à R. Le lanceur l'ajoute automatiquement à `.libPaths()` et vérifie les paquets avant tout calcul.

R lui-même n'est pas inclus : installez R 4.6.0, ou indiquez son exécutable avec `-RscriptExe`.

Les scripts expérimentaux NIMBLE/CmdStan restent présents pour l'audit du projet, mais ils ne sont pas appelés par `REPRODUIRE_TOUT.ps1` et leurs bibliothèques lourdes ne sont donc pas embarquées dans ce kit.
