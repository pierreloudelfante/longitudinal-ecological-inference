param(
    [Parameter(Mandatory = $true)][int]$ConsolidationPid,
    [Parameter(Mandatory = $true)][string]$PythonPath
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$statusPath = Join-Path $projectRoot "outputs\longitudinal_2000_v1\r_replication\king_python_r_comparison_watcher_status.json"

function Write-Status {
    param([Parameter(Mandatory = $true)][string]$Status, [string]$Detail = "")
    [ordered]@{
        status = $Status
        consolidation_pid = $ConsolidationPid
        detail = $Detail
        updated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
}

Write-Status -Status "waiting_for_r_retry_and_consolidation"
Wait-Process -Id $ConsolidationPid
Write-Status -Status "running_python_r_comparison"
& $PythonPath -m code_longitudinal.compare_python_r_ei_all_2x2
if ($LASTEXITCODE -ne 0) {
    Write-Status -Status "comparison_failed" -Detail ("exit code: " + [string]$LASTEXITCODE)
    exit $LASTEXITCODE
}
Write-Status -Status "completed"
exit 0
