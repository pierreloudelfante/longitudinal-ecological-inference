param(
    [Parameter(Mandatory = $true)][string]$PipelinePidsCsv,
    [Parameter(Mandatory = $true)][string]$PythonPath
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$statusPath = Join-Path $projectRoot "outputs\longitudinal_2000_v1\production\all_2x2_candidate\watcher_status.json"
$statusRoot = Split-Path -Parent $statusPath
New-Item -ItemType Directory -Force -Path $statusRoot | Out-Null
$PipelinePids = @($PipelinePidsCsv.Split(',') | ForEach-Object { [int]$_.Trim() })

function Write-Status {
    param([Parameter(Mandatory = $true)][string]$Status, [string]$Detail = "")
    [ordered]@{
        status = $Status
        pipeline_pids = $PipelinePids
        detail = $Detail
        updated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
}

Write-Status -Status "waiting_for_python_initial_and_targeted_rerun_streams"
foreach ($pipelinePid in $PipelinePids) {
    if (Get-Process -Id $pipelinePid -ErrorAction SilentlyContinue) {
        Wait-Process -Id $pipelinePid
    }
}

Write-Status -Status "consolidating_python_all_2x2"
& $PythonPath -m code_longitudinal.consolidate_current_krt_all_2x2
if ($LASTEXITCODE -ne 0) {
    Write-Status -Status "python_consolidation_failed" -Detail ("exit code: " + [string]$LASTEXITCODE)
    exit $LASTEXITCODE
}

Write-Status -Status "refreshing_coverage"
& $PythonPath -m code_longitudinal.build_current_estimation_coverage
if ($LASTEXITCODE -ne 0) {
    Write-Status -Status "coverage_refresh_failed" -Detail ("exit code: " + [string]$LASTEXITCODE)
    exit $LASTEXITCODE
}

try {
    Write-Status -Status "refreshing_available_python_r_comparison"
    & $PythonPath -m code_longitudinal.compare_python_r_ei_all_2x2
} catch {
    Write-Status -Status "completed_python_comparison_pending" -Detail $_.Exception.Message
    exit 0
}

Write-Status -Status "completed"
exit 0
