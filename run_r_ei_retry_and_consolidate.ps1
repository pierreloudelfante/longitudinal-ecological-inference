param(
    [Parameter(Mandatory = $true)][int]$InitialSupervisorPid,
    [Parameter(Mandatory = $true)][string]$PythonPath
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$replicationRoot = Join-Path $projectRoot "outputs\longitudinal_2000_v1\r_replication"
$statusPath = Join-Path $replicationRoot "king_ei_retry_and_consolidate_status.json"

function Write-Status {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [string]$Detail = ""
    )
    [ordered]@{
        status = $Status
        initial_supervisor_pid = $InitialSupervisorPid
        detail = $Detail
        retry_policy = "one additional pass; existing successful input hashes are never recomputed"
        updated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
}

Write-Status -Status "waiting_for_initial_r_ei_pass"
Wait-Process -Id $InitialSupervisorPid

Write-Status -Status "retrying_only_missing_or_failed_pairs"
& $PythonPath -m code_longitudinal.run_r_ei_all_2x2
$retryExit = $LASTEXITCODE
if ($retryExit -ne 0) {
    Write-Status -Status "retry_process_failed" -Detail ("exit code: " + $retryExit)
}

Write-Status -Status "consolidating_available_results"
& $PythonPath -m code_longitudinal.consolidate_r_ei_all_2x2 --allow-partial
$consolidationExit = $LASTEXITCODE
if ($consolidationExit -ne 0) {
    Write-Status -Status "consolidation_failed" -Detail ("exit code: " + $consolidationExit)
    exit $consolidationExit
}

$consolidationManifest = Join-Path $replicationRoot "king_ei_all_2x2_consolidation_manifest.json"
$manifest = Get-Content -LiteralPath $consolidationManifest -Raw | ConvertFrom-Json
$comparisonDetail = ""
try {
    Write-Status -Status "comparing_available_python_and_r_results"
    & $PythonPath -m code_longitudinal.compare_python_r_ei_all_2x2
    if ($LASTEXITCODE -ne 0) {
        $comparisonDetail = "Python-R comparison exited with code " + [string]$LASTEXITCODE
    }
} catch {
    $comparisonDetail = "Python-R comparison unavailable: " + $_.Exception.Message
}
$terminal = if ([string]$manifest.status -eq "complete") { "completed" } else { "completed_partial" }
$detail = "valid pairs: " + [string]$manifest.valid_pairs + "/" + [string]$manifest.expected_pairs
if ($comparisonDetail) {
    $detail += "; " + $comparisonDetail
}
Write-Status -Status $terminal -Detail $detail
exit 0
