param(
    [Parameter(Mandatory = $true)][string]$PythonPath
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$statusRoot = Join-Path $projectRoot "outputs\longitudinal_2000_v1\production"
$statusPath = Join-Path $statusRoot "pymc_parallel_remaining_stream_status.json"

function Write-StreamStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [string]$CurrentConfig = "",
        [string]$Detail = ""
    )
    [ordered]@{
        status = $Status
        current_config = $CurrentConfig
        detail = $Detail
        execution_policy = "one_sequential_run_per_scope_parallel_to_h23_stream"
        cores_per_fit = 1
        updated_at = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
}

$configs = @(
    "config\releases\v1.2_pymc_h6_h7.json",
    "config\releases\v1.3_pymc_h0b_h0c.json",
    "config\releases\v1.4_pymc_h4_h5.json"
)

Write-StreamStatus -Status "starting"
foreach ($config in $configs) {
    Write-StreamStatus -Status "running" -CurrentConfig $config
    & $PythonPath -m code_longitudinal.v11_pipeline krt `
        --release-config $config `
        --cores 1
    $stageExit = $LASTEXITCODE
    if ($stageExit -ne 0) {
        Write-StreamStatus -Status "stage_blocked" -CurrentConfig $config -Detail ("exit code: " + $stageExit)
        exit $stageExit
    }
    Write-StreamStatus -Status "stage_finished" -CurrentConfig $config
}

Write-StreamStatus -Status "all_initial_krt_stages_finished" -Detail "H6/H7, H0B/H0C and H4/H5 initial PyMC streams completed"
exit 0
