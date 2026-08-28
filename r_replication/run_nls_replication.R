args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 4L) {
  stop("usage: run_nls_replication.R MODEL_READY_CSV STARTS_CSV OUTPUT_CSV DIAGNOSTICS_JSON")
}

root <- normalizePath(file.path(dirname(args[[1L]]), "..", ".."), mustWork = FALSE)
local_library <- normalizePath(file.path(getwd(), ".r_lib"), mustWork = FALSE)
.libPaths(c(local_library, .libPaths()))
suppressPackageStartupMessages(library(data.table))
suppressPackageStartupMessages(library(jsonlite))

input_path <- args[[1L]]
starts_path <- args[[2L]]
output_path <- args[[3L]]
diagnostics_path <- args[[4L]]

frame <- fread(input_path, showProgress = FALSE)
x_columns <- grep("^X__", names(frame), value = TRUE)
y_columns <- grep("^Y__", names(frame), value = TRUE)
if (length(x_columns) < 2L || length(y_columns) < 2L) {
  stop("model-ready input must contain at least two X__ and Y__ columns")
}
x <- as.matrix(frame[, ..x_columns])
y <- as.matrix(frame[, ..y_columns])
n <- as.numeric(frame[["N_g"]])
t <- y / n
n_groups <- ncol(x)
n_outcomes <- ncol(t)
n_parameters <- n_groups * (n_outcomes - 1L)

probabilities <- function(params) {
  logits <- matrix(0, nrow = n_groups, ncol = n_outcomes)
  for (group_index in seq_len(n_groups)) {
    offset <- (group_index - 1L) * (n_outcomes - 1L)
    logits[group_index, seq_len(n_outcomes - 1L)] <- params[offset + seq_len(n_outcomes - 1L)]
  }
  logits <- logits - apply(logits, 1L, max)
  exp_logits <- exp(logits)
  exp_logits / rowSums(exp_logits)
}

objective <- function(params) {
  pi <- probabilities(params)
  fitted <- x %*% pi
  residual <- t[, seq_len(n_outcomes - 1L), drop = FALSE] - fitted[, seq_len(n_outcomes - 1L), drop = FALSE]
  sum(residual * residual)
}

gradient <- function(params) {
  pi <- probabilities(params)
  fitted <- x %*% pi
  residual <- t[, seq_len(n_outcomes - 1L), drop = FALSE] - fitted[, seq_len(n_outcomes - 1L), drop = FALSE]
  result <- numeric(n_parameters)
  for (group_index in seq_len(n_groups)) {
    for (parameter_outcome in seq_len(n_outcomes - 1L)) {
      derivative <- matrix(0, nrow = nrow(x), ncol = n_outcomes - 1L)
      for (fitted_outcome in seq_len(n_outcomes - 1L)) {
        indicator <- as.numeric(fitted_outcome == parameter_outcome)
        derivative[, fitted_outcome] <- x[, group_index] * pi[group_index, fitted_outcome] *
          (indicator - pi[group_index, parameter_outcome])
      }
      index <- (group_index - 1L) * (n_outcomes - 1L) + parameter_outcome
      result[index] <- -2 * sum(residual * derivative)
    }
  }
  result
}

starts_frame <- fread(starts_path, showProgress = FALSE)
starts <- lapply(starts_frame[["coefficients_json"]], fromJSON)
if (length(starts) != 20L || any(vapply(starts, length, integer(1L)) != n_parameters)) {
  stop("R replication requires the exact 20 Python start vectors")
}

started_at <- proc.time()[["elapsed"]]
fits <- lapply(starts, function(start) {
  optim(
    par = as.numeric(start),
    fn = objective,
    gr = gradient,
    method = "BFGS",
    control = list(maxit = 5000L, reltol = 1e-12)
  )
})
objectives <- vapply(fits, function(fit) fit$value, numeric(1L))
best_index <- which.min(objectives)
best <- fits[[best_index]]
pi <- probabilities(best$par)
weights <- x * n
aggregates <- matrix(NA_real_, nrow = n_groups, ncol = n_outcomes)
for (group_index in seq_len(n_groups)) {
  aggregates[group_index, ] <- colSums(weights[, group_index] * matrix(
    pi[group_index, ], nrow = nrow(x), ncol = n_outcomes, byrow = TRUE
  )) / sum(weights[, group_index])
}

output <- CJ(group_index = seq_len(n_groups), outcome_index = seq_len(n_outcomes))
output[, `:=`(
  election_id = as.character(frame[["election_id"]][1L]),
  scenario_id = as.character(frame[["scenario_id"]][1L]),
  social_group = sub("^X__", "", x_columns[group_index]),
  vote_category = sub("^Y__", "", y_columns[outcome_index]),
  estimate_r = aggregates[cbind(group_index, outcome_index)],
  n_communes = nrow(frame),
  objective_sse_unweighted_r = best$value,
  optimizer = "stats::optim_BFGS",
  convergence = best$convergence,
  best_start_index = best_index - 1L
)]
setcolorder(output, c(
  "election_id", "scenario_id", "social_group", "vote_category", "estimate_r",
  "n_communes", "objective_sse_unweighted_r", "optimizer", "convergence", "best_start_index"
))
dir.create(dirname(output_path), recursive = TRUE, showWarnings = FALSE)
fwrite(output, output_path)

diagnostics <- list(
  schema_version = "longitudinal_r_nls_diagnostics_v1",
  election_id = as.character(frame[["election_id"]][1L]),
  scenario_id = as.character(frame[["scenario_id"]][1L]),
  n_communes = nrow(frame),
  n_starts = length(starts),
  successful_starts = sum(vapply(fits, function(fit) fit$convergence == 0L, logical(1L))),
  best_start_index = best_index - 1L,
  objective_sse_unweighted_r = best$value,
  max_objective_difference = max(objectives) - min(objectives),
  max_abs_gradient = max(abs(gradient(best$par))),
  elapsed_seconds = proc.time()[["elapsed"]] - started_at,
  optimizer = "stats::optim_BFGS",
  input_csv = normalizePath(input_path, winslash = "/"),
  starts_csv = normalizePath(starts_path, winslash = "/")
)
write_json(diagnostics, diagnostics_path, auto_unbox = TRUE, pretty = TRUE, digits = 16)
