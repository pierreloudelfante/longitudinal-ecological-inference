# Manifeste de l'implémentation

L'implémentation canonique se trouve intégralement dans `ARE/part2/longitudinal_2022/`. Les données brutes et les anciens résultats n'ont pas été modifiés.

## Fichiers de code et de configuration créés

- `code_longitudinal/__init__.py`
- `code_longitudinal/balance_checks.py`
- `code_longitudinal/beta_outputs.py`
- `code_longitudinal/build_manifest.py`
- `code_longitudinal/build_illustrated_report.py`
- `code_longitudinal/build_professor_global_recap.py`
- `code_longitudinal/build_figure_catalog.py`
- `code_longitudinal/build_outputs.py`
- `code_longitudinal/build_panel.py`
- `code_longitudinal/build_release.py`
- `code_longitudinal/data_io.py`
- `code_longitudinal/extract_latent_densities.py`
- `code_longitudinal/nls.py`
- `code_longitudinal/output_schema.py`
- `code_longitudinal/paths.py`
- `code_longitudinal/plot_longitudinal.py`
- `code_longitudinal/prepare_inputs.py`
- `code_longitudinal/prepare_all_partitions.py`
- `code_longitudinal/pilot_outputs.py`
- `code_longitudinal/review_package.py`
- `code_longitudinal/run_2x2_batch.py`
- `code_longitudinal/run_nls_batch.py`
- `code_longitudinal/run_pipeline.py`
- `code_longitudinal/run_pilot_ladder.py`
- `code_longitudinal/run_registry.py`
- `code_longitudinal/run_robustness.py`
- `code_longitudinal/run_rosen_benchmark.py`
- `code_longitudinal/spec_registry.py`
- `code_longitudinal/utils.py`
- `code_longitudinal/validate_outputs.py`
- `config/run_settings.json`
- `requirements-dev.txt`
- `README.md`

## Documentation et tests créés

- `docs/SCRIPT_GUIDE.md`
- `docs/BALANCE_TESTS.md`
- `docs/METHODOLOGY_CODE_MAP.md`
- `docs/RESULTS_TRANSPARENCY.md`
- `docs/ALL_ELECTION_PARTITIONS_REPORT.md`
- `docs/PILOT_1962_1986_2022_REPORT.md`
- `docs/RESULTS_ILLUSTRATED_1962_1986_2022.md`
- `docs/PROFESSOR_GLOBAL_RECAP_1962_1986_2022.md`
- `docs/FIGURE_CATALOG.md` (généré après les figures)
- `docs/ELECTION_2022_PRODUCTION_REPORT.md`
- `docs/RELEASE_README.md`
- `docs/LONGITUDINAL_AUDIT.md`
- `docs/OUTPUT_SCHEMA.md`
- `docs/VALIDATION_REPORT.md` (généré par la validation)
- `docs/IMPLEMENTATION_MANIFEST.md`
- `tests/conftest.py`
- `tests/test_nls.py`
- `tests/test_outputs.py`
- `tests/test_illustrated_report.py`
- `tests/test_panel.py`
- `tests/test_partitions.py`

## Inventaire exact des artefacts

`outputs/file_manifest.csv` contient le chemin relatif, le rôle, la taille et le SHA-256 de chaque fichier livré : panels, tables CSV/Parquet, model-ready, manifests de runs, traces NetCDF, figures PNG/SVG et paquet professeur. Les caches transitoires, les `__pycache__` et le fichier d'inventaire lui-même en sont exclus explicitement.
