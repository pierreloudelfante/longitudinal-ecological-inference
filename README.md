# Inférence écologique longitudinale en France, 1962–2022

Paquet de réplication d'une analyse d'inférence écologique menée sur un panel fixe de **2 000 communes françaises** et **26 scrutins**. Le dépôt contient le code, les paramètres, les contrats de données, les tests et la documentation nécessaires pour reconstruire les données d'analyse, réestimer les modèles et comparer les résultats recalculés à une référence figée.

> **État de validation.** La version courante a passé les contrôles d'intégrité, les tests automatisés, le contrôle préalable en environnement propre et des sondes scientifiques bornées. La campagne complète postérieure à la dernière correction d'infrastructure n'a pas encore été exécutée jusqu'aux 610 fichiers : `full_610_run_certified=false`. Cette limite est scientifique et doit rester visible.

## Repère rapide

| Élément | Valeur |
| --- | --- |
| Révision technique | `v2.6` ([métadonnées](reproducibility/contract_v2/V26_PACKAGE_METADATA.json)) |
| Unité d'analyse | Commune |
| Panel principal | 2 000 communes |
| Période | 1962–2022 |
| Scrutins | 26 |
| Sources brutes | 31 archives ZIP authentifiées |
| Chaîne complète | 17 étapes |
| Contrat de sortie | 610 fichiers |
| Système cible | Windows x86-64 |
| Python | 3.12.10 exactement |
| R | 4.6.0 exactement |

## Livrables de référence

Les deux archives figées sont distribuées dans la livraison Dropbox `Part2/00_CURRENT`. GitHub conserve le code source, les contrats et la documentation correspondant à cette livraison.

| Fichier | Taille | SHA-256 | Rôle |
| --- | ---: | --- | --- |
| `longitudinal_2000_reproduction_complete_PORTABLE_CERTIFICATION.zip` | 31 008 043 octets | `37948ed0862d63c206481bb61aa68234717644b4512ef2629fdf5ccc9caf65fc` | Kit portable, 1 268 chemins uniques |
| `longitudinal_2000_results.zip` | 143 246 075 octets | `a5c0978e822e2276c7607764cfa74dd6ece8f135f2af1d290a8a880202cd5b79` | Référence scientifique, 610 fichiers |

Le premier ZIP est le paquet portable remis au professeur. Le second est uniquement une référence de comparaison : le pipeline n'en extrait jamais des résultats pour remplacer un calcul manquant.

## Périmètre scientifique

À partir des 31 archives sources, la chaîne reconstruit le panel et les matrices de modèles, puis produit :

| Famille | Nombre attendu |
| --- | ---: |
| Estimations KRT Python | 240 |
| Réplications King EI sous R | 240 |
| NLS sans covariables | 292 |
| NLS avec covariables | 960 |
| Densités communales | 480 |
| Bases finales principales | 8 |
| Fichiers dans l'archive finale | 610 |

Les diagnostics défavorables sont conservés comme résultats scientifiques. Une exécution techniquement complète ne transforme pas un diagnostic MCMC `caveat` ou `fail` en succès.

## Organisation du dépôt

Les conventions académiques `data / code / outputs` sont respectées **logiquement**, sans déplacer les fichiers dont les chemins sont figés dans le contrat de réplication.

| Convention | Emplacement dans ce dépôt | Contenu |
| --- | --- | --- |
| Guide principal | [`COMMENCER_ICI.md`](COMMENCER_ICI.md) | Procédure complète, prérequis, suivi et reprise |
| Données brutes | [`DONNEES_BRUTES/`](DONNEES_BRUTES/) | Emplacement local des 31 ZIP ; données non suivies par Git |
| Code Python | [`code_longitudinal/`](code_longitudinal/) | Préparation, estimation, consolidation et production des sorties |
| Code R | [`r_replication/`](r_replication/) | King EI, KRT/NIMBLE, NLS et densités |
| Paramètres | [`config/`](config/) | Configurations et contrats de calcul historiques |
| Reproductibilité | [`reproducibility/`](reproducibility/) | Orchestration, manifestes, certification, environnement et tests autonomes |
| Tests | [`tests/`](tests/) | Tests scientifiques historiques et fixtures minimales |
| Provenance | [`PROVENANCE_SOURCE.md`](PROVENANCE_SOURCE.md) | Origine du code et gel du paquet |
| Sorties recalculées | `outputs/`, `deliverables/` | Créées localement et exclues de Git |
| Journaux | `JOURNAUX_REPRODUCTION/`, `.runtime/` | État, heartbeats, erreurs et reprise ; exclus de Git |

Le flux complet est :

```text
31 archives sources authentifiées
  -> harmonisation et panel fixe
  -> matrices de modèles
  -> KRT + NLS + King EI
  -> consolidations, diagnostics, figures et rapport
  -> archive recalculée de 610 fichiers
  -> certification contre la référence figée
```

L'historique Git assure le versionnement du code ; les anciennes copies ne doivent pas être dupliquées dans des dossiers `old/` ou `archive/` sur `main`. Les archives binaires figées restent séparées du dépôt source.

## Disponibilité et provenance des données

Les données brutes ne sont pas versionnées dans Git. Elles représentent **31 archives ZIP et 1 620 387 967 octets** au total. Le contrat lisible par machine précise pour chaque source son nom accepté, son URL, sa taille et son SHA-256 :

- [`reproducibility/contract_v2/raw_sources_31.json`](reproducibility/contract_v2/raw_sources_31.json) ;
- [`reproducibility/contract_v2/DONNEES_REQUISES.csv`](reproducibility/contract_v2/DONNEES_REQUISES.csv).

Le téléchargeur reprend l'acquisition en conservant toute archive déjà conforme et refuse une taille ou une empreinte différente. Le miroir Dropbox des données brutes peut être partiel ; **le manifeste de 31 sources, et non la seule présence d'un fichier, fait foi**.

Les utilisateurs restent responsables du respect des conditions d'accès et de redistribution des fournisseurs des données sources. Le dépôt GitHub ne republie pas les 1,62 Go d'archives brutes.

## Reproduction complète

Lire d'abord [`COMMENCER_ICI.md`](COMMENCER_ICI.md). Le clone de `main` n'inclut pas l'environnement R binaire `.cache/R` ; la reproduction professorale doit donc partir d'une extraction neuve du ZIP portable distribué dans Dropbox :

### 1. Acquérir et authentifier les sources

```powershell
powershell -ExecutionPolicy Bypass -File .\TELECHARGER_DONNEES_BRUTES.ps1
```

### 2. Effectuer le contrôle préalable sans estimation

Placer `longitudinal_2000_results.zip` à la racine extraite, puis exécuter :

```powershell
powershell -ExecutionPolicy Bypass -File .\REPRODUIRE_TOUT.ps1 -PreflightSeulement `
  -ExigerRessourcesRecommandees -MinimumFreeDiskGB 50 -MinimumAvailableMemoryGB 5
```

Le contrôle doit afficher :

```text
PREFLIGHT REUSSI - AUCUNE ESTIMATION N'A ETE LANCEE
```

### 3. Lancer les 17 étapes

```powershell
powershell -ExecutionPolicy Bypass -File .\REPRODUIRE_TOUT.ps1 `
  -ExigerRessourcesRecommandees -MinimumFreeDiskGB 50 -MinimumAvailableMemoryGB 5
```

Le lanceur reprend les étapes et ajustements déjà terminés. Les échecs persistants sont mémorisés ; ils ne sont ni masqués, ni remplacés par la référence, ni relancés en boucle. La procédure exacte de reprise figure dans `COMMENCER_ICI.md`.

## Environnement et ressources

- Windows x86-64 ;
- Python 3.12.10 exactement, avec `py.exe` et `pip` ;
- R 4.6.0 exactement ;
- Microsoft Edge ou Google Chrome pour le rendu PDF ;
- 16 Go de RAM, avec au moins 5 Gio disponibles au lancement ;
- au moins 50 Gio de disque libre ;
- accès à PyPI lors du premier lancement si l'environnement Python local n'existe pas encore.

Le verrou Python faisant foi est [`reproducibility/requirements-python312.lock.txt`](reproducibility/requirements-python312.lock.txt). Les deux fichiers `requirements-*.txt` historiques placés à la racine ne servent pas à installer cette réplication. L'environnement R binaire du kit portable est décrit par [`reproducibility/r-runtime-library-manifest.json`](reproducibility/r-runtime-library-manifest.json).

Les modèles MCMC constituent l'essentiel du temps de calcul. La durée dépend du processeur et de la mémoire ; le guide opératoire documente les limites par estimation et le suivi par heartbeat. Comme dans les réplications académiques à calcul intensif, le préflight valide l'environnement mais ne prédit pas une durée identique sur toutes les machines.

## Sorties et correspondance avec la référence

La commande complète crée, sans modifier l'archive de référence :

```text
deliverables/longitudinal_2000_results_recalcules.zip
deliverables/longitudinal_2000_results_recalcules.certification.json
```

Le ZIP recalculé doit contenir les 610 chemins définis dans [`expected_results_610.json`](reproducibility/contract_v2/expected_results_610.json), répartis ainsi :

```text
00_README_PROFESSEUR.md
01_RAPPORT/
02_TABLES_PRINCIPALES/
03_FIGURES/
04_PANEL_ET_HARMONISATION/
05_DIAGNOSTICS/
06_DOCUMENTATION/
```

Les huit tables principales, leurs schémas, leurs clés et leurs nombres de lignes sont contrôlés automatiquement. Le guide [`COMMENCER_ICI.md`](COMMENCER_ICI.md) donne leur liste complète et explique où suivre les 17 étapes.

## Aléatoire contrôlé et certification

La construction du panel et les NLS sont déterministes. Les modèles KRT et King EI utilisent des graines historiques enregistrées. Les versions, paramètres, graines et règles de comparaison sont figés dans :

- [`krt_replay_240.json`](reproducibility/contract_v2/krt_replay_240.json) ;
- [`r_replay_240.json`](reproducibility/contract_v2/r_replay_240.json) ;
- [`certification_policy_v1.json`](reproducibility/contract_v2/certification_policy_v1.json).

La certification distingue :

- `rejeu_binaire_exact` : identité SHA-256 des 610 fichiers ;
- `equivalence_scientifique_numerique` : structure, identifiants, diagnostics et résultats numériques conformes aux tolérances préenregistrées.

Des écarts numériques minimes entre processeurs ou bibliothèques mathématiques restent possibles malgré des graines identiques. Ils ne sont acceptés que par les règles explicites de certification ; les seuils ne sont pas ajustés à partir du résultat candidat.

## Tests et pièces d'audit

La suite autonome du paquet se lance depuis une extraction portable :

```powershell
python -m unittest discover -s reproducibility/tests_v2 -v
```

Les principales pièces d'audit sont :

- [métadonnées du paquet](reproducibility/contract_v2/V26_PACKAGE_METADATA.json) ;
- [reçu des fichiers](reproducibility/contract_v2/CHANGEMENTS_FICHIERS.csv) ;
- [contrat des 31 sources](reproducibility/contract_v2/raw_sources_31.json) ;
- [contrat des 610 sorties](reproducibility/contract_v2/expected_results_610.json) ;
- [politique de certification](reproducibility/contract_v2/certification_policy_v1.json) ;
- [documentation technique de la réplication](reproducibility/README.md).

Les tests remplacent les moteurs coûteux par des substituts lorsqu'ils contrôlent l'orchestration. Ils démontrent le comportement du code, pas une nouvelle estimation complète. Seul le JSON produit à la fin d'une campagne intégrale peut faire passer `full_610_run_certified` à `true`.

## Citation

Les métadonnées de citation sont fournies dans [`CITATION.cff`](CITATION.cff). Tant qu'un DOI ou un article associé n'est pas renseigné, citer le dépôt GitHub, la révision technique utilisée et, si possible, le commit exact.

## Droits et licence

Les données brutes conservent les conditions d'accès et de redistribution de leurs fournisseurs respectifs et ne sont pas publiées dans Git. Aucune licence logicielle ouverte n'est actuellement attachée à ce dépôt ; en son absence, les droits d'auteur par défaut s'appliquent au code. Contacter l'auteur avant toute réutilisation allant au-delà de la consultation ou de la vérification scientifique.

## Auteur et contact

Pierre-Lou Delfante — les questions de réplication peuvent être déposées dans les [issues GitHub](https://github.com/pierreloudelfante/longitudinal-ecological-inference/issues).
