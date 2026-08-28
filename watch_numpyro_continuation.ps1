param(
    [int]$IntervalSeconds = 60,
    [int]$SampleSeconds = 5,
    [double]$LowCpuThreshold = 0.05,
    [int]$LowCpuLimit = 3,
    [int]$WarningWallMinutes = 90,
    [int]$SuspendGapToleranceSeconds = 120
)

$ErrorActionPreference = "Stop"
$stateDir = Join-Path $PSScriptRoot "outputs\longitudinal_2000_v1\production\numpyro_continuation"
$statusPath = Join-Path $stateDir "status.json"
$healthPath = Join-Path $stateDir "health_monitor.json"
$healthTempPath = Join-Path $stateDir "health_monitor.tmp.json"
$lastCheck = $null
$lowCpuChecks = 0

while ($true) {
    $loopStarted = Get-Date
    $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
    $before = @{}
    Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
        $before[$_.Id] = $_.CPU
    }

    Start-Sleep -Seconds $SampleSeconds

    $now = Get-Date
    $workers = @(
        Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
            if ($before.ContainsKey($_.Id)) {
                [pscustomobject]@{
                    process = $_
                    cpu_delta = [double]($_.CPU - $before[$_.Id])
                }
            }
        } | Sort-Object cpu_delta -Descending
    )
    $worker = $workers | Select-Object -First 1
    $alive = $null -ne $worker
    $cores = if ($alive) { [math]::Round($worker.cpu_delta / $SampleSeconds, 2) } else { $null }
    $suspendGap = $null -ne $lastCheck -and (($now - $lastCheck).TotalSeconds -gt ($IntervalSeconds + $SuspendGapToleranceSeconds))

    if ($alive -and ($suspendGap -or $cores -ge $LowCpuThreshold)) {
        $lowCpuChecks = 0
    } elseif ($status.status -eq "running") {
        $lowCpuChecks += 1
    } else {
        $lowCpuChecks = 0
    }

    $wallMinutes = $null
    if ($status.updated_at) {
        try {
            $wallMinutes = [math]::Round(($now.ToUniversalTime() - ([datetime]$status.updated_at).ToUniversalTime()).TotalMinutes, 1)
        } catch {
            $wallMinutes = $null
        }
    }

    $health = if ($status.status -ne "running") {
        [string]$status.status
    } elseif (-not $alive) {
        "missing_process"
    } elseif ($suspendGap) {
        "resumed_after_suspend"
    } elseif ($lowCpuChecks -ge $LowCpuLimit) {
        "suspected_stall"
    } elseif ($wallMinutes -ge $WarningWallMinutes) {
        "long_but_active"
    } else {
        "healthy"
    }

    [ordered]@{
        health = $health
        checked_at = $now.ToUniversalTime().ToString("o")
        pipeline_status = [string]$status.status
        stage = [string]$status.stage
        current_pair = [string]$status.current_pair
        completed = [int]$status.completed_in_stage
        expected = [int]$status.expected_in_stage
        unique_success = [int]$status.successful_unique_pairs
        pid = if ($alive) { [int]$worker.process.Id } else { $null }
        cpu_cores_equivalent = $cores
        ram_gib = if ($alive) { [math]::Round($worker.process.WorkingSet64 / 1GB, 2) } else { $null }
        current_run_wall_minutes = $wallMinutes
        suspend_gap_detected = $suspendGap
        consecutive_low_cpu_checks = $lowCpuChecks
        warning_threshold_wall_minutes = $WarningWallMinutes
    } | ConvertTo-Json | Set-Content -LiteralPath $healthTempPath -Encoding utf8
    Move-Item -LiteralPath $healthTempPath -Destination $healthPath -Force

    $lastCheck = $now
    $elapsed = ((Get-Date) - $loopStarted).TotalSeconds
    $remaining = [math]::Max(1, $IntervalSeconds - [int][math]::Ceiling($elapsed))
    Start-Sleep -Seconds $remaining
}
