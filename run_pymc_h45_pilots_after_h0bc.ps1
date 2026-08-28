param(
    [Parameter(Mandatory = $true)][int]$H0bcStreamPid,
    [Parameter(Mandatory = $true)][string]$PythonPath
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$h0bcStatusPath = Join-Path $projectRoot "outputs\longitudinal_2000_v1\production\pymc_h0bc_pilot_stream_status.json"
$statusPath = Join-Path $projectRoot "outputs\longitudinal_2000_v1\production\pymc_h45_pilot_stream_status.json"
$config = "config\releases\v1.4_pymc_h4_h5.json"
$pairs = @(
    @("leg_1962_r1", "H4"),
    @("leg_1962_r1", "H5"),
    @("leg_1986_r1", "H4"),
    @("leg_1986_r1", "H5"),
    @("leg_2022_r1", "H4"),
    @("leg_2022_r1", "H5")
)
$h0bcConfig = "config\releases\v1.3_pymc_h0b_h0c.json"
$h0bcPairs = @(
    @("leg_1962_r1", "H0B"),
    @("leg_1962_r1", "H0C"),
    @("leg_1986_r1", "H0B"),
    @("leg_1986_r1", "H0C"),
    @("leg_2022_r1", "H0B"),
    @("leg_2022_r1", "H0C")
)

function Write-PilotStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [string]$ElectionId = "",
        [string]$ScenarioId = "",
        [int]$Completed = 0,
        [string]$Detail = ""
    )
    [ordered]@{
        status = $Status
        election_id = $ElectionId
        scenario_id = $ScenarioId
        completed_pairs = $Completed
        expected_pairs = $pairs.Count
        predecessor_pid = $H0bcStreamPid
        cores_per_fit = 1
        detail = $Detail
        updated_at = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
}

function Invoke-KrtPair {
    param(
        [Parameter(Mandatory = $true)][string]$ReleaseConfig,
        [Parameter(Mandatory = $true)][string]$ElectionId,
        [Parameter(Mandatory = $true)][string]$ScenarioId
    )
    $resultText = (& $PythonPath -m code_longitudinal.v11_pipeline krt `
        --release-config $ReleaseConfig `
        --election-id $ElectionId `
        --scenario-id $ScenarioId `
        --cores 1 | Out-String)
    $commandExit = $LASTEXITCODE
    Write-Output $resultText
    if ($commandExit -ne 0) {
        throw "pipeline exit code: $commandExit"
    }
    $result = $resultText | ConvertFrom-Json
    if ([int]$result.failed -ne 0 -or [int]$result.success_or_resumed -ne 1) {
        throw ("KRT pair not successful: failed=" + [string]$result.failed + ", success_or_resumed=" + [string]$result.success_or_resumed)
    }
}

Write-PilotStatus -Status "waiting_for_h0bc_pilots"
Wait-Process -Id $H0bcStreamPid
if (-not (Test-Path -LiteralPath $h0bcStatusPath)) {
    Write-PilotStatus -Status "predecessor_failed" -Detail "H0B/H0C status file is missing"
    exit 2
}
$h0bc = Get-Content -LiteralPath $h0bcStatusPath -Raw | ConvertFrom-Json
if ([string]$h0bc.status -ne "completed" -or [int]$h0bc.completed_pairs -ne 6) {
    Write-PilotStatus -Status "predecessor_failed" -Detail ("H0B/H0C terminal status: " + [string]$h0bc.status)
    exit 2
}

# Re-check every predecessor pair through the resumable pipeline. Existing
# successes are skipped; a missing or failed pair is retried before H4/H5.
foreach ($pair in $h0bcPairs) {
    try {
        Invoke-KrtPair -ReleaseConfig $h0bcConfig -ElectionId $pair[0] -ScenarioId $pair[1]
    } catch {
        Write-PilotStatus -Status "predecessor_failed" -ElectionId $pair[0] -ScenarioId $pair[1] -Detail $_.Exception.Message
        exit 2
    }
}

$completed = 0
foreach ($pair in $pairs) {
    $election = $pair[0]
    $scenario = $pair[1]
    Write-PilotStatus -Status "running" -ElectionId $election -ScenarioId $scenario -Completed $completed
    try {
        Invoke-KrtPair -ReleaseConfig $config -ElectionId $election -ScenarioId $scenario
    } catch {
        Write-PilotStatus -Status "blocked" -ElectionId $election -ScenarioId $scenario -Completed $completed -Detail $_.Exception.Message
        exit 2
    }
    $completed += 1
    Write-PilotStatus -Status "pair_finished" -ElectionId $election -ScenarioId $scenario -Completed $completed
}

Write-PilotStatus -Status "completed" -Completed $completed -Detail "Six H4/H5 PyMC pilot commands completed"
exit 0
