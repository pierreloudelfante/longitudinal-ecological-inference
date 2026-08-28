param(
    [ValidateRange(1, 86400)]
    [int]$DelaySeconds = 7200,
    [string]$StatusPath = ""
)

$ErrorActionPreference = "Stop"

if (-not $StatusPath) {
    $StatusPath = Join-Path $PSScriptRoot "outputs\longitudinal_2000_v1\production\numpyro_continuation\scheduled_sleep.json"
}

$statusDirectory = Split-Path -Parent $StatusPath
New-Item -ItemType Directory -Force -Path $statusDirectory | Out-Null

$startedAt = Get-Date
$scheduledAt = $startedAt.AddSeconds($DelaySeconds)
[ordered]@{
    status = "waiting"
    process_id = $PID
    started_at = $startedAt.ToString("o")
    scheduled_at = $scheduledAt.ToString("o")
    delay_seconds = $DelaySeconds
} | ConvertTo-Json | Set-Content -LiteralPath $StatusPath -Encoding utf8

Start-Sleep -Seconds $DelaySeconds

[ordered]@{
    status = "requesting_sleep"
    process_id = $PID
    started_at = $startedAt.ToString("o")
    scheduled_at = $scheduledAt.ToString("o")
    requested_at = (Get-Date).ToString("o")
} | ConvertTo-Json | Set-Content -LiteralPath $StatusPath -Encoding utf8

Add-Type -AssemblyName System.Windows.Forms
$sleepRequested = [System.Windows.Forms.Application]::SetSuspendState(
    [System.Windows.Forms.PowerState]::Suspend,
    $false,
    $false
)

[ordered]@{
    status = if ($sleepRequested) { "resumed_after_sleep" } else { "sleep_request_rejected" }
    process_id = $PID
    scheduled_at = $scheduledAt.ToString("o")
    returned_at = (Get-Date).ToString("o")
} | ConvertTo-Json | Set-Content -LiteralPath $StatusPath -Encoding utf8
