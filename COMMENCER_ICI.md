# Réplication du projet longitudinal 1962–2022 — version finale portable

## Objet de ce paquet

Cette procédure utilise les archives brutes socio-économiques et électorales de Cagé–Piketty pour reconstruire le panel longitudinal et les matrices des modèles, exécuter les estimations et produire les tableaux, figures et rapports.

Le contrat de sortie correspond à `longitudinal_2000_results.zip` de référence (610 fichiers, SHA-256 `a5c0978e822e2276c7607764cfa74dd6ece8f135f2af1d290a8a880202cd5b79`).

**Avant toute commande scientifique, trois éléments distincts sont obligatoires :**

1. le présent ZIP de réplication, extrait dans un dossier local neuf ;
2. les 31 ZIP de données brutes authentifiés (1 620 387 967 octets au total), obtenus par le script de la section 1 ou fournis séparément ;
3. `longitudinal_2000_results.zip` (143 246 075 octets, SHA-256 ci-dessus), téléchargé séparément depuis `00_CURRENT` et placé à la racine extraite.

Le ZIP de réplication ne contient volontairement ni les 1,62 Go de sources ni l'archive de résultats de référence. Leur absence est donc un prérequis manquant, pas une étape que le lanceur peut reconstruire ou contourner. Le preflight s'arrête avant toute estimation si l'un de ces trois éléments ou l'un des logiciels de la section 2 manque.

La révision technique finale conserve exactement le périmètre scientifique, les estimateurs, les graines, les paramètres et les tolérances de la révision précédente. Elle remplace seulement le paquet d'infrastructure `cli 3.6.6` par son binaire Windows officiel CRAN, vérifie les 22 paquets R natifs dès le contrôle préalable et répare automatiquement un environnement Python local dont la création aurait été interrompue. La reconstruction complète n'est déclarée terminée que si les tables scientifiques satisfont le contrat de certification décrit ci-dessous.

| Périmètre | Attendu |
|---|---:|
| Scrutins | 26 |
| Communes du panel principal | 2 000 |
| KRT Python, avec réglages individuels de référence | 240 |
| King EI R, même ensemble de couples | 240 |
| NLS de base admissibles dans l'audit national | 270 |
| NLS RxC complémentaires, admissibles sur le panel fixé | 22 |
| Total NLS non covariés livré | 292 |
| NLS avec covariables : quatre spécifications × 240 couples | 960 |
| Densités communales individuelles : deux méthodes × 240 couples | 480 |
| Fichiers attendus dans l'archive de résultats | 610 |

Les 292 NLS ne sont pas tous déclarés scientifiquement validés. Le programme conserve les diagnostics calculés, y compris les échecs numériques. Une couverture informatique complète n'est pas un diagnostic MCMC favorable.

## 1. Préparer les données sources

La méthode complète et vérifiée consiste à télécharger les 31 archives depuis leurs URL sources consignées dans le manifeste. Depuis la racine extraite, exécuter :

```powershell
powershell -ExecutionPolicy Bypass -File .\TELECHARGER_DONNEES_BRUTES.ps1
```

Ce script d'acquisition est distinct du lanceur scientifique : il ne prépare aucune base et ne lance aucune estimation. Il télécharge dans `DONNEES_BRUTES/`, reprend en conservant toute archive déjà conforme, et refuse chaque fichier dont la taille ou le SHA-256 diffère du manifeste. Il peut aussi contrôler un dossier déjà fourni sans accès réseau :

```powershell
powershell -ExecutionPolicy Bypass -File .\TELECHARGER_DONNEES_BRUTES.ps1 `
  -DossierDestination "D:\Donnees\Cage_Piketty" -VerifierSeulement
```

Au 8 octobre 2026, les 31 URL répondaient en HTTP 200 avec exactement les 31 tailles attendues. Le miroir `00_CURRENT/DONNEES_BRUTES/` de Dropbox ne contient que 27/31 ZIP à cause du quota Dropbox ; il ne constitue donc pas à lui seul le jeu complet et ne doit pas être présenté comme tel. Une acquisition manuelle reste possible en utilisant les colonnes `source_url` et `download_name` de `reproducibility/contract_v2/DONNEES_REQUISES.csv`, puis en conservant **les ZIP compressés** dans `DONNEES_BRUTES/`.

La liste complète est `reproducibility/contract_v2/DONNEES_REQUISES.csv` : **31 archives, environ 1,62 Go**. Elles comprennent les 26 archives électorales et cinq archives socio-économiques : CSP, taille des agglomérations/communes, revenus, capital immobilier et nationalités. Les cinq archives socio-économiques sont nécessaires à la préparation des données et aux spécifications avec covariables.

Le CSV précise le nom interne, le nom d'origine du téléchargement, l'URL enregistrée dans le journal de téléchargement du projet, la taille et le SHA-256 attendu. Le lanceur scientifique ne télécharge jamais les sources : l'acquisition explicite ci-dessus précède le contrôle préalable. Une réponse HTTP ou un nom correct ne suffit pas ; seuls la taille et le SHA-256 contractuels rendent une archive recevable. Ne pas remplacer silencieusement une version dont l'empreinte diffère.

Les noms d'origine (`CSP_csv.zip`, `leg1962_csv.zip`, etc.) sont acceptés. Pour une même source logique, au moins l'un des deux noms (`name` canonique ou `download_name` d'origine) doit porter exactement la taille et le SHA-256 contractuels. Si les deux noms sont présents et qu'une seule copie est authentique, le vérificateur utilise exclusivement la copie authentique et affiche un avertissement nommant l'autre ; celle-ci n'entre jamais dans le calcul. Si aucune copie n'est authentique, il s'arrête avant tout calcul et avant tout téléchargement. Si nécessaire, le lanceur crée une vue normalisée par liens physiques ; si le système de fichiers ne permet pas ces liens, il copie les fichiers. Il ne modifie pas les archives sources.

## 2. Installer les logiciels requis

Le parcours figé vise **Windows x86_64**, **Python 3.12.10 exactement** et **R 4.6.0 exactement**. Installer Python avec le lanceur Windows `py.exe`. Le script vérifie la version, l'architecture, `pip` et la nature virtuelle de l'environnement avant de créer, si nécessaire, son environnement local `.venv-reproduction/`. Les dépendances opératoires sont définies dans `reproducibility/requirements-python312.lock.txt`, complété explicitement par `mistune==3.3.4` pour la génération du rapport ; les deux fichiers `requirements-*.txt` placés à la racine sont des reçus historiques et ne doivent pas être utilisés pour installer la réplication. Sur un poste neuf, le premier lancement **requiert un accès à PyPI** tant que cet environnement exact n'existe pas encore. Les paquets R sont déjà fournis et ne sont pas téléchargés.

Liens officiels pour préparer une machine neuve :

- Python 3.12.10, **Windows installer (64-bit)**, en conservant `pip` et le lanceur `py.exe` : <https://www.python.org/downloads/release/python-31210/> ;
- R 4.6.0 pour Windows (archive officielle CRAN, fichier `R-4.6.0-win.exe`) : <https://cran.r-project.org/bin/windows/base/old/4.6.0/> ;
- Microsoft Edge pour Windows si Edge n'est pas déjà installé : <https://www.microsoft.com/edge/download>.

Redémarrer PowerShell après une installation afin que les nouveaux exécutables soient visibles. Le contrôle préalable refuse toute autre version de Python ou de R : il ne modifie pas ces logiciels système.

Télécharger aussi `longitudinal_2000_results.zip` depuis le même dossier Dropbox `00_CURRENT` et le placer **sans le renommer** à côté de `REPRODUIRE_TOUT.ps1`. Avant toute estimation, le lanceur vérifie son SHA-256, son intégrité ZIP et ses 610 chemins ; il enregistre également sa taille dans le reçu. Cette archive sert uniquement de référence de comparaison ; elle n'est jamais copiée à la place des sorties recalculées.

La bibliothèque R binaire fournie dans `.cache/R/library` contient les 33 paquets nécessaires à l'exécution ; elle évite toute installation R cachée ou dépendante de versions CRAN futures. Ses 989 fichiers sont couverts par les empreintes arborescentes, comptes et tailles des 33 paquets dans `reproducibility/r-runtime-library-manifest.json` ; leurs empreintes individuelles figurent aussi dans le reçu de changement du paquet. Le contrôle authentifie l'intégralité de ces fichiers, compare les versions critiques au verrou R, puis charge les 22 paquets contenant du code natif. Le reçu `reproducibility/contract_v2/R_CLI_3_6_6_CRAN_RECEIPT.json` identifie le binaire officiel `cli 3.6.6` et son SHA-256. Le navigateur **Edge ou Chrome** sert à générer le PDF depuis le HTML nouvellement produit. Il n'est pas utilisé pour obtenir les données. Le contrôle préalable teste la génération PDF avant le lancement des estimations.

Le dossier caché `.cache/R/library` fait partie du paquet et ne doit pas être omis lors d'une copie manuelle. Sur un poste où Smart App Control ou WDAC est appliqué, Windows doit autoriser les DLL natifs fournis. Le SHA-256 établit l'intégrité, mais n'est pas une signature de code. `-ExecutionPolicy Bypass` autorise uniquement le script PowerShell : cette option ne désactive ni Smart App Control ni WDAC. Le contrôle préalable s'arrête avant toute estimation si Windows refuse un DLL.

Les scripts R utilisent uniquement la bibliothèque fournie et les paquets standards/recommandés de l'installation R 4.6.0 (notamment `MASS` et `lattice`). Les bibliothèques personnelles, les bibliothèques de site et les profils de démarrage R sont exclus ; aucune ancienne installation de paquets du compte utilisateur n'est nécessaire.

À chaque lancement, le script vérifie les versions de tous ces paquets puis leur cohérence avec `pip check`. Si l'environnement est déjà conforme, il le réutilise automatiquement : **aucune réinstallation ni aucun téléchargement**. Sinon, il installe uniquement les paquets absents ou de version différente dans `.venv-reproduction/`. Cette installation nécessite un accès au dépôt de paquets et ne crée pas de cache partagé sur l'ordinateur. Les logiciels Python, R et le navigateur doivent déjà être installés ; le lanceur ne les réinstalle pas.

`-SansInstallation` interdit toute installation et signale précisément les paquets manquants ou différents. Avec `-PythonExe`, un environnement externe est vérifié et réutilisé s'il est conforme ; il reste intact s'il ne l'est pas. Pour autoriser explicitement la mise à niveau d'un **environnement virtuel externe**, ajouter `-AutoriserInstallationExterne`. L'installation dans un Python global est toujours refusée. Ces options ne contournent aucun contrôle scientifique ou de version.

## 3. Lancer la reconstruction

Extraire le ZIP dans **un nouveau dossier local inscriptible**, idéalement avec un chemin assez court et hors d'un dossier synchronisé pendant les calculs, puis ouvrir PowerShell dans ce dossier. Ne pas utiliser un répertoire contenant déjà les sorties d'un autre projet.

Exemple d'extraction avec PowerShell (le dossier cible ne doit pas déjà exister) :

```powershell
Expand-Archive -LiteralPath .\longitudinal_2000_reproduction_complete_PORTABLE_CERTIFICATION.zip -DestinationPath '.\Reproduction longitudinale'
Set-Location -LiteralPath '.\Reproduction longitudinale'
```

Placer ensuite les 31 ZIP dans `DONNEES_BRUTES/` et le ZIP de référence à cette racine. Le contrôle préalable suivant est **obligatoire avant le premier rejeu** et ne lance aucune estimation :

```powershell
powershell -ExecutionPolicy Bypass -File .\REPRODUIRE_TOUT.ps1 -PreflightSeulement `
  -ExigerRessourcesRecommandees -MinimumFreeDiskGB 50 -MinimumAvailableMemoryGB 5
```

Ne lancer la commande complète qu'après avoir vu `PREFLIGHT REUSSI - AUCUNE ESTIMATION N'A ETE LANCEE` et un reçu `JOURNAUX_REPRODUCTION/PREFLIGHT_DERNIER.txt` sans échec. Avec les chemins par défaut :

```powershell
powershell -ExecutionPolicy Bypass -File .\REPRODUIRE_TOUT.ps1 `
  -ExigerRessourcesRecommandees -MinimumFreeDiskGB 50 -MinimumAvailableMemoryGB 5
```

Si les données sont ailleurs, conserver exactement ce chemin dans le preflight puis dans le rejeu :

```powershell
powershell -ExecutionPolicy Bypass -File .\REPRODUIRE_TOUT.ps1 `
  -DossierDonneesBrutes "D:\Donnees\Cage_Piketty" -PreflightSeulement `
  -ExigerRessourcesRecommandees -MinimumFreeDiskGB 50 -MinimumAvailableMemoryGB 5
powershell -ExecutionPolicy Bypass -File .\REPRODUIRE_TOUT.ps1 `
  -DossierDonneesBrutes "D:\Donnees\Cage_Piketty" `
  -ExigerRessourcesRecommandees -MinimumFreeDiskGB 50 -MinimumAvailableMemoryGB 5
```

Ce contrôle relit entièrement les 31 ZIP (nom, taille, SHA-256, chemins internes dupliqués, décompression et CRC), authentifie les fichiers livrés recensés par le reçu de changement (sauf ce reçu lui-même, dont l'auto-empreinte est impossible) et l'archive de référence, teste les versions/imports Python et R, les 22 paquets R natifs, les permissions d'écriture et le navigateur. Il affiche aussi les ressources observées. La procédure stricte ci-dessus exige un ordinateur de 16 Go (au moins 15 GiB vus par Windows), au moins 5 GiB de mémoire vive disponibles au lancement et 50 GiB d'espace disque libres. La recommandation calculée pour le disque est 5 GiB fixes plus 160 MiB par KRT, soit environ 42,5 GiB pour les 240 KRT ; le seuil de 50 GiB conserve une marge prudente car la taille des traces varie.

Lors d'une reconstruction, la préparation est suivie d'une seconde barrière automatique **avant le premier estimateur** : les 292 Parquet, leurs miroirs CSV et leurs manifestes sont tous rouverts ; les identifiants, l'ordre des 2 000 communes, les marges, les SHA-256 et l'égalité numérique CSV/Parquet sont contrôlés. Un seul échec empêche le démarrage des estimations.

Chaque ajustement des cinq familles d'estimateurs (KRT, NLS de base, NLS RxC, sensibilités covariées et King EI R) est ensuite isolé dans son propre Job Object Windows, avec un journal et un heartbeat. Le worker de chaque étape est lui-même rattaché à un Job Object exclusif de l'extraction : si le lanceur ou l'orchestrateur est interrompu brutalement, Windows arrête automatiquement l'arbre Python/R/JAX correspondant avant qu'une reprise puisse être acceptée. Un processus est créé suspendu, rattaché au Job Object, puis seulement autorisé à démarrer ; aucun descendant ne peut donc s'échapper dans l'intervalle.

Les limites murales par défaut sont volontairement conservatrices : KRT 24 heures par couple, NLS de base 120 minutes, NLS RxC 120 minutes, sensibilité covariée 60 minutes et King EI R 12 heures. L'attente d'une mémoire suffisante avant King R est bornée à 240 minutes ; le heartbeat est actualisé toutes les 30 secondes. Ces limites sont des protections contre un blocage silencieux, pas des critères statistiques. Les étapes non estimatives restent interruptibles et reprenables par étape ; le navigateur dispose d'une borne de 15 minutes pour produire le PDF, tandis que les autres opérations d'assemblage, de densités et d'empaquetage n'ont pas de limite murale globale.

Elles peuvent être augmentées avant le lancement si la machine est objectivement plus lente :

```powershell
powershell -ExecutionPolicy Bypass -File .\REPRODUIRE_TOUT.ps1 `
  -LimiteKRTHeures 36 -LimiteNLSMinutes 180 -LimiteNLSRxCMinutes 180 `
  -LimiteCovariablesMinutes 90 -LimiteKingRHeures 18 `
  -LimiteAttenteMemoireRMinutes 360 -IntervalleHeartbeatSecondes 30 `
  -ExigerRessourcesRecommandees -MinimumFreeDiskGB 50 -MinimumAvailableMemoryGB 5
```

Toutes ces valeurs doivent être strictement positives. Une limite atteinte arrête l'arbre de processus de cette estimation et enregistre un échec durable ; elle n'autorise jamais l'emploi de la sortie de référence à la place du calcul manquant.

Le même lanceur accepte `-PythonExe`, `-RscriptExe`, `-NavigateurExe` et `-ArchiveResultatsReference` avec leurs chemins complets si les emplacements par défaut ne conviennent pas.

Le plan de calcul peut être inspecté sans les données ni les bibliothèques scientifiques, avec Python installé :

```powershell
py -3.12 -m reproducibility.replication_complete plan
```

## 4. Ce que fait la commande

Elle valide les 31 sources, reconstruit le panel depuis les données, compare toutes ses lignes et colonnes à la référence, vérifie les identifiants et leur ordre, prépare explicitement les 292 matrices sur le bon panel, estime les 270 NLS de base puis les 240 KRT. Les six calculs H0A/H1 historiquement renforcés conservent leurs réglages propres. Aucun nouveau réajustement guidé par les diagnostics n'est ajouté.

Elle construit les agrégats H0A/H1 nécessaires aux consolidations originales, consolide les 240 KRT, estime et consolide les 240 King EI R, puis calcule les 22 RxC complémentaires et les 960 sensibilités covariées. Elle reconstruit ensuite les bases finales, les figures, les 480 densités et le rapport HTML/PDF. Le PDF de sortie est généré à partir du HTML de cette nouvelle exécution.

Le panel historique a été écrit avec Arrow 25.0.0, tandis que le verrou Python livré utilise Arrow 24.0.0. Deux fichiers Parquet contenant les mêmes données peuvent donc avoir des empreintes binaires différentes. La comparaison porte sur les 3 000 lignes du panel maître, ses 21 colonnes et les 2 000 communes principales, sans substituer le panel de référence au panel reconstruit. Les nombres flottants sont comparés avec une tolérance de `10⁻¹²`, les identifiants et leur ordre à l'identique. Le nouveau SHA-256 est ensuite enregistré et utilisé pour vérifier les dépendances de cette exécution. Le SHA historique reste conservé comme provenance.

Les 610 chemins de résultats attendus, les huit schémas de tables principales, leurs dimensions et leurs clés sont contrôlés avant la fabrication de l'archive. Une sortie manquante fait échouer le parcours. Après fabrication, le même lanceur compare l'archive recalculée à l'archive de référence. Un code d'échec est transmis au lanceur lorsqu'une étape ou la certification ne se termine pas correctement.

## 5. Pourquoi les résultats aléatoires peuvent différer légèrement

Les NLS et la construction du panel sont déterministes. Les modèles KRT Python et King EI R utilisent des tirages pseudo-aléatoires avec les graines historiques enregistrées. Les réglages KRT figurent dans `reproducibility/contract_v2/krt_replay_240.json` et les graines R de chaque couple dans `reproducibility/contract_v2/r_replay_240.json`. Les graines, versions et paramètres sont figés ; les bibliothèques numériques sont limitées à un fil (`OMP`, `MKL`, `OpenBLAS`, `NumExpr`) et JAX utilise les nombres 64 bits. Ces précautions réduisent les différences, sans garantir l'identité bit à bit entre processeurs ou bibliothèques mathématiques.

La certification distingue donc deux résultats :

- `rejeu_binaire_exact` : les 610 fichiers ont exactement les mêmes SHA-256 que la référence ;
- `equivalence_scientifique_numerique` : les chemins, lignes, colonnes, clés, identifiants, comptes, statuts et diagnostics sont identiques, les tables déterministes respectent des tolérances de `10⁻¹²` à `10⁻⁸`, et les résumés MCMC restent dans les tolérances préenregistrées sans changer le signe d'un effet établi ni la classification d'un intervalle agrégé par rapport à zéro.

Pour les centres des distributions MCMC, la tolérance est le maximum entre 0,25 à 0,5 point de pourcentage et 10 % de la largeur de l'intervalle de référence. Pour les bornes, elle est le maximum entre 0,5 à 1 point et 15 % de cette largeur. Les règles exactes, lisibles par la machine, sont dans `reproducibility/contract_v2/certification_policy_v1.json`. Elles sont évaluées par `reproducibility/certify_reproduction.py` ; elles ne sont pas recalculées à partir du résultat candidat.

Les identifiants scientifiques (commune, élection, hypothèse, échantillon) doivent rester identiques. Les identifiants techniques d'exécution (`run_id`, et les clés associées) sont régénérés : leur cohérence est contrôlée, mais leur date n'est pas un résultat scientifique. Deux valeurs manquantes aux mêmes emplacements restent manquantes ; aucune imputation ni suppression n'est autorisée pour obtenir une correspondance.

## 6. Où se trouvent les bases finales, les résultats et les journaux ?

La réplication complète crée deux livrables nouveaux, sans modifier l'archive de référence :

```text
deliverables/longitudinal_2000_results_recalcules.zip
deliverables/longitudinal_2000_results_recalcules.certification.json
```

Le ZIP final contient exactement les 610 chemins définis dans `reproducibility/contract_v2/expected_results_610.json` :

```text
00_README_PROFESSEUR.md
01_RAPPORT/                         # rapport longitudinal HTML et PDF
02_TABLES_PRINCIPALES/              # bases finales décrites ci-dessous
03_FIGURES/                         # trajectoires, sensibilités et 480 densités
04_PANEL_ET_HARMONISATION/          # panel final et contrôles d'harmonisation
05_DIAGNOSTICS/                     # diagnostics scientifiques finaux
06_DOCUMENTATION/                   # dictionnaire, catalogue et manifeste SHA-256
```

Les notices internes de cette archive de résultats conservent la documentation historique du livrable. Pour exécuter la réplication portable actuelle, suivre les commandes du présent guide et `REPRODUIRE_TOUT.ps1`, plutôt que les anciennes commandes de publication citées dans ces notices. Aucune présentation PowerPoint ne fait partie du contrat des 610 fichiers.

Les huit bases finales principales, leurs noms et leurs dimensions obligatoires sont :

| Fichier sous `02_TABLES_PRINCIPALES/` | Lignes attendues |
| --- | ---: |
| `02_TABLES_PRINCIPALES/longitudinal_contrasts_krt_r_nls.parquet` | 720 |
| `02_TABLES_PRINCIPALES/longitudinal_krt_aggregate.parquet` | 720 |
| `02_TABLES_PRINCIPALES/longitudinal_krt_commune.parquet` | 480 000 |
| `02_TABLES_PRINCIPALES/longitudinal_nls.parquet` | 2 370 |
| `02_TABLES_PRINCIPALES/longitudinal_nls_covariate_coefficients.parquet` | 6 720 |
| `02_TABLES_PRINCIPALES/longitudinal_nls_covariates.parquet` | 2 880 |
| `02_TABLES_PRINCIPALES/longitudinal_r_ei_aggregate.parquet` | 720 |
| `02_TABLES_PRINCIPALES/longitudinal_r_ei_commune.parquet` | 480 000 |

Le lanceur contrôle leurs schémas, clés, identifiants, nombres de lignes et valeurs numériques par rapport à `longitudinal_2000_results.zip`. Il contrôle aussi les 602 autres fichiers finaux. Un chemin ou une dimension manquante fait échouer la fabrication et la certification. `06_DOCUMENTATION/DELIVERY_MANIFEST.json` enregistre la taille et le SHA-256 des 609 autres fichiers de l'archive ; il ne peut pas contenir sa propre empreinte. Le contenu des archives de résultats et technique fournies séparément n'est jamais écrasé.

Le journal général PowerShell est dans `JOURNAUX_REPRODUCTION/`. Les fichiers d'état à consulter sont :

| Information | Fichier faisant foi |
| --- | --- |
| Contrôle préalable | `JOURNAUX_REPRODUCTION/PREFLIGHT_DERNIER.txt` et `.json` |
| Étape globale | `.runtime/replication_v2/state.json` |
| Calcul natif courant | heartbeat le plus récent sous `.runtime/replication_v2/estimation_processes/` |
| Attente mémoire King R | `outputs/longitudinal_2000_v1/r_replication/king_ei_all_2x2_status.json` |
| Échec et commande exacte de reprise | `JOURNAUX_REPRODUCTION/DERNIER_ECHEC.txt` et `.json` |

La barrière des matrices est enregistrée dans `.runtime/replication_v2/prepared_inputs_pre_estimation_gate.json`. La console indique `ETAPE n/17`, le nom de l'étape et son journal ; ce numéro est un ordre d'étapes, pas un pourcentage ni une estimation de durée. Chaque étape a un journal `.runtime/replication_v2/NN_nom.log`. Pour chaque KRT, NLS et sensibilité, le journal et le heartbeat sont sous `estimation_processes/<famille>/`; pour King R, ils sont dans le dossier du couple sous `outputs/longitudinal_2000_v1/r_replication/king_ei_runs/`. Le heartbeat JSON indique le couple, le PID, le début, le temps écoulé, la limite et le statut final (`success`, `failed`, `timeout` ou `orphan_risk`). `orphan_risk` signifie que Windows n'a pas pu confirmer l'arrêt de tout l'arbre de processus : ne pas relancer avant d'avoir vérifié et arrêté les anciens processus Python/R concernés. Une seconde campagne d'estimation simultanée dans le même dossier est refusée par verrou. Ne pas lancer non plus un second préflight ou bootstrap dans ce dossier pendant qu'une commande du lanceur y est encore active.

Avant un calcul R, le programme peut attendre que suffisamment de mémoire vive soit disponible. Cette attente de sécurité est indiquée dans `outputs/longitudinal_2000_v1/r_replication/king_ei_all_2x2_status.json`. Ne pas relancer une seconde commande. Garder la console ouverte et, si nécessaire, enregistrer son travail puis fermer les applications non indispensables. Le programme vérifie de nouveau la disponibilité et reprend automatiquement, sans changer les modèles. Par défaut, cette attente expire après 240 minutes : comme la mémoire est une ressource commune, son expiration arrête immédiatement le lot R afin de ne pas répéter la même attente jusqu'à 240 fois. Libérer la mémoire, puis utiliser explicitement `-ReessayerEchecs`.

En cas d'erreur technique, lire d'abord `JOURNAUX_REPRODUCTION/DERNIER_ECHEC.txt` : ce résumé indique le problème constaté et l'action proposée. `DERNIER_ECHEC.json` fournit le relevé structuré correspondant. Le lanceur PowerShell peut aussi écrire ce résumé lorsque Python n'est pas disponible. Les détails restent dans le journal général et le journal de l'étape ; les échecs d'estimation sont conservés séparément dans `.runtime/replication_v2/estimation_failures/`. Un succès complet marque le dernier échec comme résolu, sans en effacer silencieusement la trace.

Une panne technique ne doit pas être confondue avec un diagnostic scientifique défavorable : une estimation terminée avec un statut MCMC `caveat` ou `fail` reste livrée avec ce diagnostic. Elle n'est pas réestimée automatiquement pour obtenir un statut plus favorable. En cas de panne d'un calcul, les autres couples indépendants **du même lot** peuvent se terminer ; les étapes qui dépendent du lot incomplet, puis la certification finale, restent bloquées. Une erreur reconnue comme touchant les ressources communes, par exemple un manque de mémoire, de place disque ou de permissions, arrête le lot immédiatement. Le programme ne remplace jamais un calcul manquant par son résultat historique.

Lors de l'exécution initiale, ou après autorisation explicite de réessayer, une erreur transitoire reconnue peut entraîner **une seule nouvelle tentative automatique**. Un dépassement de temps n'est jamais relancé automatiquement : les autres couples indépendants peuvent continuer, mais le lot et la certification restent en échec tant que ce calcul manque. Une erreur persistante ou non reconnue est mémorisée et n'est pas répétée par défaut à chaque relance. Il n'y a ni boucle de relance, ni correction automatique des données ou du code, ni substitution depuis `longitudinal_2000_results.zip`, ni notification par courriel ou fenêtre spéciale.

Un lot complet implique de longs calculs MCMC. Laisser l'ordinateur alimenté, la console ouverte et éviter la mise en veille.

Après une interruption, conserver **la même commande, le même dossier, les mêmes données et le même code**, et vérifier que la précédente exécution est arrêtée. Les étapes achevées et les ajustements terminés sont conservés. Si l'arrêt s'est produit entre deux étapes, une relance ordinaire suffit. Si une estimation était en cours, sa tentative est mémorisée comme interrompue : elle n'est pas répétée automatiquement et nécessite `-ReessayerEchecs`, comme décrit ci-dessous. Un ajustement MCMC ainsi réautorisé recommence ; ses itérations partielles ne sont pas une estimation terminée.

Si un échec technique mémorisé bloque la reprise :

1. Lire `DERNIER_ECHEC.txt` et le journal indiqué. Corriger la cause externe identifiée, par exemple un espace disque insuffisant ou un fichier temporairement verrouillé ; après une interruption, vérifier notamment qu'aucun ancien processus ne poursuit le même calcul. Ne pas modifier les données, le code, les graines ou les réglages des modèles.
2. Après cette correction seulement, reprendre la commande initiale avec ses mêmes chemins et options, en ajoutant `-ReessayerEchecs`. Avec les chemins par défaut :

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\REPRODUIRE_TOUT.ps1 -ReessayerEchecs `
     -ExigerRessourcesRecommandees -MinimumFreeDiskGB 50 -MinimumAvailableMemoryGB 5
   ```

   Cette option autorise une nouvelle tentative des calculs bloqués ; elle ne force pas le recalcul des succès conservés et ne contourne ni les contrôles d'intégrité ni la certification.
3. Si la cause est inconnue, si l'erreur se répète ou si la comparaison scientifique échoue, transmettre à l'auteur `DERNIER_ECHEC.txt`, `DERNIER_ECHEC.json`, le journal concerné et, s'il existe, le rapport de certification. Ne pas multiplier les relances ni changer les seuils pour faire passer le contrôle.

Si une correction exige un nouveau code ou de nouvelles données, utiliser le paquet corrigé dans **un nouveau dossier d'extraction**. Le contrôle d'empreinte refuse de mélanger ces versions avec les calculs déjà produits ; `-ReessayerEchecs` ne lève pas ce refus. Conserver l'ancienne extraction et ses journaux pour le diagnostic.

## 7. Contrôles et état de validation

Les vérifications documentées couvrent les données et sorties attendues, les paramètres des 240 appels KRT, la gestion des erreurs, la reprise, les tests NLS sur données synthétiques et le contrôle numérique post-exécution. **L'exécution intégrale à partir des 31 archives brutes doit encore être effectuée au moins une fois sur une machine indépendante avant de présenter le paquet comme validé de bout en bout.** Le rapport JSON de certification de cette exécution constitue alors la preuve de comparaison.

Le contrôle de présence des sorties est distinct de la comparaison numérique avec les résultats de référence. Après exécution, examiner les nouvelles estimations et leurs diagnostics. Les passages interprétatifs conservés dans les rapports doivent être confrontés aux tables recalculées. Les estimations utilisent les matrices reconstruites à partir des données sources.

La révision technique finale conserve l'ordre et les estimateurs des 17 étapes du rejeu intégral. L'orchestration, les consolidations, les diagnostics et les producteurs de livrables utilisent une chaîne de production commune. La commande professeur ci-dessus demande toujours le périmètre intégral. Les réglages individuels des modèles et les seuils diagnostiques restent ceux des contrats figés ; seuls les contrôles préalables, la portabilité technique, la traçabilité et les bornes d'exécution ont été renforcés.

Les corrections portent sur l'assemblage des tables finales, le choix des graines R historiques, les contrôles des valeurs manquantes, la provenance et la reprise des nouvelles exécutions. Les tolérances numériques ne sont pas élargies. Le relevé `reproducibility/contract_v2/CHANGEMENTS_FICHIERS.csv` décrit les empreintes avant et après correction. Les archives de résultats historiques fournies séparément restent inchangées.
