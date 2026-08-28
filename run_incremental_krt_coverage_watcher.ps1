param(
    [Parameter(Mandatory = $true)][int]$FinalPipelineWatcherPid,
    [Parameter(Mandatory = $true)][string]$PythonPath
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$runsRoot = Join-Path $projectRoot "outputs\runs"
$statusPath = Join-Path $projectRoot "outputs\longitudinal_2000_v1\production\incremental_coverage_watcher_status.json"
$expectedPanelSha256 = "bde70c71660fce29610d7931461d8db6181dba874514a1866b63cf16a81cec4a"

function Write-Status {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [int]$SuccessfulManifestCount = 0,
        [string]$Detail = ""
    )
    [ordered]@{
        status = $Status
        final_pipeline_watcher_pid = $FinalPipelineWatcherPid
        successful_manifest_count = $SuccessfulManifestCount
        detail = $Detail
        updated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
}

function Get-SuccessfulRunIds {
    $runIds = [System.Collections.Generic.List[string]]::new()
    foreach ($manifestPath in Get-ChildItem -LiteralPath $runsRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object { Join-Path $_.FullName "manifest.json" }) {
        if (-not (Test-Path -LiteralPath $manifestPath)) { continue }
        try {
            $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
            if (
                $manifest.status -eq "success" -and
                $manifest.stage -eq "2x2" -and
                $manifest.parameters.model_key -eq "krt_beta_binomial" -and
                [int]$manifest.parameters.sample_size -eq 2000 -and
                $manifest.parameters.panel_sha256 -eq $expectedPanelSha256
            ) {
                $runIds.Add([string]$manifest.run_id)
            }
        } catch {
            continue
        }
    }
    return @($runIds | Sort-Object)
}

function Refresh-Coverage {
    param([int]$SuccessfulManifestCount)
    Write-Status -Status "consolidating" -SuccessfulManifestCount $SuccessfulManifestCount
    & $PythonPath -m code_longitudinal.consolidate_current_krt_all_2x2
    if ($LASTEXITCODE -ne 0) {
        throw "consolidation failed with exit code $LASTEXITCODE"
    }
    & $PythonPath -m code_longitudinal.build_current_estimation_coverage
    if ($LASTEXITCODE -ne 0) {
        throw "coverage refresh failed with exit code $LASTEXITCODE"
    }
    Write-Status -Status "watching" -SuccessfulManifestCount $SuccessfulManifestCount
}

$lastFingerprint = ""
while (Get-Process -Id $FinalPipelineWatcherPid -ErrorAction SilentlyContinue) {
    $runIds = @(Get-SuccessfulRunIds)
    $fingerprint = $runIds -join "|"
    if ($fingerprint -ne $lastFingerprint) {
        try {
            Refresh-Coverage -SuccessfulManifestCount $runIds.Count
            $lastFingerprint = $fingerprint
        } catch {
            Write-Status -Status "refresh_failed_will_retry" -SuccessfulManifestCount $runIds.Count -Detail $_.Exception.Message
        }
    }
    Start-Sleep -Seconds 30
}

$runIds = @(Get-SuccessfulRunIds)
try {
    Refresh-Coverage -SuccessfulManifestCount $runIds.Count
    Write-Status -Status "completed" -SuccessfulManifestCount $runIds.Count
} catch {
    Write-Status -Status "final_refresh_failed" -SuccessfulManifestCount $runIds.Count -Detail $_.Exception.Message
    exit 1
}
exit 0
