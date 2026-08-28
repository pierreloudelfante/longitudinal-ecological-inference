param(
    [Parameter(Mandatory = $true)][int]$BenchmarkPid,
    [Parameter(Mandatory = $true)][string]$BenchmarkStdout,
    [Parameter(Mandatory = $true)][string]$PythonPath
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$productionRoot = Join-Path $projectRoot "outputs\longitudinal_2000_v1\production\longitudinal_2000_v1.1_H0A_H1_H2_H3_pymc_fallback"
$statusPath = Join-Path $productionRoot "pymc_fallback_chain_status.json"

function Write-ChainStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [string]$Detail = ""
    )
    [ordered]@{
        status = $Status
        detail = $Detail
        benchmark_pid = $BenchmarkPid
        benchmark_stdout = $BenchmarkStdout
        updated_at = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
}

Write-ChainStatus -Status "waiting_for_benchmark"
Wait-Process -Id $BenchmarkPid

if (-not (Test-Path -LiteralPath $BenchmarkStdout)) {
    Write-ChainStatus -Status "benchmark_failed" -Detail "benchmark stdout is missing"
    exit 2
}

try {
    $benchmark = Get-Content -LiteralPath $BenchmarkStdout -Raw | ConvertFrom-Json
} catch {
    Write-ChainStatus -Status "benchmark_failed" -Detail "benchmark stdout is not valid JSON"
    exit 2
}

if ([int]$benchmark.success_or_resumed -lt 1 -or [int]$benchmark.failed -gt 0) {
    Write-ChainStatus -Status "benchmark_failed" -Detail "PyMC benchmark did not produce a successful auditable run"
    exit 2
}

Write-ChainStatus -Status "launching_supervisor" -Detail "benchmark passed; starting run-level H2/H3 continuation"
& $PythonPath -m code_longitudinal.h23_supervisor `
    --release-config config\releases\v1.1_pymc_fallback.json `
    --continue-after-failed-pilots
$supervisorExit = $LASTEXITCODE

if ($supervisorExit -eq 0) {
    Write-ChainStatus -Status "supervisor_finished" -Detail "H2/H3 fallback supervisor exited successfully"
} else {
    Write-ChainStatus -Status "supervisor_blocked" -Detail "H2/H3 fallback supervisor exit code: $supervisorExit"
}
exit $supervisorExit
