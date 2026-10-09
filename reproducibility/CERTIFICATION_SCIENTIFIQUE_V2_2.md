# Protocole de certification scientifique v2.3

Le nom historique de ce fichier est conservé pour compatibilité avec les liens du paquet v2.2. La procédure décrite ici est celle de la v2.3, avec les corrections de portabilité du contrôle R et de la génération PDF Edge.

## Question testée

Le but n'est pas seulement de vérifier que le programme s'exécute. Le test porte sur la proposition suivante : en repartant des **31 archives brutes contractuelles**, le même pipeline de 17 étapes reproduit la structure, les données déterministes, les résultats statistiques et les diagnostics de l'archive de référence `longitudinal_2000_results.zip`.

## Pourquoi il y a 31 archives, et non 27

Les 27 archives initialement recensées correspondaient aux 26 scrutins et à l'archive CSP. Quatre sources socio-économiques effectivement utilisées avaient été omises de cette liste : taille des agglomérations/communes, revenus, capital immobilier et nationalités. Le contrat exécutable `contract_v2/raw_sources_31.json` contient les 31 noms, tailles et SHA-256. Le pipeline s'arrête avant toute estimation si une seule archive n'est pas résolue exactement.

L'estimation scientifique utilise donc **31 archives**. Aucun résultat n'est certifié à partir d'un sous-ensemble de 27.

## Pipeline identique

Le lanceur `REPRODUIRE_TOUT.ps1` appelle, dans cet ordre :

1. `panel`
2. `prepare`
3. `nls270`
4. `krt240`
5. `canonical52`
6. `consolidate240`
7. `r240`
8. `r_consolidate`
9. `nls_rxc22`
10. `coverage`
11. `covariates960`
12. `full_sources`
13. `assets`
14. `density480`
15. `report`
16. `verify`
17. `package`

La certification est un contrôle postérieur à l'étape 17. Elle ne change pas les estimateurs et ne remplace jamais un résultat recalculé par un fichier historique.

## Test en quatre niveaux

### 1. Sources et environnement

- 31/31 archives présentes ; taille et SHA-256 exacts ;
- archive de référence de 610 fichiers, SHA-256 `a5c0978e822e2276c7607764cfa74dd6ece8f135f2af1d290a8a880202cd5b79` ;
- Python 3.12.10, R 4.6.0 et dépendances verrouillées ;
- graines historiques conservées ; calcul numérique limité à un fil ; JAX en 64 bits ;
- versions, commandes, journaux et empreintes enregistrés.

### 2. Couverture et structure

- 610 chemins attendus, sans fichier manquant ni inattendu ;
- CRC valide dans les deux archives ;
- même nombre de lignes, mêmes colonnes, mêmes clés et même ordre logique pour les tables comparées ;
- mêmes identifiants, catégories, statuts d'exécution et indicateurs de diagnostics, hors champs explicitement volatils tels que la durée.

### 3. Résultats déterministes

Le panel et les NLS sont comparés numériquement avec des tolérances de `10^-12` à `10^-8`, selon la table. Toute différence substantielle, clé dupliquée, valeur manquante supplémentaire ou inversion de signe fait échouer la certification.

### 4. Résultats MCMC

Les tirages KRT et King EI sont pseudo-aléatoires. Des graines identiques rendent le calcul répétable dans un environnement identique, mais des différences de processeur, de bibliothèque mathématique ou d'ordonnancement peuvent modifier les derniers bits et parfois les tirages. C'est pourquoi deux qualifications sont produites :

- `exact_replay` : les 610 SHA-256 sont identiques ;
- `scientific_equivalence` : l'identité binaire n'est pas obtenue, mais tous les contrôles scientifiques passent.

Pour les centres MCMC agrégés, l'écart maximal est `max(0,0025 ; 10 % de la largeur de l'intervalle de référence)`. Pour les centres communaux, il est `max(0,005 ; 10 % de la largeur)`. Pour les bornes, les seuils sont respectivement `max(0,005 ; 15 %)` et `max(0,01 ; 15 %)`. Le signe des effets centraux sélectionnés et la position des intervalles agrégés par rapport à zéro doivent rester inchangés. Les règles complètes sont figées avant le test dans `contract_v2/certification_policy_v1.json`.

Ces seuils établissent une équivalence scientifique opérationnelle ; ils ne prétendent pas démontrer l'identité des chaînes de Monte-Carlo.

### 5. Figures, rapport et documentation

Les fichiers non tabulaires ne sont pas simplement comptés. Chaque PNG différent est décodé et comparé pixel par pixel (dimensions identiques, erreur absolue moyenne au plus 1 %, RMSE au plus 8 % et au plus 15 % de pixels modifiés au-delà de 8/255). Les SVG conservent la même structure textuelle et leurs coordonnées numériques restent dans les seuils préenregistrés. Les HTML et Markdown gardent le même squelette, les mêmes entiers et des valeurs décimales tolérées ; les JSON sont comparés hors horodatages, durées, empreintes et tailles déjà vérifiés ailleurs. Le PDF doit être valide, conserver sa pagination et une taille cohérente ; son HTML source est contrôlé séparément. Toute extension inconnue ou tout écart hors seuil fait échouer la certification scientifique.

## Commandes historiques (le guide courant reste `../COMMENCER_ICI.md`)

Placer `longitudinal_2000_results.zip` à côté du lanceur, puis acquérir les 31 ZIP :

```powershell
powershell -ExecutionPolicy Bypass -File .\TELECHARGER_DONNEES_BRUTES.ps1
```

Contrôle sans estimation :

```powershell
powershell -ExecutionPolicy Bypass -File .\REPRODUIRE_TOUT.ps1 -PreflightSeulement `
  -ExigerRessourcesRecommandees -MinimumFreeDiskGB 50 -MinimumAvailableMemoryGB 5
```

Reproduction complète et certification automatique :

```powershell
powershell -ExecutionPolicy Bypass -File .\REPRODUIRE_TOUT.ps1 `
  -ExigerRessourcesRecommandees -MinimumFreeDiskGB 50 -MinimumAvailableMemoryGB 5
```

Rejouer seulement la certification d'une archive déjà calculée :

```powershell
python -m reproducibility.replication_complete certify `
  --reference-results .\longitudinal_2000_results.zip `
  --candidate-results .\deliverables\longitudinal_2000_results_recalcules.zip
```

## Preuves produites

- `.runtime/replication_v2/raw_sources_verified.json` : résolution et empreintes des 31 sources ;
- `.runtime/replication_v2/environment.json` : environnement exécuté ;
- `.runtime/replication_v2/state.json` et journaux d'étapes : progression, reprise et erreurs ;
- `deliverables/longitudinal_2000_results_recalcules.zip` : résultat recalculé ;
- `deliverables/longitudinal_2000_results_recalcules.certification.json` : verdict détaillé et différences ;
- `JOURNAUX_REPRODUCTION/` : transcription PowerShell complète.

Le paquet ne doit être présenté comme validé de bout en bout qu'après un calcul indépendant à partir des 31 archives et un statut final `exact_replay` ou `scientific_equivalence` dans le rapport de certification.
