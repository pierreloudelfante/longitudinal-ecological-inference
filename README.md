# Longitudinal Ecological Inference in France

Replication code for a study of **26 French elections (1962–2022)** using a fixed panel of **2,000 municipalities**. The pipeline combines Python KRT, R King EI and nonlinear least squares to estimate group-level electoral behaviour from aggregate data.

## What is included

- Data preparation, harmonisation and construction of the longitudinal panel.
- 240 Python KRT fits, 240 R King EI fits, 292 baseline NLS fits and 960 NLS specifications with covariates.
- Diagnostics, municipality-level densities, tables, figures and a reproducibility workflow targeting 610 output files.

## Getting started

Read the [English replication guide](REPLICATION_GUIDE.md) for setup, commands and recovery.

The Windows replication workflow requires Python **3.12.10**, R **4.6.0**, Edge or Chrome, and the portable package distributed separately with the reference results. Raw data and generated results are excluded from Git.

## Repository

| Directory | Purpose |
| --- | --- |
| `code_longitudinal/` | Python preparation, estimation and reporting |
| `r_replication/` | R estimators and density figures |
| `config/` | Model and release settings |
| `reproducibility/` | Orchestration, frozen contracts and certification |
| `tests/` | Scientific and structural checks |

## Replication status

Technical revision **v2.6** corresponds to the portable Dropbox delivery. Integrity checks, automated tests, clean-environment preflight and bounded scientific checks are documented. **A complete independent rerun of all 610 outputs after the final infrastructure fix remains uncertified** (`full_610_run_certified=false`).

Original French filenames, frozen documentation and machine-readable contracts are retained for compatibility. See the [English guide](REPLICATION_GUIDE.md) for provenance and validation details.

## Citation

Pierre-Lou Delfante. Cite this repository and the exact commit used; see [CITATION.cff](CITATION.cff). Source data retain their providers' terms. No open-source software licence is currently attached to this repository.
