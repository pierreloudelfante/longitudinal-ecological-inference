suppressPackageStartupMessages({
  library(jsonlite)
  library(MASS)
})

args <- commandArgs(trailingOnly = TRUE)
root <- if (length(args) >= 1L) args[[1]] else getwd()
root <- normalizePath(root, mustWork = TRUE, winslash = "/")
input_dir <- if (length(args) >= 2L) args[[2]] else file.path(root, "work", "density_all_pairs", "data")
output_root <- if (length(args) >= 3L) args[[3]] else file.path(root, "deliverables", "longitudinal_2000_densites_completes")
input_dir <- normalizePath(input_dir, mustWork = TRUE, winslash = "/")
input_manifest <- fromJSON(file.path(input_dir, "density_inputs_manifest.json"))
expected_pairs <- as.integer(input_manifest$expected_pairs_per_method)
if (length(expected_pairs) != 1L || is.na(expected_pairs) || expected_pairs < 1L) {
  stop("invalid expected pair count in validated density input manifest")
}
expected_figures <- 2L * expected_pairs
dir.create(output_root, recursive = TRUE, showWarnings = FALSE)
output_root <- normalizePath(output_root, mustWork = TRUE, winslash = "/")

method_specs <- list(
  list(id = "krt_python", input = "density_inputs_krt_python.csv", folder = "01_KRT_PYTHON", label = "KRT beta-binomial - Python/NumPyro"),
  list(id = "r_eipack", input = "density_inputs_r_eipack.csv", folder = "02_R_EI", label = "King EI normale tronquee - R/eiPack")
)

blue <- "#2457A7"
orange <- "#D97706"
ink <- "#20242A"
muted <- "#5B6472"
grid <- "#D8DDE5"
palette_joint <- hcl.colors(72L, palette = "Blues 3", rev = TRUE)

strip_utf8_bom <- function(value) {
  bytes <- charToRaw(value)
  if (length(bytes) >= 3L && identical(as.integer(bytes[1:3]), c(239L, 187L, 191L))) {
    return(rawToChar(bytes[-(1:3)]))
  }
  value
}

read_csv_portable <- function(path) {
  frame <- read.csv(path, stringsAsFactors = FALSE, check.names = FALSE, na.strings = c("", "NA", "NaN"))
  names(frame) <- vapply(names(frame), strip_utf8_bom, character(1L), USE.NAMES = FALSE)
  frame
}

election_metadata <- function(election_id) {
  parts <- strsplit(election_id, "_", fixed = TRUE)[[1]]
  data.frame(
    election_id = election_id,
    election_type = if (identical(parts[[1]], "leg")) "legislative" else "presidential",
    year = as.integer(parts[[2]]),
    round = as.integer(sub("r", "", parts[[3]], fixed = TRUE)),
    stringsAsFactors = FALSE
  )
}

safe_bandwidth <- function(values) {
  values <- values[is.finite(values)]
  if (length(values) < 2L || diff(range(values)) < 1e-10) return(0.02)
  bandwidth <- suppressWarnings(bw.nrd0(values))
  if (!is.finite(bandwidth) || bandwidth <= 0) bandwidth <- max(sd(values) * 0.25, 0.01)
  max(min(bandwidth, 0.15), 0.005)
}

weighted_density <- function(values, weights, bandwidth, axis) {
  selected <- is.finite(values) & is.finite(weights) & weights > 0
  values <- values[selected]
  weights <- weights[selected]
  if (length(values) < 2L || sum(weights) <= 0) return(rep(NA_real_, length(axis)))
  estimate <- density(
    values,
    weights = weights / sum(weights),
    bw = bandwidth,
    from = min(axis),
    to = max(axis),
    n = length(axis),
    cut = 0
  )
  approx(estimate$x, estimate$y, xout = axis, rule = 2)$y
}

joint_density <- function(frame, h, axis) {
  selected <- is.finite(frame$b1_mean) & is.finite(frame$b2_mean)
  x <- frame$b1_mean[selected]
  y <- frame$b2_mean[selected]
  if (length(x) < 25L) return(NULL)
  kde2d(x, y, h = h, n = length(axis), lims = c(0, 1, 0, 1))
}

draw_pair <- function(path, device, frame, metadata, method_label, scenario_id, bandwidths, joint_h) {
  if (device == "png") {
    png(path, width = 2100, height = 760, res = 150)
  } else {
    svg(path, width = 14, height = 5.1, pointsize = 10)
  }
  on.exit(dev.off(), add = TRUE)
  old <- par(no.readonly = TRUE)
  on.exit(par(old), add = TRUE)
  layout(matrix(c(1, 2, 3), nrow = 1L), widths = c(1.18, 1, 1))
  par(oma = c(1.0, 0.8, 4.0, 0.8), mar = c(4.3, 4.4, 3.0, 1.0))

  axis <- seq(0, 1, length.out = 101L)
  joint <- joint_density(frame, joint_h, axis)
  finite_both <- sum(is.finite(frame$b1_mean) & is.finite(frame$b2_mean))
  finite_b1 <- sum(is.finite(frame$b1_mean))
  finite_b2 <- sum(is.finite(frame$b2_mean))

  if (is.null(joint)) {
    plot.new()
    text(0.5, 0.5, "Donnees insuffisantes", col = muted)
  } else {
    image(joint$x, joint$y, joint$z, col = palette_joint, xlim = c(0, 1), ylim = c(0, 1),
          xlab = expression(beta[1]), ylab = expression(beta[2]), main = "Densite jointe communale", useRaster = TRUE)
    contour(joint$x, joint$y, joint$z, add = TRUE, drawlabels = FALSE, col = adjustcolor(ink, 0.55), lwd = 0.8)
    abline(0, 1, col = orange, lty = 2, lwd = 1.5)
    selected <- is.finite(frame$b1_mean) & is.finite(frame$b2_mean)
    points(frame$b1_mean[selected], frame$b2_mean[selected], pch = 16, cex = 0.13, col = adjustcolor(ink, 0.15))
    box(col = muted)
  }

  b1_density <- weighted_density(frame$b1_mean, frame$b1_weight, bandwidths[["b1"]], axis)
  plot(axis, b1_density, type = "n", xlim = c(0, 1), ylim = c(0, max(b1_density, na.rm = TRUE) * 1.06),
       xlab = expression(beta[1]), ylab = "Densite ponderee", main = expression("Marginale " * beta[1]))
  grid(col = grid)
  polygon(c(axis, rev(axis)), c(rep(0, length(axis)), rev(b1_density)), col = adjustcolor(blue, 0.16), border = NA)
  lines(axis, b1_density, lwd = 2.4, col = blue)
  box(col = muted)

  b2_density <- weighted_density(frame$b2_mean, frame$b2_weight, bandwidths[["b2"]], axis)
  plot(axis, b2_density, type = "n", xlim = c(0, 1), ylim = c(0, max(b2_density, na.rm = TRUE) * 1.06),
       xlab = expression(beta[2]), ylab = "Densite ponderee", main = expression("Marginale " * beta[2]))
  grid(col = grid)
  polygon(c(axis, rev(axis)), c(rep(0, length(axis)), rev(b2_density)), col = adjustcolor(orange, 0.16), border = NA)
  lines(axis, b2_density, lwd = 2.4, col = orange)
  box(col = muted)

  type_label <- if (metadata$election_type[[1]] == "legislative") "Legislatives" else "Presidentielle"
  title <- paste0(scenario_id, " - ", type_label, " ", metadata$year[[1]], " (tour ", metadata$round[[1]], ")")
  subtitle <- paste0(method_label, " | n beta1=", finite_b1, " | n beta2=", finite_b2, " | n conjoint=", finite_both)
  mtext(title, outer = TRUE, side = 3, line = 2.25, cex = 1.35, font = 2, col = ink)
  mtext(subtitle, outer = TRUE, side = 3, line = 0.85, cex = 0.9, col = muted)
  mtext("Moyennes posterieures communales; marginales ponderees par l'effectif du groupe; axes fixes a [0,1].",
        outer = TRUE, side = 1, line = -0.15, cex = 0.78, col = muted)
}

catalog_rows <- list()
coverage_rows <- list()
generated <- character()
errors <- list()

for (method_spec in method_specs) {
  input_path <- file.path(input_dir, method_spec$input)
  if (!file.exists(input_path)) stop("missing input: ", input_path)
  data <- read_csv_portable(input_path)
  metadata <- do.call(rbind, lapply(sort(unique(data$election_id)), election_metadata))
  data <- merge(data, metadata, by = "election_id", all.x = TRUE, sort = FALSE)
  method_dir <- file.path(output_root, method_spec$folder)
  dir.create(method_dir, recursive = TRUE, showWarnings = FALSE)

  series_keys <- unique(data[, c("scenario_id", "election_type")])
  bandwidth_map <- list()
  for (index in seq_len(nrow(series_keys))) {
    scenario_id <- series_keys$scenario_id[[index]]
    election_type <- series_keys$election_type[[index]]
    selected <- data$scenario_id == scenario_id & data$election_type == election_type
    frame <- data[selected, ]
    h1 <- safe_bandwidth(frame$b1_mean)
    h2 <- safe_bandwidth(frame$b2_mean)
    key <- paste(scenario_id, election_type, sep = "__")
    bandwidth_map[[key]] <- list(b1 = h1, b2 = h2, joint = c(h1, h2))
  }

  pairs <- unique(data[, c("election_id", "scenario_id", "election_type", "year", "round")])
  pairs <- pairs[order(pairs$election_type, pairs$year, pairs$round, pairs$election_id, pairs$scenario_id), ]
  for (row_index in seq_len(nrow(pairs))) {
    pair <- pairs[row_index, ]
    selected <- data$election_id == pair$election_id[[1]] & data$scenario_id == pair$scenario_id[[1]]
    frame <- data[selected, ]
    finite_b1 <- sum(is.finite(frame$b1_mean))
    finite_b2 <- sum(is.finite(frame$b2_mean))
    finite_both <- sum(is.finite(frame$b1_mean) & is.finite(frame$b2_mean))
    scenario_id <- as.character(pair$scenario_id[[1]])
    election_id <- as.character(pair$election_id[[1]])
    series_key <- paste(scenario_id, pair$election_type[[1]], sep = "__")
    bandwidths <- bandwidth_map[[series_key]]
    pair_dir <- file.path(method_dir, scenario_id, election_id)
    dir.create(pair_dir, recursive = TRUE, showWarnings = FALSE)
    stem <- paste0("densite_jointe_marginales_", method_spec$id, "_", election_id, "_", scenario_id)
    png_path <- file.path(pair_dir, paste0(stem, ".png"))
    svg_path <- file.path(pair_dir, paste0(stem, ".svg"))
    status <- "complete"
    warning <- ""
    tryCatch({
      draw_pair(png_path, "png", frame, pair, method_spec$label, scenario_id, bandwidths, bandwidths$joint)
      draw_pair(svg_path, "svg", frame, pair, method_spec$label, scenario_id, bandwidths, bandwidths$joint)
      generated <- c(generated, png_path, svg_path)
    }, error = function(condition) {
      status <<- "error"
      warning <<- conditionMessage(condition)
      errors[[paste(method_spec$id, election_id, scenario_id, sep = "__")]] <<- warning
    })
    if (finite_b1 < nrow(frame) || finite_b2 < nrow(frame)) {
      warning <- trimws(paste(warning, "Valeurs non finies exclues des densites."))
    }
    catalog_rows[[length(catalog_rows) + 1L]] <- data.frame(
      method = method_spec$id,
      election_id = election_id,
      election_type = as.character(pair$election_type[[1]]),
      year = as.integer(pair$year[[1]]),
      round = as.integer(pair$round[[1]]),
      scenario_id = scenario_id,
      status = status,
      png = if (status == "complete") substring(png_path, nchar(output_root) + 2L) else "",
      svg = if (status == "complete") substring(svg_path, nchar(output_root) + 2L) else "",
      finite_b1 = finite_b1,
      finite_b2 = finite_b2,
      finite_both = finite_both,
      total_rows = nrow(frame),
      bandwidth_b1 = bandwidths$b1,
      bandwidth_b2 = bandwidths$b2,
      warning = warning,
      stringsAsFactors = FALSE
    )
    coverage_rows[[length(coverage_rows) + 1L]] <- catalog_rows[[length(catalog_rows)]]
    if (row_index %% 20L == 0L) cat(method_spec$id, ": ", row_index, "/", nrow(pairs), " pairs\n", sep = "")
  }
}

catalog <- do.call(rbind, catalog_rows)
write.csv(catalog, file.path(output_root, "03_CATALOGUE_DENSITES.csv"), row.names = FALSE, fileEncoding = "UTF-8")
method_pair_counts <- table(catalog$method)
method_pair_counts <- setNames(as.list(as.integer(method_pair_counts)), names(method_pair_counts))
manifest <- list(
  schema_version = "all_pair_density_figures_v1",
  status = if (all(catalog$status == "complete") && nrow(catalog) == expected_figures) "complete" else "partial",
  generated_at_utc = format(Sys.time(), tz = "UTC", usetz = TRUE),
  pair_figures = nrow(catalog),
  expected_pair_figures = expected_figures,
  replication_scope = input_manifest$replication_scope,
  png_files = sum(catalog$status == "complete"),
  svg_files = sum(catalog$status == "complete"),
  methods = unique(catalog$method),
  election_scenario_pairs_per_method = method_pair_counts,
  finite_beta_policy = "non-finite commune means are excluded and their counts are printed in every figure and catalogued",
  joint_density = "equal-weight commune KDE with bandwidth shared within method x scenario x election type",
  marginal_density = "group-population-weighted KDE with bandwidth shared within method x scenario x election type",
  axes = "beta1 and beta2 fixed to [0,1]",
  errors = errors
)
write_json(manifest, file.path(output_root, "04_DENSITY_MANIFEST.json"), auto_unbox = TRUE, pretty = TRUE, digits = NA)
cat(toJSON(manifest, auto_unbox = TRUE, pretty = TRUE, digits = NA), "\n")
