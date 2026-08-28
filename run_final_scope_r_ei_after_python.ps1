param(
    [Parameter(Mandatory = $true)][int]$H0BCPipelinePid,
    [Parameter(Mandatory = $true)][string]$PythonPath
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$productionRoot = Join-Path $projectRoot "outputs\longitudinal_2000_v1\production"
$statusPath = Join-Path $productionRoot "final_scope_python_then_r_ei_status.json"
$selectionPath = Join-Path $productionRoot "all_2x2_candidate\krt_240_candidate_selection.csv"
$requiredScenarios = @("H0A", "H1", "H0B", "H0C", "H2", "H3")

function Write-FinalScopeStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [string]$Detail = "",
        [hashtable]$Counts = @{}
    )
    [ordered]@{
        schema_version = "final_scope_python_then_r_ei_status_v1"
        status = $Status
        detail = $Detail
        python_scenarios = $requiredScenarios
        r_engine = "R_ei_1.3-3_depending_on_eiPack_0.2-2"
        nimble_used = $false
        expected_pairs = 156
        counts = $Counts
        updated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statusPath -Encoding utf8
}

Write-FinalScopeStatus -Status "waiting_for_python_h0b_h0c" -Detail "Waiting for the H0B/H0C initial stream; no other Python scenario is authorized."
Wait-Process -Id $H0BCPipelinePid -ErrorAction SilentlyContinue

Write-FinalScopeStatus -Status "running_python_h2_h3_initial_only" -Detail "Running only missing initial H2/H3 fits; no strengthened rerun stream is enabled."
& $PythonPath -m code_longitudinal.v11_pipeline krt `
    --release-config "config\releases\v1.1_pymc_fallback.json" `
    --cores 1
$h23Exit = $LASTEXITCODE
if ($h23Exit -ne 0) {
    Write-FinalScopeStatus -Status "python_h2_h3_failed" -Detail ("H2/H3 initial runner exit code: " + $h23Exit)
    exit $h23Exit
}

$deadline = (Get-Date).AddMinutes(5)
do {
    # Rebuild the explicit selection from the manifests just written by the
    # Python queue.  The CSV is a materialized view, not a live database, so
    # reading it without refreshing can falsely report an incomplete scope.
    & $PythonPath -m code_longitudinal.build_current_estimation_coverage | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-FinalScopeStatus -Status "python_consolidation_failed" -Detail ("coverage refresh exit code: " + $LASTEXITCODE)
        exit $LASTEXITCODE
    }
    if (-not (Test-Path -LiteralPath $selectionPath)) {
        Start-Sleep -Seconds 15
        continue
    }
    $selection = Import-Csv -LiteralPath $selectionPath
    $counts = @{}
    foreach ($scenario in $requiredScenarios) {
        $counts[$scenario] = @($selection | Where-Object { $_.scenario_id -eq $scenario }).Count
    }
    $complete = ($requiredScenarios | Where-Object { $counts[$_] -ne 26 }).Count -eq 0
    if (-not $complete) {
        Write-FinalScopeStatus -Status "waiting_for_python_consolidation" -Detail "Waiting for 26 attempted pairs in every retained scenario." -Counts $counts
        Start-Sleep -Seconds 15
    }
} until ($complete -or (Get-Date) -ge $deadline)

if (-not $complete) {
    Write-FinalScopeStatus -Status "blocked_python_scope_incomplete" -Detail "R ei was not started because the retained Python scope is incomplete." -Counts $counts
    exit 2
}

Write-FinalScopeStatus -Status "running_r_ei" -Detail "Running the six retained scenarios sequentially; NIMBLE is not used." -Counts $counts
& $PythonPath -m code_longitudinal.run_r_ei_all_2x2 --scenarios H0A H1 H0B H0C H2 H3
$rExit = $LASTEXITCODE
if ($rExit -ne 0) {
    Write-FinalScopeStatus -Status "r_ei_failed" -Detail ("R ei runner exit code: " + $rExit) -Counts $counts
    exit $rExit
}

Write-FinalScopeStatus -Status "r_ei_complete" -Detail "All 156 retained R ei pairs completed or were safely reused." -Counts $counts
exit 0
