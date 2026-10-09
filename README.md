# Inférence écologique longitudinale — réplication 1962–2022

Ce dépôt contient les sources versionnées de la réplication longitudinale menée sur un panel fixe de 2 000 communes françaises. La branche `main` correspond à la version portable **2.6**, gelée le 8 octobre 2026 et publiée dans Dropbox sous `Part2/00_CURRENT`.

## Version de référence

La [release GitHub v2.6](https://github.com/pierreloudelfante/longitudinal-ecological-inference/releases/tag/v2.6) fournit les deux fichiers utilisés par la livraison Dropbox :

| Fichier | Taille | SHA-256 | Contenu |
| --- | ---: | --- | --- |
| `longitudinal_2000_reproduction_complete_PORTABLE_CERTIFICATION.zip` | 31 008 043 octets | `37948ed0862d63c206481bb61aa68234717644b4512ef2629fdf5ccc9caf65fc` | Kit portable, 1 268 chemins uniques |
| `longitudinal_2000_results.zip` | 143 246 075 octets | `a5c0978e822e2276c7607764cfa74dd6ece8f135f2af1d290a8a880202cd5b79` | Archive de référence, 610 fichiers |

Le premier ZIP publié sur GitHub est identique octet par octet au paquet final de Dropbox. Le second est l'archive de résultats de référence utilisée pour la comparaison finale.

## Ce que fait le projet

La chaîne part de 31 archives brutes authentifiées par taille et SHA-256, reconstruit le panel et les matrices de modèles, puis exécute :

- 240 estimations KRT Python ;
- 240 réplications King EI sous R ;
- 292 spécifications NLS sans covariables ;
- 960 spécifications NLS avec covariables ;
- 480 densités communales.

Le pipeline comporte 17 étapes et produit huit tables principales, 580 figures, les diagnostics, le rapport et une archive recalculée de 610 fichiers.

## GitHub et Dropbox

GitHub et Dropbox ont des rôles complémentaires :

- **GitHub `main`** conserve le code, les configurations, les tests, les contrats, les manifestes et les sources documentaires ;
- **GitHub Releases** conserve les deux archives figées correspondant à la livraison ;
- **Dropbox `Part2/00_CURRENT`** reste l'espace de remise au professeur et contient aussi le miroir partiel des données brutes ;
- les 31 archives brutes ne sont pas enregistrées dans Git : `TELECHARGER_DONNEES_BRUTES.ps1` les récupère depuis les URL officielles et vérifie leur intégrité.

Le dossier `.cache/R` du kit portable n'est pas suivi fichier par fichier dans `main` : il contient un environnement R binaire Windows. Il reste inclus dans l'archive portable de la release et est décrit par `reproducibility/r-runtime-library-manifest.json`.

## Démarrage

Prérequis : Windows x86-64, Python 3.12.10, R 4.6.0, Edge ou Chrome, 16 Go de RAM, au moins 5 Gio de mémoire disponible et 50 Gio de disque libre.

Depuis une extraction neuve du ZIP portable :

```powershell
powershell -ExecutionPolicy Bypass -File .\TELECHARGER_DONNEES_BRUTES.ps1

powershell -ExecutionPolicy Bypass -File .\REPRODUIRE_TOUT.ps1 -PreflightSeulement `
  -ExigerRessourcesRecommandees -MinimumFreeDiskGB 50 -MinimumAvailableMemoryGB 5

powershell -ExecutionPolicy Bypass -File .\REPRODUIRE_TOUT.ps1 `
  -ExigerRessourcesRecommandees -MinimumFreeDiskGB 50 -MinimumAvailableMemoryGB 5
```

Le préflight doit afficher :

```text
PREFLIGHT REUSSI - AUCUNE ESTIMATION N'A ETE LANCEE
```

Lire [COMMENCER_ICI.md](COMMENCER_ICI.md) avant le rejeu complet.

## Tests et preuves

Dans une extraction du ZIP portable, la suite d'audit autonome se lance ainsi :

```powershell
python -m unittest discover -s reproducibility/tests_v2 -v
```

Les tests historiques sous `tests/` qui lisent directement des panels ou sorties déjà calculés nécessitent ces artefacts locaux ; ils ne constituent pas la suite autonome du paquet.

Les principales pièces d'audit sont :

- [provenance du paquet](PROVENANCE_SOURCE.md) ;
- [métadonnées v2.6](reproducibility/contract_v2/V26_PACKAGE_METADATA.json) ;
- [contrat des 31 sources](reproducibility/contract_v2/raw_sources_31.json) ;
- [liste des 610 résultats attendus](reproducibility/contract_v2/expected_results_610.json) ;
- [politique de certification](reproducibility/contract_v2/certification_policy_v1.json).

## Limite à conserver explicitement

`full_610_run_certified=false` : les tests, le préflight et les sondes scientifiques donnent un niveau de confiance élevé, mais la dernière correction d'infrastructure n'a pas encore été suivie d'un rejeu indépendant complet des 610 fichiers. La preuve définitive sera le JSON de certification produit à la fin d'une exécution intégrale.
