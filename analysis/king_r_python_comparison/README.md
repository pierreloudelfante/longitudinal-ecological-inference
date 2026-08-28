# Comparaison King 2×2 — Python PyEI vs R `ei`

Cette analyse compare deux implémentations de la famille d’inférence écologique 2×2 de King sur les mêmes lignes effectives, dans le même ordre.

- Panel nominal : `panel_3000_seed_20260802` (3 000 communes).
- Hypothèses : H0A (abstention) et H1 (vote à gauche).
- Élections : législatives 1962, 1986 et 2022.
- Python : PyEI 1.1.4, modèle `truncated_normal`, runs exploratoires déjà présents dans le dépôt.
- R : `ei` 1.3-3, maximum a posteriori puis 99 simulations par importance sampling.

Les lignes de frontière ou de tomographie dégénérée exclues par le code Python sont retirées **avant** l’appel R. Chaque CSV partagé est ensuite contrôlé contre l’ordre des `unit_id` du run Python correspondant et figé par SHA-256.

## Limite méthodologique importante

Les deux bibliothèques visent la famille King à normale tronquée, mais n’utilisent ni le même moteur de calcul ni une paramétrisation de prior strictement identique. Cette analyse mesure donc une robustesse inter-implémentations à entrées constantes ; elle ne constitue pas une réplication bit-à-bit de la postérieure. Elle ne compare pas non plus le modèle PyEI `king99` bêta-binomial KRT, qui n’a pas d’équivalent direct dans le paquet R `ei`.

## Reproduction

```powershell
python analysis/king_r_python_comparison/prepare_shared_inputs.py
& 'C:\Program Files\R\R-4.6.0\bin\Rscript.exe' analysis/king_r_python_comparison/run_r_ei.R
python analysis/king_r_python_comparison/compare_results.py
python analysis/king_r_python_comparison/build_notebook.py
python -m jupyter nbconvert --execute --to notebook --inplace analysis/king_r_python_comparison/king_r_python_comparison.ipynb
```
