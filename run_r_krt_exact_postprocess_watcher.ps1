param(
    [Parameter(Mandatory = $true)][int]$ExactSupervisorPid,
    [Parameter(Mandatory = $true)][string]$PythonPath
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$statusPath = Join-Path $projectRoot "outputs\longitudinal_2000_v1\r_replication\krt_exact_postprocess_watcher_status.json"
$statusRoot = Split-Path -Parent $statusPath
New-Item -ItemType Directory -Force -Path $statusRoot | Out-Null

function Write-Status {
    param([Parameter(Mandatory = $true)][string]$Status, [string]$Detail = "")
    [ordered]@{
        status = $Status
        exact_supervisor_pid = $ExactSupervisorPid
        detail = $Detail
        updated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
}

Write-Status -Status "waiting_for_r_krt_exact_supervisor"
if (Get-Process -Id $ExactSupervisorPid -ErrorAction SilentlyContinue) {
    Wait-Process -Id $ExactSupervisorPid
}

Write-Status -Status "consolidating_r_krt_exact"
& $PythonPath -m code_longitudinal.consolidate_r_krt_exact_all_2x2
if ($LASTEXITCODE -ne 0) {
    Write-Status -Status "consolidation_failed" -Detail ("exit code: " + [string]$LASTEXITCODE)
    exit $LASTEXITCODE
}

Write-Status -Status "comparing_python_r_krt_exact"
& $PythonPath -m code_longitudinal.compare_python_r_krt_exact_all_2x2
if ($LASTEXITCODE -ne 0) {
    Write-Status -Status "comparison_failed" -Detail ("exit code: " + [string]$LASTEXITCODE)
    exit $LASTEXITCODE
}

Write-Status -Status "completed"
exit 0
