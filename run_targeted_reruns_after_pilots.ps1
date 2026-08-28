param(
    [Parameter(Mandatory = $true)][int]$PilotStreamPid,
    [Parameter(Mandatory = $true)][string]$PythonPath
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$statusPath = Join-Path $projectRoot "outputs\longitudinal_2000_v1\production\pymc_targeted_reruns_after_pilots_status.json"
$rowsPath = Join-Path $projectRoot "outputs\longitudinal_2000_v1\production\pymc_targeted_reruns_after_pilots.csv"
$pairs = @(
    @("config\releases\v1.3_pymc_h0b_h0c.json", "leg_1962_r1", "H0B"),
    @("config\releases\v1.3_pymc_h0b_h0c.json", "leg_1962_r1", "H0C"),
    @("config\releases\v1.3_pymc_h0b_h0c.json", "leg_1986_r1", "H0B"),
    @("config\releases\v1.3_pymc_h0b_h0c.json", "leg_1986_r1", "H0C"),
    @("config\releases\v1.3_pymc_h0b_h0c.json", "leg_2022_r1", "H0B"),
    @("config\releases\v1.3_pymc_h0b_h0c.json", "leg_2022_r1", "H0C"),
    @("config\releases\v1.4_pymc_h4_h5.json", "leg_1962_r1", "H4"),
    @("config\releases\v1.4_pymc_h4_h5.json", "leg_1962_r1", "H5"),
    @("config\releases\v1.4_pymc_h4_h5.json", "leg_1986_r1", "H4"),
    @("config\releases\v1.4_pymc_h4_h5.json", "leg_1986_r1", "H5"),
    @("config\releases\v1.4_pymc_h4_h5.json", "leg_2022_r1", "H4"),
    @("config\releases\v1.4_pymc_h4_h5.json", "leg_2022_r1", "H5")
)

function Write-QueueStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [int]$Checked = 0,
        [int]$Selected = 0,
        [int]$NotRequired = 0,
        [int]$Failed = 0,
        [string]$ElectionId = "",
        [string]$ScenarioId = ""
    )
    [ordered]@{
        status = $Status
        predecessor_pid = $PilotStreamPid
        checked_pairs = $Checked
        expected_pairs = $pairs.Count
        selected_reruns = $Selected
        reruns_not_required = $NotRequired
        unresolved_or_unavailable = $Failed
        election_id = $ElectionId
        scenario_id = $ScenarioId
        updated_at = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
}

Write-QueueStatus -Status "waiting_for_h0bc_h45_pilots"
Wait-Process -Id $PilotStreamPid

$results = New-Object System.Collections.Generic.List[object]
$checked = 0
$selected = 0
$notRequired = 0
$failed = 0
foreach ($pair in $pairs) {
    $config = $pair[0]
    $election = $pair[1]
    $scenario = $pair[2]
    Write-QueueStatus -Status "checking_or_rerunning" -Checked $checked -Selected $selected -NotRequired $notRequired -Failed $failed -ElectionId $election -ScenarioId $scenario
    $resultText = (& $PythonPath -m code_longitudinal.targeted_rerun_remaining `
        --release-config $config `
        --election-id $election `
        --scenario-id $scenario 2>&1 | Out-String)
    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 0) {
        try {
            $result = $resultText | ConvertFrom-Json
            if ([string]$result.status -eq "selected") {
                $selected += 1
            } else {
                $notRequired += 1
            }
            $results.Add([pscustomobject]@{
                release_config = $config
                election_id = $election
                scenario_id = $scenario
                status = [string]$result.status
                initial_run_id = [string]$result.initial_run_id
                selected_run_id = [string]$result.selected_run_id
                selection_reason = [string]$result.selection_reason
                error = ""
            })
        } catch {
            $failed += 1
            $results.Add([pscustomobject]@{
                release_config = $config
                election_id = $election
                scenario_id = $scenario
                status = "invalid_result"
                initial_run_id = ""
                selected_run_id = ""
                selection_reason = ""
                error = $_.Exception.Message
            })
        }
    } else {
        $failed += 1
        $results.Add([pscustomobject]@{
            release_config = $config
            election_id = $election
            scenario_id = $scenario
            status = "unresolved_or_unavailable"
            initial_run_id = ""
            selected_run_id = ""
            selection_reason = ""
            error = $resultText.Trim()
        })
    }
    $checked += 1
    $results | Export-Csv -LiteralPath $rowsPath -NoTypeInformation -Encoding utf8
}

$terminal = if ($failed -eq 0) { "completed" } else { "completed_with_unresolved_pairs" }
Write-QueueStatus -Status $terminal -Checked $checked -Selected $selected -NotRequired $notRequired -Failed $failed
exit 0
