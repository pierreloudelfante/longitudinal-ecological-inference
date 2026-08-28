# Configuration d'exécution

`run_settings.json` centralise les paramètres qui peuvent changer sans modifier le code : tailles et graine du panel, seuils de balance, tolérance comptable, paliers PyEI, budgets temps/mémoire, diagnostics MCMC, paramètres NLS et scénarios pilotes.

Le registre des élections et la définition conceptuelle des scénarios restent dans `../code_longitudinal/spec_registry.py`, car ils sont validés comme du code et couverts par les tests.

## Règles

- Le format est JSON ; aucune dépendance YAML n'est nécessaire.
- Les probabilités et fractions sont exprimées entre 0 et 1.
- Les durées limites sont en heures dans la configuration, puis converties en secondes par le code.
- Une modification de configuration change la configuration statistique du run et doit produire une nouvelle clé d'exécution.
- Ne pas abaisser un seuil diagnostique pour rendre artificiellement un run acceptable.

Les valeurs de production prévues sont quatre chaînes, 1 000 draws, 1 000 itérations de réglage et `target_accept=0.99`.

