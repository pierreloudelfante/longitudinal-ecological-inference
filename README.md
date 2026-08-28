# Longitudinal Ecological Inference — Fixed Panel of 2,000 Municipalities

This research repository estimates ecological-inference models across 26
French elections using a fixed longitudinal panel of 2,000 municipalities. It
contains work in progress: intermediate results are not a validated release.

## Current analysis contract

- panel: `panel/longitudinal_2000_v1.parquet`;
- identifier: `longitudinal_2000_v1__strict_nested_3000__seed_20260803`;
- SHA-256: `bde70c71660fce29610d7931461d8db6181dba874514a1866b63cf16a81cec4a`;
- NLS: 292 prepared and estimated specifications, including 270 in the public
  v1.0.2 scope and 22 RxC specifications retained as an audited extension;
- Python KRT: 240 expected 2×2 specifications for H0A–H7, with H6/H7 eligible
  for 16 elections each;
- R KRT: exact NIMBLE replication planned after the initial Python runs and
  targeted retries are complete;
- NetCDF: temporary post-processing artifacts excluded from delivery archives.

The latest machine-readable coverage status is written to:

```text
outputs/longitudinal_2000_v1/production/current_estimation_coverage.json
```

Partial KRT selections and tables are written to:

```text
outputs/longitudinal_2000_v1/production/all_2x2_candidate/
```

## Pipeline overview

```text
source archives
  -> political and social data auditing and harmonization
  -> fixed longitudinal panel and model-ready matrices
  -> Python/R NLS
  -> Python KRT initial run
  -> MCMC diagnostics | ecological identification | KRT–NLS warning
  -> one targeted retry for severe/failed MCMC
  -> canonical selection
  -> exact R/NIMBLE KRT replication
  -> Python/R comparison
  -> verified Parquet files, figures, report, and archives
```

The following diagnostics remain separate:

1. `mcmc_status` measures numerical sampling quality;
2. `identification_status` describes the width of the ecological constraints;
3. `method_sensitivity_status` flags a KRT–NLS discrepancy and never changes
   priors or `king_lambda` opportunistically.

## Authoritative configuration

Each KRT production run is defined by a file in `config/releases/`. The release
scope specifies the panel, scenarios, pilots, versioned KRT parameterization,
`king_lambda`, MCMC settings, and random seeds. `config/run_settings.json`
remains necessary for data preparation and compatibility with older scripts,
but it does not replace the release-level KRT contract.

Examples:

```text
config/releases/v1.1_pymc_fallback.json   H2/H3
config/releases/v1.2_pymc_h6_h7.json      H6/H7
config/releases/v1.3_pymc_h0b_h0c.json    H0B/H0C
config/releases/v1.4_pymc_h4_h5.json      H4/H5
```

Production runs use four chains, 1,000 warmup iterations, 1,000 retained draws,
`target_accept=0.99`, `max_treedepth=14`, and a deterministic seed for each
specification. An eligible retry uses 2,000 warmup iterations, 2,000 retained
draws, and its dedicated base seed.

## Important inputs and outputs

| Item | Location | Grain |
|---|---|---|
| Panel | `panel/longitudinal_2000_v1.parquet` | municipality |
| Model-ready matrices | `outputs/model_ready/` | municipality × election × scenario |
| Runs | `outputs/runs/<run_id>/` | one model fit |
| Coverage | `outputs/longitudinal_2000_v1/production/current_estimation_coverage.csv` | scenario |
| Partial municipality-level KRT | `outputs/longitudinal_2000_v1/production/all_2x2_candidate/longitudinal_krt_commune_240_candidate.parquet` | municipality × run |
| Partial aggregate KRT | `outputs/longitudinal_2000_v1/production/all_2x2_candidate/longitudinal_krt_aggregate_240_candidate.parquet` | run × estimand |
| Partial selection | `outputs/longitudinal_2000_v1/production/all_2x2_candidate/krt_240_candidate_selection.csv` | election × scenario |
| Complete candidate NLS | `outputs/longitudinal_2000_v1/production/rxc_nls_panel_extension_v11/longitudinal_nls_292_candidate.parquet` | specification × estimand |
| Exact R replication | `outputs/longitudinal_2000_v1/r_replication/` | specification × estimand |

## Main commands

From the repository root, with the ecological-inference Python environment
activated:

```powershell
python -m code_longitudinal.v11_pipeline krt `
  --release-config config\releases\v1.1_pymc_fallback.json `
  --cores 1

python -m code_longitudinal.consolidate_current_krt_all_2x2
python -m code_longitudinal.build_current_estimation_coverage
python -m pytest -q tests
```

Restart scripts inspect success manifests before each fit. A successful run with
the same contract is not recomputed.

## Reproducibility levels

- **Level 1 — audit:** inspect delivered Parquet files, CSV files, figures, and
  manifests; no source archive is required.
- **Level 2 — consolidation:** use the technical bundle, completed runs, and the
  documented environment.
- **Level 3 — full reproduction:** obtain the raw source archives separately,
  restore the local `panel/` and output inputs, and use the documented Python/R
  environments. Raw data and generated results are intentionally not stored in
  this repository.
