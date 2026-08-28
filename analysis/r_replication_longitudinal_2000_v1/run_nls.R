source(file.path(dirname(normalizePath(sub("^--file=", "", grep("^--file=", commandArgs(), value = TRUE)[[1]]), winslash = "/")), "common.R"))

softmax_rows <- function(eta) {
  shifted <- eta - apply(eta, 1L, max)
  exponentiated <- exp(shifted)
  exponentiated / rowSums(exponentiated)
}

unpack_probabilities <- function(params, n_groups, n_outcomes) {
  logits <- matrix(params, nrow = n_groups, ncol = n_outcomes - 1L, byrow = TRUE)
  softmax_rows(cbind(logits, 0))
}

fitted_margins <- function(params, x, n_outcomes) {
  pi <- unpack_probabilities(params, ncol(x), n_outcomes)
  x %*% pi
}

nls_objective <- function(params, x, t) {
  fitted <- fitted_margins(params, x, ncol(t))
  sum((t[, seq_len(ncol(t) - 1L), drop = FALSE] - fitted[, seq_len(ncol(t) - 1L), drop = FALSE])^2)
}

pooled_start <- function(x, t, epsilon = 1e-5) {
  beta <- qr.solve(x, t, tol = 1e-12)
  beta <- pmax(beta, epsilon)
  beta <- beta / rowSums(beta)
  logits <- log(beta[, seq_len(ncol(beta) - 1L), drop = FALSE] / beta[, ncol(beta)])
  as.vector(t(logits))
}

fit_one_nls <- function(election_id, scenario_id, n_starts = 20L, force = FALSE) {
  panel <- read_panel_primary()
  dat <- read_model_ready(election_id, scenario_id, panel)
  input_path <- attr(dat, "source_path")
  pair_key <- paste(election_id, scenario_id, sep = "__")
  output_dir <- file.path(RESULTS_DIR, "nls", pair_key)
  manifest_path <- file.path(output_dir, "manifest.json")
  if (file.exists(manifest_path) && !force) {
    existing <- read_json_file(manifest_path)
    if (identical(existing$status, "success") && identical(existing$input_sha256, sha256_file(input_path))) {
      message("Loaded validated R NLS result: ", pair_key)
      return(existing)
    }
  }
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

  x_names <- grep("^X__", names(dat), value = TRUE)
  y_names <- grep("^Y__", names(dat), value = TRUE)
  n_names <- grep("^N__", names(dat), value = TRUE)
  x <- as.matrix(data.frame(lapply(dat[x_names], as.numeric), check.names = FALSE))
  y <- as.matrix(data.frame(lapply(dat[y_names], as.numeric), check.names = FALSE))
  n <- as.numeric(dat$N_g)
  t <- y / n
  n_parameters <- ncol(x) * (ncol(t) - 1L)
  if (n_starts < 2L) stop("NLS requires at least two starts.")
  set.seed(RANDOM_SEED, kind = "Mersenne-Twister", normal.kind = "Inversion")
  starts <- list(pooled_start(x, t), rep(0, n_parameters))
  if (n_starts > 2L) {
    starts <- c(starts, replicate(n_starts - 2L, rnorm(n_parameters, 0, 0.5), simplify = FALSE))
  }

  started <- proc.time()[["elapsed"]]
  fit_rows <- vector("list", length(starts))
  fits <- vector("list", length(starts))
  for (index in seq_along(starts)) {
    fit <- optim(
      par = starts[[index]],
      fn = nls_objective,
      x = x,
      t = t,
      method = "BFGS",
      control = list(maxit = 5000L, reltol = 1e-9)
    )
    fits[[index]] <- fit
    fit_rows[[index]] <- data.frame(
      start_index = index - 1L,
      start_type = if (index == 1L) "pooled_ols_logit" else if (index == 2L) "zero" else "random",
      convergence = fit$convergence,
      success = fit$convergence == 0L,
      objective_sse_unweighted = fit$value,
      function_evaluations = unname(fit$counts[["function"]]),
      gradient_evaluations = unname(fit$counts[["gradient"]]),
      coefficients_json = jsonlite::toJSON(unname(fit$par), auto_unbox = TRUE),
      stringsAsFactors = FALSE
    )
  }
  finite <- which(vapply(fits, function(fit) is.finite(fit$value), logical(1)))
  if (!length(finite)) stop("No finite R NLS fit for ", pair_key)
  best_index <- finite[[which.min(vapply(fits[finite], function(fit) fit$value, numeric(1)))]]
  best <- fits[[best_index]]
  pi <- unpack_probabilities(best$par, ncol(x), ncol(t))
  fitted <- x %*% pi
  elapsed <- proc.time()[["elapsed"]] - started

  estimate_rows <- list()
  cursor <- 0L
  for (group_index in seq_along(n_names)) {
    group <- sub("^N__", "", n_names[[group_index]])
    for (outcome_index in seq_along(y_names)) {
      cursor <- cursor + 1L
      estimate_rows[[cursor]] <- data.frame(
        election_id = election_id,
        scenario_id = scenario_id,
        engine = "R_base_optim_BFGS",
        model_key = "rosen_nls_r_matched",
        social_group = group,
        vote_category = sub("^Y__", "", y_names[[outcome_index]]),
        estimate = pi[group_index, outcome_index],
        n_communes_used = nrow(dat),
        N_total = sum(n),
        stringsAsFactors = FALSE
      )
    }
  }
  estimates <- do.call(rbind, estimate_rows)
  coefficients <- data.frame(
    social_group = rep(sub("^N__", "", n_names), each = ncol(t) - 1L),
    vote_category = rep(sub("^Y__", "", y_names[-length(y_names)]), times = ncol(x)),
    reference_vote_category = sub("^Y__", "", tail(y_names, 1L)),
    term = "alpha",
    estimate = best$par,
    stringsAsFactors = FALSE
  )
  start_diagnostics <- do.call(rbind, fit_rows)
  start_diagnostics$selected_best <- seq_len(nrow(start_diagnostics)) == best_index
  diagnostics <- data.frame(
    election_id = election_id,
    scenario_id = scenario_id,
    engine = "R_base_optim_BFGS",
    optimizer = "stats::optim(method='BFGS')",
    optimizer_success = best$convergence == 0L,
    optimizer_status = best$convergence,
    objective_sse_unweighted = best$value,
    max_abs_fitted_margin_error = max(abs(t[, -ncol(t), drop = FALSE] - fitted[, -ncol(t), drop = FALSE])),
    n_parameters = length(best$par),
    n_starts = length(starts),
    n_successful_starts = sum(vapply(fits, function(fit) fit$convergence == 0L, logical(1))),
    elapsed_seconds = elapsed,
    stringsAsFactors = FALSE
  )
  write.csv(estimates, file.path(output_dir, "r_nls_estimates.csv"), row.names = FALSE, fileEncoding = "UTF-8")
  write.csv(coefficients, file.path(output_dir, "r_nls_coefficients.csv"), row.names = FALSE, fileEncoding = "UTF-8")
  write.csv(start_diagnostics, file.path(output_dir, "r_nls_start_diagnostics.csv"), row.names = FALSE, fileEncoding = "UTF-8")
  write.csv(diagnostics, file.path(output_dir, "r_nls_diagnostics.csv"), row.names = FALSE, fileEncoding = "UTF-8")

  manifest <- list(
    status = "success",
    generated_at_utc = utc_now(),
    election_id = election_id,
    scenario_id = scenario_id,
    panel_id = PANEL_ID,
    sample_size = nrow(dat),
    exact_panel_order_match = TRUE,
    spec_version = SPEC_VERSION,
    harmonization_version = HARMONIZATION_VERSION,
    input_path = relative_path(input_path),
    input_sha256 = sha256_file(input_path),
    engine = "R stats::optim BFGS",
    objective = "same unweighted Rosen NLS ecological-margin SSE as Python",
    parameterization = "same reference-category softmax; intercept-only longitudinal v1 specification",
    n_starts = length(starts),
    start_scale = 0.5,
    tolerance = 1e-9,
    max_evaluations = 5000L,
    random_seed = RANDOM_SEED,
    rng_note = "R Mersenne-Twister random starts; Python uses NumPy PCG64. Pooled and zero starts and the mathematical objective are identical.",
    objective_sse_unweighted = best$value,
    optimizer_success = best$convergence == 0L,
    output_dir = relative_path(output_dir)
  )
  write_json_file(manifest, manifest_path)
  message(sprintf("Completed R NLS %s: n=%d, SSE=%.12g, %.2fs", pair_key, nrow(dat), best$value, elapsed))
  manifest
}

options <- parse_options()
plan <- read_run_plan()
if (options$all) {
  selected <- plan[plan$preparation_status == "admissible", c("election_id", "scenario_id"), drop = FALSE]
} else {
  selected <- data.frame(election_id = options$election, scenario_id = options$scenario, stringsAsFactors = FALSE)
  row <- plan[plan$election_id == options$election & plan$scenario_id == options$scenario, , drop = FALSE]
  if (nrow(row) != 1L || row$preparation_status[[1]] != "admissible") {
    stop("Requested pair is not admissible in the frozen run plan.")
  }
}

summary_rows <- list()
for (index in seq_len(nrow(selected))) {
  result <- tryCatch(
    fit_one_nls(selected$election_id[[index]], selected$scenario_id[[index]], options$starts, options$force),
    error = function(error) list(
      status = "failed",
      election_id = selected$election_id[[index]],
      scenario_id = selected$scenario_id[[index]],
      error = conditionMessage(error)
    )
  )
  summary_rows[[index]] <- data.frame(
    election_id = selected$election_id[[index]],
    scenario_id = selected$scenario_id[[index]],
    status = result$status,
    error = if (is.null(result$error)) "" else result$error,
    stringsAsFactors = FALSE
  )
  if (identical(result$status, "failed")) message("FAILED: ", result$error)
}
summary_frame <- do.call(rbind, summary_rows)
write.csv(summary_frame, file.path(RESULTS_DIR, "nls_execution_summary.csv"), row.names = FALSE, fileEncoding = "UTF-8")
if (any(summary_frame$status == "failed")) quit(status = 2L)
