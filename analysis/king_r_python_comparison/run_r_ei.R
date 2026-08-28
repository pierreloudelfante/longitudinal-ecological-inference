args <- commandArgs(trailingOnly = TRUE)
script_arg <- grep("^--file=", commandArgs(), value = TRUE)
script_path <- normalizePath(sub("^--file=", "", script_arg[[1]]), winslash = "/")
analysis_dir <- dirname(script_path)
root_dir <- normalizePath(file.path(analysis_dir, "..", ".."), winslash = "/")
local_lib <- file.path(root_dir, ".r_lib")
.libPaths(c(local_lib, .libPaths()))

suppressPackageStartupMessages(library(ei))
suppressPackageStartupMessages(library(jsonlite))

manifest_path <- file.path(analysis_dir, "results", "comparison_manifest.csv")
output_dir <- file.path(analysis_dir, "results", "r_ei")
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
manifest <- read.csv(manifest_path, stringsAsFactors = FALSE, check.names = FALSE)
key_pattern <- if (length(args) >= 1) args[[1]] else ".*"
manifest <- manifest[grepl(key_pattern, manifest$comparison_key), , drop = FALSE]
if (nrow(manifest) == 0) stop("No comparison rows match: ", key_pattern)
prior_runtime_path <- file.path(output_dir, "r_runtime_manifest.csv")
prior_runtime <- if (file.exists(prior_runtime_path)) {
  read.csv(prior_runtime_path, stringsAsFactors = FALSE)
} else {
  data.frame()
}

quantiles <- function(x) {
  stats::quantile(x, probs = c(0.025, 0.5, 0.975), names = FALSE, type = 8)
}

aggregate_rows <- list()
diagnostic_rows <- list()
precinct_rows <- list()
runtime_rows <- list()

for (row_index in seq_len(nrow(manifest))) {
  meta <- manifest[row_index, , drop = FALSE]
  input_path <- file.path(analysis_dir, meta$shared_input[[1]])
  input_path <- normalizePath(input_path, winslash = "/")
  dat <- read.csv(input_path, stringsAsFactors = FALSE, colClasses = c(unit_id = "character"))
  if (nrow(dat) != meta$effective_n[[1]]) stop("Row-count mismatch for ", meta$comparison_key[[1]])
  if (anyDuplicated(dat$unit_id)) stop("Duplicate unit_id for ", meta$comparison_key[[1]])
  if (any(dat$x <= 0 | dat$x >= 1 | dat$t <= 0 | dat$t >= 1)) {
    stop("R input contains boundary fractions for ", meta$comparison_key[[1]])
  }
  if (max(abs(dat$N1 + dat$N2 - dat$N_g)) != 0) stop("Social counts do not close")
  if (max(abs(dat$Y1 + dat$Y2 - dat$N_g)) != 0) stop("Political counts do not close")

  captured_warnings <- character()
  rds_path <- file.path(output_dir, paste0(meta$comparison_key, "__fit.rds"))
  if (file.exists(rds_path)) {
    fit <- readRDS(rds_path)
    cached_row <- prior_runtime[prior_runtime$comparison_key == meta$comparison_key, , drop = FALSE]
    elapsed <- if (nrow(cached_row)) cached_row$elapsed_seconds[[1]] else NA_real_
    message(sprintf("Loaded cached %s", meta$comparison_key))
  } else {
    set.seed(20260802)
    started <- proc.time()[["elapsed"]]
    fit <- withCallingHandlers(
      ei(t ~ x, total = "N_g", id = "unit_id", data = dat),
      warning = function(w) {
        captured_warnings <<- c(captured_warnings, conditionMessage(w))
        invokeRestart("muffleWarning")
      }
    )
    elapsed <- proc.time()[["elapsed"]] - started
    saveRDS(fit, rds_path, compress = "xz")
  }

  if (!identical(dim(fit$betabs)[1], nrow(dat))) stop("betabs row mismatch")
  if (!identical(dim(fit$betaws)[1], nrow(dat))) stop("betaws row mismatch")
  nsim <- ncol(fit$betabs)
  b1_draws <- colSums(fit$betabs * dat$N1) / sum(dat$N1)
  b2_draws <- colSums(fit$betaws * dat$N2) / sum(dat$N2)
  contrast_draws <- b1_draws - b2_draws
  b1_q <- quantiles(b1_draws)
  b2_q <- quantiles(b2_draws)
  contrast_q <- quantiles(contrast_draws)

  aggregate_rows[[length(aggregate_rows) + 1]] <- data.frame(
    comparison_key = meta$comparison_key,
    election_id = meta$election_id,
    year = meta$year,
    scenario_id = meta$scenario_id,
    engine = "R ei 1.3-3",
    model = "king_truncated_normal",
    estimand = "b_1",
    social_group = meta$group_1,
    estimate = mean(b1_draws),
    lower = b1_q[[1]],
    median = b1_q[[2]],
    upper = b1_q[[3]],
    n_simulations = nsim,
    effective_n = nrow(dat),
    weight_total = sum(dat$N1),
    stringsAsFactors = FALSE
  )
  aggregate_rows[[length(aggregate_rows) + 1]] <- data.frame(
    comparison_key = meta$comparison_key,
    election_id = meta$election_id,
    year = meta$year,
    scenario_id = meta$scenario_id,
    engine = "R ei 1.3-3",
    model = "king_truncated_normal",
    estimand = "b_2",
    social_group = meta$group_2,
    estimate = mean(b2_draws),
    lower = b2_q[[1]],
    median = b2_q[[2]],
    upper = b2_q[[3]],
    n_simulations = nsim,
    effective_n = nrow(dat),
    weight_total = sum(dat$N2),
    stringsAsFactors = FALSE
  )
  aggregate_rows[[length(aggregate_rows) + 1]] <- data.frame(
    comparison_key = meta$comparison_key,
    election_id = meta$election_id,
    year = meta$year,
    scenario_id = meta$scenario_id,
    engine = "R ei 1.3-3",
    model = "king_truncated_normal",
    estimand = "b_1_minus_b_2",
    social_group = "contrast",
    estimate = mean(contrast_draws),
    lower = contrast_q[[1]],
    median = contrast_q[[2]],
    upper = contrast_q[[3]],
    n_simulations = nsim,
    effective_n = nrow(dat),
    weight_total = sum(dat$N_g),
    stringsAsFactors = FALSE
  )

  b1_summary <- cbind(
    mean = rowMeans(fit$betabs),
    sd = apply(fit$betabs, 1, stats::sd),
    t(apply(fit$betabs, 1, quantiles))
  )
  b2_summary <- cbind(
    mean = rowMeans(fit$betaws),
    sd = apply(fit$betaws, 1, stats::sd),
    t(apply(fit$betaws, 1, quantiles))
  )
  colnames(b1_summary) <- c("mean", "sd", "q025", "q50", "q975")
  colnames(b2_summary) <- c("mean", "sd", "q025", "q50", "q975")
  precinct_rows[[length(precinct_rows) + 1]] <- data.frame(
    comparison_key = meta$comparison_key,
    unit_id = dat$unit_id,
    sample_rank = dat$sample_rank,
    b1_mean = b1_summary[, "mean"],
    b1_sd = b1_summary[, "sd"],
    b1_q025 = b1_summary[, "q025"],
    b1_q50 = b1_summary[, "q50"],
    b1_q975 = b1_summary[, "q975"],
    b2_mean = b2_summary[, "mean"],
    b2_sd = b2_summary[, "sd"],
    b2_q025 = b2_summary[, "q025"],
    b2_q50 = b2_summary[, "q50"],
    b2_q975 = b2_summary[, "q975"],
    stringsAsFactors = FALSE
  )

  hessian <- (fit$hessianC + t(fit$hessianC)) / 2
  eigenvalues <- eigen(hessian, symmetric = TRUE, only.values = TRUE)$values
  positive_definite <- all(is.finite(eigenvalues)) && min(eigenvalues) > 0
  hessian_condition <- if (positive_definite) max(eigenvalues) / min(eigenvalues) else Inf
  reconstruction <- fit$betabs * dat$x + fit$betaws * (1 - dat$x)
  reconstruction_error <- max(abs(reconstruction - dat$t))
  beta_bound_violations <- sum(fit$betabs < -1e-12 | fit$betabs > 1 + 1e-12) +
    sum(fit$betaws < -1e-12 | fit$betaws > 1 + 1e-12)
  finite_draw_fraction <- mean(is.finite(fit$betabs)) * mean(is.finite(fit$betaws))
  unique_psi_rows <- nrow(unique(round(fit$psi, 12)))
  base_status <- if (
    positive_definite && beta_bound_violations == 0 &&
      reconstruction_error < 1e-8 && finite_draw_fraction == 1
  ) "pass" else "fail"
  diagnostic_status <- if (base_status == "pass") "caveat" else "fail"
  diagnostic_reason <- if (base_status == "pass") {
    "Fit and accounting checks pass; R ei uses 99 importance simulations and exposes no multi-chain R-hat/ESS."
  } else {
    "At least one optimizer/Hessian, finite-draw, bound, or accounting check failed."
  }
  diagnostic_rows[[length(diagnostic_rows) + 1]] <- data.frame(
    comparison_key = meta$comparison_key,
    election_id = meta$election_id,
    year = meta$year,
    scenario_id = meta$scenario_id,
    engine = "R ei 1.3-3",
    fit_status = "success",
    diagnostic_status = diagnostic_status,
    diagnostic_reason = diagnostic_reason,
    effective_n = nrow(dat),
    elapsed_seconds = elapsed,
    importance_simulations = nsim,
    unique_parameter_simulations = unique_psi_rows,
    importance_sampling_batches = fit$resamp,
    hessian_positive_definite = positive_definite,
    hessian_min_eigenvalue = min(eigenvalues),
    hessian_condition_number = hessian_condition,
    finite_draw_fraction = finite_draw_fraction,
    beta_bound_violations = beta_bound_violations,
    max_accounting_reconstruction_error = reconstruction_error,
    warning_count = length(unique(captured_warnings)),
    warnings = paste(unique(captured_warnings), collapse = " | "),
    stringsAsFactors = FALSE
  )
  runtime_rows[[length(runtime_rows) + 1]] <- data.frame(
    comparison_key = meta$comparison_key,
    input_path = meta$shared_input,
    input_sha256 = meta$shared_input_sha256,
    r_version = R.version.string,
    ei_version = as.character(packageVersion("ei")),
    eiPack_version = as.character(packageVersion("eiPack")),
    random_seed = 20260802,
    elapsed_seconds = elapsed,
    stringsAsFactors = FALSE
  )
  message(sprintf("Completed %s: n=%d, %.1fs", meta$comparison_key, nrow(dat), elapsed))
}

write.csv(do.call(rbind, aggregate_rows), file.path(output_dir, "r_aggregate_estimates.csv"), row.names = FALSE, fileEncoding = "UTF-8")
write.csv(do.call(rbind, diagnostic_rows), file.path(output_dir, "r_diagnostics.csv"), row.names = FALSE, fileEncoding = "UTF-8")
write.csv(do.call(rbind, precinct_rows), file.path(output_dir, "r_commune_latent_summaries.csv"), row.names = FALSE, fileEncoding = "UTF-8")
write.csv(do.call(rbind, runtime_rows), file.path(output_dir, "r_runtime_manifest.csv"), row.names = FALSE, fileEncoding = "UTF-8")
write_json(
  list(
    generated_at = format(Sys.time(), tz = "UTC", usetz = TRUE),
    r_version = R.version.string,
    package_versions = list(ei = as.character(packageVersion("ei")), eiPack = as.character(packageVersion("eiPack"))),
    comparison_keys = manifest$comparison_key,
    note = "R ei 2x2 uses maximum-posterior estimation plus 99 importance simulations; sample/burnin arguments apply only to RxC in this package."
  ),
  file.path(output_dir, "r_session_manifest.json"),
  pretty = TRUE,
  auto_unbox = TRUE
)
