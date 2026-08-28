param(
    [Parameter(Mandatory = $true)][string]$PythonPath
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$config = "config\releases\v1.3_pymc_h0b_h0c.json"
$statusPath = Join-Path $projectRoot "outputs\longitudinal_2000_v1\production\pymc_h0bc_pilot_stream_status.json"
$pairs = @(
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
        cores_per_fit = 1
        detail = $Detail
        updated_at = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
}

function Invoke-KrtPair {
    param(
        [Parameter(Mandatory = $true)][string]$ElectionId,
        [Parameter(Mandatory = $true)][string]$ScenarioId
    )
    $resultText = (& $PythonPath -m code_longitudinal.v11_pipeline krt `
        --release-config $config `
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

$completed = 0
Write-PilotStatus -Status "starting"
foreach ($pair in $pairs) {
    $election = $pair[0]
    $scenario = $pair[1]
    Write-PilotStatus -Status "running" -ElectionId $election -ScenarioId $scenario -Completed $completed
    try {
        Invoke-KrtPair -ElectionId $election -ScenarioId $scenario
    } catch {
        Write-PilotStatus -Status "blocked" -ElectionId $election -ScenarioId $scenario -Completed $completed -Detail $_.Exception.Message
        exit 2
    }
    $completed += 1
    Write-PilotStatus -Status "pair_finished" -ElectionId $election -ScenarioId $scenario -Completed $completed
}

Write-PilotStatus -Status "completed" -Completed $completed -Detail "Six H0B/H0C PyMC pilot commands completed"
exit 0
