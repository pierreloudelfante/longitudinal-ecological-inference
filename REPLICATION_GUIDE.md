# Replication guide

## Scope and provenance

This project studies 26 French elections from 1962 to 2022 on a fixed panel of 2,000 municipalities. The source project is `ARE/part2/longitudinal_2022`, historically prepared on branch `codex/finalisation-professeur-240` from commit `5b243c6b3b63f8cc4102182a65f9e88e714e1370`. The portable overlay was frozen on 8 October 2026.

Python KRT and R King EI are distinct estimators. The current portable launcher uses R `ei`/`eiPack`; experimental NIMBLE/CmdStan scripts remain available for audit but are not part of that launcher.

The workflow reconstructs inputs, estimates models, consolidates diagnostics and builds a candidate archive. Reference results are used only for comparison and never replace missing calculations.

## Obtain the replication materials

Use a fresh extraction of the portable package supplied in Dropbox under `Part2/00_CURRENT`. A Git clone does not contain its binary R library.

| Archive | Bytes | SHA-256 |
| --- | ---: | --- |
| `longitudinal_2000_reproduction_complete_PORTABLE_CERTIFICATION.zip` | 31,008,043 | `37948ed0862d63c206481bb61aa68234717644b4512ef2629fdf5ccc9caf65fc` |
| `longitudinal_2000_results.zip` | 143,246,075 | `a5c0978e822e2276c7607764cfa74dd6ece8f135f2af1d290a8a880202cd5b79` |

Keep the reference results ZIP unchanged beside `REPRODUIRE_TOUT.ps1`.

The raw-input contract requires **31 ZIP archives**, totalling **1,620,387,967 bytes**: 26 electoral archives and five socioeconomic archives. The Dropbox guide records a partial 27/31 raw-data mirror; use the acquisition script and authenticated manifest rather than assuming that mirror is complete.

Source URLs, accepted names, sizes and SHA-256 hashes are recorded in [raw_sources_31.json](reproducibility/contract_v2/raw_sources_31.json) and [DONNEES_REQUISES.csv](reproducibility/contract_v2/DONNEES_REQUISES.csv). Keep archives compressed. A filename alone does not authenticate an input.

## Environment

- Windows x86-64.
- Python **3.12.10**, with the Windows `py.exe` launcher and `pip`.
- R **4.6.0**.
- Edge or Chrome for PDF generation.
- 16 GB RAM, at least 5 GiB available memory and 50 GiB free disk space at launch.
- PyPI access for initial Python environment creation.

The launcher creates a local `.venv-reproduction/` and checks exact versions. The operative Python lock is [requirements-python312.lock.txt](reproducibility/requirements-python312.lock.txt), with `mistune==3.3.4` explicitly added for report rendering. Root-level historical requirements files are not installation instructions for this workflow.

The portable ZIP supplies the frozen Windows R library in `.cache/R/library`; it does not supply R itself. Its 33 packages are described in [r-runtime-library-manifest.json](reproducibility/r-runtime-library-manifest.json). Preflight authenticates the library and loads its 22 native-code packages.

Critical R packages include `ei 1.3.3`, `eiPack 0.2.2`, `jsonlite 2.0.0`, `digest 0.6.39`, `data.table 1.18.4`, `MASS 7.3-65` and `coda 0.19-4.1`.

## Run the workflow

Run commands from the fresh portable extraction, preferably outside a synchronised directory. The original French command names and options remain executable interfaces.

### 1. Download and authenticate inputs

```powershell
powershell -ExecutionPolicy Bypass -File .\TELECHARGER_DONNEES_BRUTES.ps1
```

This downloads inputs to `DONNEES_BRUTES/`, preserves valid existing archives and rejects size or hash mismatches. To verify an existing collection without downloading:

```powershell
powershell -ExecutionPolicy Bypass -File .\TELECHARGER_DONNEES_BRUTES.ps1 `
  -DossierDestination "D:\Data\Cage_Piketty" -VerifierSeulement
```

### 2. Run preflight without estimation

```powershell
powershell -ExecutionPolicy Bypass -File .\REPRODUIRE_TOUT.ps1 -PreflightSeulement `
  -ExigerRessourcesRecommandees -MinimumFreeDiskGB 50 -MinimumAvailableMemoryGB 5
```

Proceed only after the launcher reports:

```text
PREFLIGHT REUSSI - AUCUNE ESTIMATION N'A ETE LANCEE
```

For inputs stored elsewhere, add `-DossierDonneesBrutes "D:\Data\Cage_Piketty"` to both preflight and execution commands. Use `-RscriptExe` to provide the R executable when required.

### 3. Execute all 17 stages

```powershell
powershell -ExecutionPolicy Bypass -File .\REPRODUIRE_TOUT.ps1 `
  -ExigerRessourcesRecommandees -MinimumFreeDiskGB 50 -MinimumAvailableMemoryGB 5
```

Keep the computer powered and awake. Run only one launcher command at a time in an extraction, including preflight or environment bootstrap.

The scientific scope is 240 Python KRT fits, 240 R King EI fits, 292 baseline NLS fits (270 core and 22 RxC), 960 covariate NLS specifications and 480 municipality-level density figures. The final contract contains 610 files, including eight main tables and 580 figures. Computational coverage does not imply favourable scientific diagnostics.

## Outputs and monitoring

New outputs are written separately from the reference:

```text
deliverables/longitudinal_2000_results_recalcules.zip
deliverables/longitudinal_2000_results_recalcules.certification.json
```

The archive contains `00_README_PROFESSEUR.md`, `01_RAPPORT/`, `02_TABLES_PRINCIPALES/`, `03_FIGURES/`, `04_PANEL_ET_HARMONISATION/`, `05_DIAGNOSTICS/` and `06_DOCUMENTATION/`. PowerPoint presentations are separate materials and are outside the 610-file contract.

| Main table under `02_TABLES_PRINCIPALES/` | Required rows |
| --- | ---: |
| `longitudinal_contrasts_krt_r_nls.parquet` | 720 |
| `longitudinal_krt_aggregate.parquet` | 720 |
| `longitudinal_krt_commune.parquet` | 480,000 |
| `longitudinal_nls.parquet` | 2,370 |
| `longitudinal_nls_covariate_coefficients.parquet` | 6,720 |
| `longitudinal_nls_covariates.parquet` | 2,880 |
| `longitudinal_r_ei_aggregate.parquet` | 720 |
| `longitudinal_r_ei_commune.parquet` | 480,000 |

| Information | Location |
| --- | --- |
| Preflight | `JOURNAUX_REPRODUCTION/PREFLIGHT_DERNIER.txt` and `.json` |
| Overall progress | `.runtime/replication_v2/state.json` |
| Estimation heartbeats | `.runtime/replication_v2/estimation_processes/` |
| R memory waiting status | `outputs/longitudinal_2000_v1/r_replication/king_ei_all_2x2_status.json` |
| Failure and recovery command | `JOURNAUX_REPRODUCTION/DERNIER_ECHEC.txt` and `.json` |

The console displays `ETAPE n/17`: a stage number, not a completion percentage or time estimate.

## Interruptions and recovery

Completed stages and fits are preserved. Keep the same command, directory, inputs, code and model settings when resuming. Confirm that the previous process tree has stopped before restarting; `orphan_risk` means Windows could not confirm termination.

Read the failure summary and fix the external cause first. If an interrupted or failed fit blocks recovery, use the exact command recorded in the summary. With default paths:

```powershell
powershell -ExecutionPolicy Bypass -File .\REPRODUIRE_TOUT.ps1 -ReessayerEchecs `
  -ExigerRessourcesRecommandees -MinimumFreeDiskGB 50 -MinimumAvailableMemoryGB 5
```

This authorises another attempt for failed fits; it does not overwrite successful fits or bypass integrity and certification. Interrupted MCMC iterations are not completed fits.

Recognised transient failures may receive one automatic retry. Timeouts are never retried automatically. Persistent failures are remembered. Independent fits in the same batch may finish, but dependent stages and final certification remain blocked. Shared resource failures stop the batch. R memory waiting expires after 240 minutes by default; free memory before explicitly retrying.

If code or inputs must change, use a new extraction. Do not alter seeds, diagnostic thresholds or certification tolerances to obtain a pass. Preserve the previous extraction and logs for diagnosis.

## Certification and validation limits

The frozen [certification policy](reproducibility/contract_v2/certification_policy_v1.json) distinguishes:

- `rejeu_binaire_exact`: identical SHA-256 hashes for all 610 files.
- `equivalence_scientifique_numerique`: matching structure, scientific identifiers, statuses and diagnostics, with deterministic and MCMC quantities within preregistered tolerances.

Small cross-platform numerical differences may occur despite fixed seeds. Tolerances are fixed before candidate results are examined. Missing values must remain in the same positions. Technical run identifiers may be regenerated, but their consistency is checked.

Numerical MCMC diagnostics, ecological identification and method sensitivity are separate concepts. Unfavourable `caveat` or `fail` diagnostics remain visible and are not repaired by opportunistic changes to priors or `king_lambda`.

Documented checks include integrity checks, automated tests, clean-environment preflight and bounded scientific replays. **The full independent 610-output replay after the final infrastructure fix is not certified**: `full_610_run_certified=false`. Only the final certification JSON from a complete run can establish that result.

## Developer checks

```powershell
python -m reproducibility.replication_complete plan
python -m reproducibility.replication_complete integrity
python -m unittest discover -s reproducibility/tests_v2 -v
python -m pytest -q tests/test_nls.py
```

Orchestration tests substitute expensive engines where appropriate; passing them does not establish a full scientific rerun. NLS tests use synthetic data.

To compare an already-built candidate:

```powershell
python -m reproducibility.replication_complete certify `
  --reference-results .\longitudinal_2000_results.zip `
  --candidate-results .\deliverables\longitudinal_2000_results_recalcules.zip
```

Use the root portable launcher for full reproduction. Historical `capture` commands redefine references and are outside this verification workflow.

## Source consistency and language

On 13 November 2026, before this documentation update, all **284 GitHub files** matched the local publication worktree `_codex_work/github_academic_facade_20261009` by Git blob hash. Of these, **278 files** also matched the locally retained portable ZIP byte for byte; its SHA-256 matched the Dropbox guide. The six GitHub-only files were `.gitattributes`, `.gitignore`, `CITATION.cff`, `README.md` and two small test fixtures.

This comparison establishes source consistency with that frozen portable delivery. It does not certify a new estimation campaign or cover later, separately distributed presentation materials.

English documentation is an editorial layer. Original French filenames, runtime messages, historical documents and frozen manifests remain unchanged so that the portable package's integrity contract stays reproducible. The detailed original guide is [COMMENCER_ICI.md](COMMENCER_ICI.md).

## Citation and rights

Author: Pierre-Lou Delfante. Cite the repository and exact revision using [CITATION.cff](CITATION.cff). Raw data retain their providers' access and redistribution terms. The repository currently has no open-source software licence.
