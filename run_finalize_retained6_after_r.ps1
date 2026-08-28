param(
    [Parameter(Mandatory = $true)][int]$RWatcherPid,
    [Parameter(Mandatory = $true)][string]$PythonPath
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$productionRoot = Join-Path $projectRoot "outputs\longitudinal_2000_v1\production"
$releaseId = "longitudinal_2000_v1.5_H0A_H1_H0B_H0C_H2_H3"
$releaseRoot = Join-Path $productionRoot $releaseId
$selection = Join-Path $releaseRoot "canonical_run_selection.csv"
$statusPath = Join-Path $productionRoot "finalize_retained6_after_r_status.json"
$upstreamStatus = Join-Path $productionRoot "final_scope_python_then_r_ei_status.json"
$config = "config\releases\v1.5_retained6.json"

function Write-FinalizeStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [string]$Stage = "",
        [string]$Detail = ""
    )
    [ordered]@{
        schema_version = "finalize_retained6_after_r_status_v1"
        status = $Status
        stage = $Stage
        detail = $Detail
        release_id = $releaseId
        updated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
}

function Invoke-PythonStage {
    param(
        [Parameter(Mandatory = $true)][string]$Stage,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    Write-FinalizeStatus -Status "running" -Stage $Stage
    & $PythonPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        Write-FinalizeStatus -Status "failed" -Stage $Stage -Detail ("exit code: " + $LASTEXITCODE)
        exit $LASTEXITCODE
    }
}

New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
Write-FinalizeStatus -Status "waiting_for_r" -Detail ("watcher pid: " + $RWatcherPid)
Wait-Process -Id $RWatcherPid -ErrorAction SilentlyContinue

if (-not (Test-Path -LiteralPath $upstreamStatus)) {
    Write-FinalizeStatus -Status "blocked" -Stage "upstream_check" -Detail "missing upstream status"
    exit 2
}
$upstream = Get-Content -Raw -LiteralPath $upstreamStatus | ConvertFrom-Json
if ($upstream.status -ne "r_ei_complete") {
    Write-FinalizeStatus -Status "blocked" -Stage "upstream_check" -Detail ("upstream status: " + $upstream.status)
    exit 2
}

Invoke-PythonStage -Stage "canonical_selection" -Arguments @(
    "-m", "code_longitudinal.build_retained6_selection",
    "--release-config", $config,
    "--output", $selection
)
Invoke-PythonStage -Stage "python_finalization" -Arguments @(
    "-m", "code_longitudinal.scoped_finalizer",
    "--release-config", $config,
    "--canonical-selection", $selection,
    "--allow-diagnostic-failures"
)
Invoke-PythonStage -Stage "r_consolidation" -Arguments @(
    "-m", "code_longitudinal.consolidate_r_ei_all_2x2",
    "--scenarios", "H0A", "H1", "H0B", "H0C", "H2", "H3"
)
Invoke-PythonStage -Stage "python_r_comparison" -Arguments @(
    "-m", "code_longitudinal.compare_python_r_ei_all_2x2"
)
Invoke-PythonStage -Stage "materialization" -Arguments @(
    "-m", "code_longitudinal.materialize_retained6_release",
    "--release-config", $config
)
Invoke-PythonStage -Stage "python_r_figures" -Arguments @(
    "-m", "code_longitudinal.plot_python_r_retained6"
)
Invoke-PythonStage -Stage "diagnostics_2022" -Arguments @(
    "-m", "code_longitudinal.plot_2022_retained6_diagnostics"
)
Invoke-PythonStage -Stage "documentation" -Arguments @(
    "-m", "code_longitudinal.build_retained6_documentation"
)

Write-FinalizeStatus -Status "complete_pending_pdf_and_packaging" -Stage "documentation" -Detail "PDF visual QA and ZIP packaging remain interactive final gates."
exit 0
