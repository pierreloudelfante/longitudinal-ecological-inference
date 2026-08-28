param(
    [string]$PythonExe = "",
    [switch]$PlanOnly,
    [switch]$SkipTargetedReruns
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
Set-Location $projectRoot

if (-not $PythonExe) {
    $PythonExe = Join-Path $projectRoot "..\pour_moi_avec_data\.venv-ei\Scripts\python.exe"
}
if (-not (Test-Path $PythonExe)) {
    throw "Environnement Python introuvable: $PythonExe"
}
$PythonExe = (Resolve-Path $PythonExe).Path

$stateDir = Join-Path $projectRoot "outputs\longitudinal_2000_v1\production\numpyro_continuation"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$targetPlanPath = Join-Path $stateDir "initial_missing_pairs_plan.csv"
$initialProgressPath = Join-Path $stateDir "initial_execution_progress.csv"
$rerunProgressPath = Join-Path $stateDir "targeted_rerun_progress.csv"
$statusPath = Join-Path $stateDir "status.json"
$modelIndexPath = Join-Path $projectRoot "work\handoff_20260826T124313Z\MODEL_READY_INDEX_240.csv"

$scopeByScenario = @{
    H2 = "config\releases\v1.1.json"
    H3 = "config\releases\v1.1.json"
    H4 = "config\releases\v1.4_numpyro_h4_h5_continuation.json"
    H5 = "config\releases\v1.4_numpyro_h4_h5_continuation.json"
}

function Get-KrtSuccessIndex {
    $index = @{}
    Get-ChildItem (Join-Path $projectRoot "outputs\runs") -Directory | ForEach-Object {
        $manifestPath = Join-Path $_.FullName "manifest.json"
        if (-not (Test-Path $manifestPath)) { return }
        try { $manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json } catch { return }
        $parameters = $manifest.parameters
        if ($manifest.status -ne "success" -or $null -eq $parameters) { return }
        if ($parameters.model_key -ne "krt_beta_binomial") { return }
        $required = @(
            (Join-Path $_.FullName "commune_latent_summaries.parquet"),
            (Join-Path $_.FullName "aggregate_comparison_v2.csv"),
            (Join-Path $_.FullName "model_diagnostics.csv"),
            (Join-Path $_.FullName "mcmc_diagnostics_v2.json")
        )
        if (($required | Where-Object { -not (Test-Path $_) }).Count -gt 0) { return }
        $key = "$($parameters.election_id)|$($parameters.scenario_id)"
        $candidate = [pscustomobject]@{
            run_id = [string]$manifest.run_id
            sampler_backend = if ($parameters.sampler_backend) { [string]$parameters.sampler_backend } else { "numpyro_legacy_default" }
            release_id = [string]$parameters.release_id
            finished_at_utc = [string]$manifest.finished_at_utc
        }
        if (-not $index.ContainsKey($key) -or $candidate.finished_at_utc -gt $index[$key].finished_at_utc) {
            $index[$key] = $candidate
        }
    }
    return $index
}

function Write-Status([string]$Stage, [int]$Completed, [int]$Expected, [string]$CurrentPair, [string]$Message) {
    $successIndex = Get-KrtSuccessIndex
    [ordered]@{
        status = if ($Stage -eq "completed") { "completed" } else { "running" }
        engine = "numpyro"
        stage = $Stage
        completed_in_stage = $Completed
        expected_in_stage = $Expected
        current_pair = $CurrentPair
        successful_unique_pairs = $successIndex.Count
        expected_unique_pairs = 240
        message = $Message
        python_executable = $PythonExe
        updated_at = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 $statusPath
}

& $PythonExe -c "import jax, numpyro; assert jax.devices(); print('NumPyro/JAX OK:', numpyro.__version__, jax.devices())"
if ($LASTEXITCODE -ne 0) { throw "NumPyro/JAX indisponible." }
if (-not (Test-Path $modelIndexPath)) { throw "Index des 240 matrices introuvable: $modelIndexPath" }

$modelIndex = Import-Csv $modelIndexPath |
    Sort-Object scenario_id, election_id |
    Group-Object election_id, scenario_id |
    ForEach-Object { $_.Group | Select-Object -First 1 }
if ($modelIndex.Count -ne 240) { throw "Le plan doit contenir 240 couples uniques; trouve: $($modelIndex.Count)." }

if (Test-Path $targetPlanPath) {
    $targets = @(Import-Csv $targetPlanPath)
} else {
    $baseline = Get-KrtSuccessIndex
    $targets = @(
        foreach ($row in $modelIndex) {
            $key = "$($row.election_id)|$($row.scenario_id)"
            if (-not $baseline.ContainsKey($key)) {
                $scope = $scopeByScenario[[string]$row.scenario_id]
                if (-not $scope) { throw "Aucun scope NumPyro pour le couple absent $key." }
                [pscustomobject]@{
                    election_id = [string]$row.election_id
                    scenario_id = [string]$row.scenario_id
                    release_config = $scope
                    baseline_status = "missing"
                }
            }
        }
    )
    $targets | Export-Csv -NoTypeInformation -Encoding utf8 $targetPlanPath
}

$activeTargets = @($targets | Where-Object { $_.baseline_status -notlike "deferred*" })
$deferredTargets = @($targets | Where-Object { $_.baseline_status -like "deferred*" })

$baselineSuccess = Get-KrtSuccessIndex
Write-Host "Plan fige: $($activeTargets.Count) couples actifs, $($deferredTargets.Count) differes; $($baselineSuccess.Count)/240 succes deja conserves."
Write-Status "initial" 0 $activeTargets.Count "" "Plan NumPyro pret."
if ($PlanOnly) { return }

$initialDone = 0
foreach ($target in $activeTargets) {
    $key = "$($target.election_id)|$($target.scenario_id)"
    $success = Get-KrtSuccessIndex
    if ($success.ContainsKey($key)) {
        $initialDone += 1
        Write-Host "[$initialDone/$($activeTargets.Count)] deja reussi: $key ($($success[$key].sampler_backend))"
        Write-Status "initial" $initialDone $activeTargets.Count $key "Succes existant conserve."
        continue
    }

    Write-Host "[$($initialDone + 1)/$($activeTargets.Count)] NumPyro initial: $key"
    Write-Status "initial" $initialDone $activeTargets.Count $key "Ajustement initial NumPyro en cours."
    $started = Get-Date
    & $PythonExe -m code_longitudinal.v11_pipeline krt `
        --release-config $target.release_config `
        --election-id $target.election_id `
        --scenario-id $target.scenario_id `
        --cores 1
    $exitCode = $LASTEXITCODE
    $successAfter = Get-KrtSuccessIndex
    $resultStatus = if ($successAfter.ContainsKey($key)) { "success" } else { "failed" }
    [pscustomobject]@{
        election_id = $target.election_id
        scenario_id = $target.scenario_id
        release_config = $target.release_config
        status = $resultStatus
        exit_code = $exitCode
        elapsed_seconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
        run_id = if ($successAfter.ContainsKey($key)) { $successAfter[$key].run_id } else { "" }
        finished_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    } | Export-Csv -NoTypeInformation -Encoding utf8 -Append $initialProgressPath
    if ($resultStatus -ne "success") {
        Write-Status "failed" $initialDone $activeTargets.Count $key "Arret apres echec du couple courant."
        throw "Echec du couple $key; la reprise est arretee avant le couple suivant."
    }
    $initialDone += 1
    Write-Status "initial" $initialDone $activeTargets.Count $key "Ajustement initial termine."
}

if (-not $SkipTargetedReruns) {
    $rerunDone = 0
    foreach ($target in $activeTargets) {
        $scopePayload = Get-Content -Raw $target.release_config | ConvertFrom-Json
        $resultPath = Join-Path $projectRoot "outputs\longitudinal_2000_v1\production\$($scopePayload.release_id)\targeted_rerun__$($target.election_id)__$($target.scenario_id).json"
        if (Test-Path $resultPath) { $rerunDone += 1; continue }
        $key = "$($target.election_id)|$($target.scenario_id)"
        Write-Host "[$($rerunDone + 1)/$($activeTargets.Count)] diagnostic et relance ciblee si necessaire: $key"
        Write-Status "targeted_rerun" $rerunDone $activeTargets.Count $key "Diagnostic de relance ciblee en cours."
        $started = Get-Date
        & $PythonExe -m code_longitudinal.targeted_rerun_remaining `
            --release-config $target.release_config `
            --election-id $target.election_id `
            --scenario-id $target.scenario_id
        $exitCode = $LASTEXITCODE
        $resultStatus = if ($exitCode -eq 0 -and (Test-Path $resultPath)) { "completed" } else { "unresolved" }
        [pscustomobject]@{
            election_id = $target.election_id
            scenario_id = $target.scenario_id
            status = $resultStatus
            exit_code = $exitCode
            elapsed_seconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
            result_path = $resultPath
            finished_at_utc = (Get-Date).ToUniversalTime().ToString("o")
        } | Export-Csv -NoTypeInformation -Encoding utf8 -Append $rerunProgressPath
        if ($resultStatus -ne "completed") { throw "Relance ciblee non resolue pour $key." }
        $rerunDone += 1
        Write-Status "targeted_rerun" $rerunDone $activeTargets.Count $key "Regle de relance terminee."
    }
}

Write-Status "consolidation" 0 2 "" "Consolidation des candidats KRT."
& $PythonExe -m code_longitudinal.consolidate_current_krt_all_2x2
if ($LASTEXITCODE -ne 0) { throw "Echec de la consolidation KRT." }
Write-Status "consolidation" 1 2 "" "Reconstruction de la couverture courante."
& $PythonExe -m code_longitudinal.build_current_estimation_coverage
if ($LASTEXITCODE -ne 0) { throw "Echec de la couverture courante." }

$finalSuccess = Get-KrtSuccessIndex
Write-Status "completed" 2 2 "" "Production NumPyro, relances ciblees et consolidation terminees."
Write-Host "Production Python terminee: $($finalSuccess.Count)/240 couples avec succes durable."
