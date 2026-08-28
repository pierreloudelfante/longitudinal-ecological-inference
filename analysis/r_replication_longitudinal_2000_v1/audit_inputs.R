source(file.path(dirname(normalizePath(sub("^--file=", "", grep("^--file=", commandArgs(), value = TRUE)[[1]]), winslash = "/")), "common.R"))

panel <- read_panel_primary()
plan <- read_run_plan()
if (length(unique(plan$election_id)) != 26L) stop("Run plan does not contain exactly 26 elections.")
if (nrow(plan) != 292L) stop("Run plan does not contain exactly 292 election/scenario pairs.")
admissible <- plan[plan$preparation_status == "admissible", , drop = FALSE]
if (nrow(admissible) != 270L) stop("Run plan does not contain exactly 270 admissible pairs.")

rows <- vector("list", nrow(admissible))
for (index in seq_len(nrow(admissible))) {
  election_id <- admissible$election_id[[index]]
  scenario_id <- admissible$scenario_id[[index]]
  dat <- read_model_ready(election_id, scenario_id, panel)
  check <- attr(dat, "input_check")
  source_path <- attr(dat, "source_path")
  rows[[index]] <- data.frame(
    election_id = election_id,
    scenario_id = scenario_id,
    model_family = admissible$model_family[[index]],
    preparation_status = "admissible",
    rows = check$rows,
    unique_unit_ids = check$unique_unit_ids,
    exact_panel_order_match = check$exact_panel_order_match,
    social_count_closure_max_abs = check$social_count_closure_max_abs,
    political_count_closure_max_abs = check$political_count_closure_max_abs,
    social_share_closure_max_abs = check$social_share_closure_max_abs,
    social_share_count_roundtrip_max_abs = check$social_share_count_roundtrip_max_abs,
    N_total = check$N_total,
    source_path = relative_path(source_path),
    source_sha256 = sha256_file(source_path),
    stringsAsFactors = FALSE
  )
  if (index %% 25L == 0L) message("Validated ", index, "/", nrow(admissible), " model-ready inputs")
}

contract <- do.call(rbind, rows)
output_csv <- file.path(RESULTS_DIR, "input_contract.csv")
write.csv(contract, output_csv, row.names = FALSE, fileEncoding = "UTF-8")
manifest <- list(
  generated_at_utc = utc_now(),
  spec_version = SPEC_VERSION,
  harmonization_version = HARMONIZATION_VERSION,
  panel_id = PANEL_ID,
  panel_csv = relative_path(PANEL_CSV),
  panel_csv_sha256 = sha256_file(PANEL_CSV),
  panel_parquet_sha256 = read_json_file(PANEL_MANIFEST)$panel_sha256,
  primary_panel_rows = nrow(panel),
  primary_unique_unit_ids = length(unique(panel$unit_id)),
  elections = length(unique(plan$election_id)),
  classified_pairs = nrow(plan),
  admissible_pairs = nrow(admissible),
  inadmissible_pairs = sum(plan$preparation_status != "admissible"),
  all_model_ready_inputs_present = TRUE,
  all_exact_panel_order_match = all(contract$exact_panel_order_match),
  all_social_counts_close = max(contract$social_count_closure_max_abs) == 0,
  all_political_counts_close = max(contract$political_count_closure_max_abs) == 0,
  input_contract_csv = relative_path(output_csv),
  input_contract_sha256 = sha256_file(output_csv)
)
write_json_file(manifest, file.path(RESULTS_DIR, "input_contract_manifest.json"))
message("Validated exactly ", nrow(contract), " admissible model-ready files on the same 2,000 unit_id values and order.")
