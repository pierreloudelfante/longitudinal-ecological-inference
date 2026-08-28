#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(coda)
  library(jsonlite)
  library(nimble)
  library(posterior)
})

code <- nimbleCode({
  a ~ dnorm(0, 1)
})
model <- nimbleModel(
  code,
  inits = list(a = 0),
  check = TRUE,
  calculate = TRUE
)
compiled <- compileNimble(model, showCompilerOutput = FALSE)
stopifnot(is.finite(compiled$calculate()))
cat("r_nimble_preflight=PASS\n")
