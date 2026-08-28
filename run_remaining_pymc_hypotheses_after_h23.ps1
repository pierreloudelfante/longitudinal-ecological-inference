param(
    [Parameter(Mandatory = $true)][int]$H23ChainPid,
    [Parameter(Mandatory = $true)][string]$PythonPath
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$h23Production = Join-Path $projectRoot "outputs\longitudinal_2000_v1\production\longitudinal_2000_v1.1_H0A_H1_H2_H3_pymc_fallback"
$h23Status = Join-Path $h23Production "pymc_fallback_chain_status.json"
$statusRoot = Join-Path $projectRoot "outputs\longitudinal_2000_v1\production"
$statusPath = Join-Path $statusRoot "pymc_remaining_hypotheses_chain_status.json"

function Write-RemainingStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [string]$CurrentConfig = "",
        [string]$Detail = ""
    )
    [ordered]@{
        status = $Status
        current_config = $CurrentConfig
        detail = $Detail
        h23_chain_pid = $H23ChainPid
        updated_at = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
}

Write-RemainingStatus -Status "waiting_for_h23_chain"
Wait-Process -Id $H23ChainPid

if (-not (Test-Path -LiteralPath $h23Status)) {
    Write-RemainingStatus -Status "h23_chain_failed" -Detail "H2/H3 chain status is missing"
    exit 2
}
$h23 = Get-Content -LiteralPath $h23Status -Raw | ConvertFrom-Json
if ([string]$h23.status -ne "supervisor_finished") {
    Write-RemainingStatus -Status "h23_chain_failed" -Detail ("H2/H3 terminal status: " + [string]$h23.status)
    exit 2
}

$configs = @(
    "config\releases\v1.2_pymc_h6_h7.json",
    "config\releases\v1.3_pymc_h0b_h0c.json",
    "config\releases\v1.4_pymc_h4_h5.json"
)
foreach ($config in $configs) {
    Write-RemainingStatus -Status "running" -CurrentConfig $config
    & $PythonPath -m code_longitudinal.v11_pipeline krt `
        --release-config $config `
        --cores 2
    $stageExit = $LASTEXITCODE
    if ($stageExit -ne 0) {
        Write-RemainingStatus -Status "stage_blocked" -CurrentConfig $config -Detail ("exit code: " + $stageExit)
        exit $stageExit
    }
    Write-RemainingStatus -Status "stage_finished" -CurrentConfig $config
}

Write-RemainingStatus -Status "all_initial_krt_stages_finished" -Detail "H6/H7, H0B/H0C and H4/H5 initial PyMC production commands completed"
exit 0
