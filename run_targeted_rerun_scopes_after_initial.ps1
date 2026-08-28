param(
    [Parameter(Mandatory = $true)][int]$InitialStreamPid,
    [Parameter(Mandatory = $true)][string]$PythonPath
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$statusPath = Join-Path $projectRoot "outputs\longitudinal_2000_v1\production\pymc_targeted_rerun_scopes_status.json"
$configs = @(
    "config\releases\v1.2_pymc_h6_h7.json",
    "config\releases\v1.3_pymc_h0b_h0c.json",
    "config\releases\v1.4_pymc_h4_h5.json"
)

function Write-ScopeStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Status,
        [int]$Completed = 0,
        [string]$CurrentConfig = "",
        [int]$Unresolved = 0
    )
    [ordered]@{
        status = $Status
        predecessor_pid = $InitialStreamPid
        scopes_completed = $Completed
        scopes_expected = $configs.Count
        current_config = $CurrentConfig
        unresolved_scopes = $Unresolved
        updated_at = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
}

Write-ScopeStatus -Status "waiting_for_all_initial_scopes"
Wait-Process -Id $InitialStreamPid

$completed = 0
$unresolved = 0
foreach ($config in $configs) {
    Write-ScopeStatus -Status "running" -Completed $completed -CurrentConfig $config -Unresolved $unresolved
    $resultText = (& $PythonPath -m code_longitudinal.targeted_rerun_scope --release-config $config | Out-String)
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        $unresolved += 1
    } else {
        try {
            $result = $resultText | ConvertFrom-Json
            if ([int]$result.unresolved_pairs -gt 0) {
                $unresolved += 1
            }
        } catch {
            $unresolved += 1
        }
    }
    $completed += 1
}

$terminal = if ($unresolved -eq 0) { "completed" } else { "completed_with_unresolved_scopes" }
Write-ScopeStatus -Status $terminal -Completed $completed -Unresolved $unresolved
exit 0
