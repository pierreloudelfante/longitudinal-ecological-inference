[CmdletBinding()]
param(
    [string]$DossierDonneesBrutes = "",
    [string]$ArchiveResultatsReference = "",
    [string]$PythonExe = "",
    [string]$RscriptExe = "",
    [string]$NavigateurExe = "",
    [switch]$SansInstallation,
    [switch]$AutoriserInstallationExterne,
    [switch]$PreflightSeulement,
    [switch]$PlanSeulement,
    [switch]$ReessayerEchecs,
    [double]$MinimumFreeDiskGB = 0,
    [double]$MinimumAvailableMemoryGB = 0,
    [switch]$ExigerRessourcesRecommandees,
    # Controle interne borne; la reproduction complete reste le parcours par defaut.
    [switch]$Controle2022,
    [switch]$ControleCourt,
    [switch]$SansPresentation,
    # Limites murales d'orchestration uniquement; aucun reglage scientifique ne change.
    [int]$LimiteKRTHeures = 24,
    [int]$LimiteNLSMinutes = 120,
    [int]$LimiteNLSRxCMinutes = 120,
    [int]$LimiteCovariablesMinutes = 60,
    [int]$LimiteKingRHeures = 12,
    [int]$LimiteAttenteMemoireRMinutes = 240,
    [int]$IntervalleHeartbeatSecondes = 30
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$scriptBoundParameters = @{}
foreach ($item in $PSBoundParameters.GetEnumerator()) {
    $scriptBoundParameters[$item.Key] = $item.Value
}
if ($Controle2022 -and $ControleCourt) { throw "Choisir un seul controle interne: -Controle2022 ou -ControleCourt." }
if ($MinimumFreeDiskGB -lt 0 -or $MinimumAvailableMemoryGB -lt 0) {
    throw "Les seuils de disque et de memoire doivent etre positifs."
}
$replicationScope = if ($ControleCourt -or $Controle2022) { "court" } else { "full" }
$env:LONGITUDINAL_REPLICATION_SCOPE = $replicationScope
$env:LONGITUDINAL_RETRY_FAILED = if ($ReessayerEchecs) { "1" } else { "0" }
$limits = @($LimiteKRTHeures, $LimiteNLSMinutes, $LimiteNLSRxCMinutes,
    $LimiteCovariablesMinutes, $LimiteKingRHeures, $LimiteAttenteMemoireRMinutes,
    $IntervalleHeartbeatSecondes)
if (@($limits | Where-Object { $_ -le 0 }).Count -gt 0) {
    throw "Toutes les limites de temps et l'intervalle heartbeat doivent etre strictement positifs."
}
$env:LONGITUDINAL_TIMEOUT_KRT_SECONDS = [string]($LimiteKRTHeures * 3600)
$env:LONGITUDINAL_TIMEOUT_NLS_SECONDS = [string]($LimiteNLSMinutes * 60)
$env:LONGITUDINAL_TIMEOUT_NLS_RXC_SECONDS = [string]($LimiteNLSRxCMinutes * 60)
$env:LONGITUDINAL_TIMEOUT_COVARIATE_SECONDS = [string]($LimiteCovariablesMinutes * 60)
$env:LONGITUDINAL_TIMEOUT_KING_R_SECONDS = [string]($LimiteKingRHeures * 3600)
$env:LONGITUDINAL_R_MEMORY_WAIT_SECONDS = [string]($LimiteAttenteMemoireRMinutes * 60)
$env:LONGITUDINAL_HEARTBEAT_SECONDS = [string]$IntervalleHeartbeatSecondes
if ($MinimumFreeDiskGB -gt 0) {
    $env:LONGITUDINAL_MIN_FREE_DISK_GB = $MinimumFreeDiskGB.ToString([Globalization.CultureInfo]::InvariantCulture)
}
if ($MinimumAvailableMemoryGB -gt 0) {
    $env:LONGITUDINAL_MIN_AVAILABLE_MEMORY_GB = $MinimumAvailableMemoryGB.ToString([Globalization.CultureInfo]::InvariantCulture)
}
if ($ExigerRessourcesRecommandees) { $env:LONGITUDINAL_ENFORCE_RESOURCE_RECOMMENDATIONS = "1" }
if ($Controle2022) { Write-Warning "-Controle2022 est un ancien alias. Le controle commun couvre desormais plusieurs elections; utiliser -ControleCourt." }
if (-not $DossierDonneesBrutes) {
    $DossierDonneesBrutes = Join-Path $PSScriptRoot "DONNEES_BRUTES"
}
if (-not $ArchiveResultatsReference) {
    $ArchiveResultatsReference = Join-Path $PSScriptRoot "longitudinal_2000_results.zip"
}
function Invoke-External([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Echec ($LASTEXITCODE) : $Exe $($Arguments -join ' ')" }
}
function ConvertTo-PowerShellLiteral([string]$Value) {
    return "'" + $Value.Replace("'", "''") + "'"
}
function New-ResumeCommand([hashtable]$BoundParameters) {
    $parts = @("powershell", "-ExecutionPolicy", "Bypass", "-File", ".\REPRODUIRE_TOUT.ps1")
    $orderedNames = @(
        "DossierDonneesBrutes", "ArchiveResultatsReference", "PythonExe", "RscriptExe", "NavigateurExe",
        "SansInstallation", "AutoriserInstallationExterne", "PreflightSeulement", "PlanSeulement",
        "ReessayerEchecs", "MinimumFreeDiskGB", "MinimumAvailableMemoryGB",
        "ExigerRessourcesRecommandees", "Controle2022", "ControleCourt", "SansPresentation",
        "LimiteKRTHeures", "LimiteNLSMinutes", "LimiteNLSRxCMinutes", "LimiteCovariablesMinutes",
        "LimiteKingRHeures", "LimiteAttenteMemoireRMinutes", "IntervalleHeartbeatSecondes"
    )
    $switchNames = @(
        "SansInstallation", "AutoriserInstallationExterne", "PreflightSeulement", "PlanSeulement",
        "ReessayerEchecs", "ExigerRessourcesRecommandees", "Controle2022", "ControleCourt", "SansPresentation"
    )
    foreach ($name in $orderedNames) {
        if (-not $BoundParameters.ContainsKey($name)) { continue }
        $value = $BoundParameters[$name]
        if ($switchNames -contains $name) {
            if ([bool]$value) { $parts += "-$name" }
            continue
        }
        $parts += "-$name"
        if ($value -is [string]) {
            $parts += ConvertTo-PowerShellLiteral $value
        } elseif ($value -is [IFormattable]) {
            $parts += $value.ToString($null, [Globalization.CultureInfo]::InvariantCulture)
        } else {
            $parts += ConvertTo-PowerShellLiteral ([string]$value)
        }
    }
    return ($parts -join " ")
}
function Get-PythonRuntimeStatus([string]$Exe, [string[]]$PrefixArguments = @()) {
    $inspectionCode = @'
import json, platform, struct, sys
print(json.dumps({
    "version": platform.python_version(),
    "system": platform.system(),
    "machine": platform.machine(),
    "pointer_bits": struct.calcsize("P") * 8,
    "is_venv": sys.prefix != sys.base_prefix,
}))
'@
    try {
        # Standard input preserves Python quotes under Windows PowerShell 5.1.
        $inspectionOutput = $inspectionCode | & $Exe @PrefixArguments -I - 2>$null
        $inspectionExit = $LASTEXITCODE
        if ($inspectionExit -ne 0) { return $null }
        $status = (($inspectionOutput -join "`n") | ConvertFrom-Json)
        $null = & $Exe @PrefixArguments -I -m pip --version 2>$null
        $pipExit = $LASTEXITCODE
        $status | Add-Member -NotePropertyName pip_usable -NotePropertyValue ($pipExit -eq 0)
        return $status
    } catch {
        return $null
    }
}
function Test-PythonRuntimeStatus($Status, [switch]$RequireVirtualEnvironment) {
    if ($null -eq $Status) { return $false }
    $machine = ([string]$Status.machine).ToLowerInvariant()
    return (($Status.version -eq "3.12.10") -and ($Status.system -eq "Windows") -and
        ($Status.pointer_bits -eq 64) -and ($machine -in @("amd64", "x86_64")) -and
        [bool]$Status.pip_usable -and (-not $RequireVirtualEnvironment -or [bool]$Status.is_venv))
}
function Get-PythonDependencyStatus([string]$Exe, [string]$LockPath) {
    $inspectionCode = @'
import importlib.metadata, json, pathlib, sys
requirements = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() + ["mistune==3.3.4"]
mismatches = []
count = 0
for requirement in requirements:
    requirement = requirement.strip()
    if not requirement or requirement.startswith("#"):
        continue
    name, expected = requirement.split("==", 1)
    count += 1
    try:
        observed = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        observed = "absent"
    if observed != expected:
        mismatches.append({"requirement": requirement, "observed": observed})
print(json.dumps({"checked": count, "mismatches": mismatches, "is_venv": sys.prefix != sys.base_prefix}))
'@
    # Standard input preserves Python quotes under Windows PowerShell 5.1.
    $inspectionJson = $inspectionCode | & $Exe -I - $LockPath
    if ($LASTEXITCODE -ne 0) { throw "Impossible de verifier les dependances de $Exe." }
    return ($inspectionJson | ConvertFrom-Json)
}
$journalDir = Join-Path $PSScriptRoot "JOURNAUX_REPRODUCTION"
$journal = Join-Path $journalDir ("reproduction_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")
$launcherStartedUtc = [DateTime]::UtcNow
$resumeCommand = New-ResumeCommand $scriptBoundParameters
$env:LONGITUDINAL_RESUME_COMMAND = $resumeCommand
$transcriptStarted = $false
try {
    New-Item -ItemType Directory -Force -Path $journalDir | Out-Null
    try {
        Start-Transcript -LiteralPath $journal | Out-Null
        $transcriptStarted = $true
    } catch {
        Write-Warning "Le transcript PowerShell n'a pas pu demarrer; les journaux d'etapes et les recus d'echec restent actifs. $($_.Exception.Message)"
    }
    $nativeArchitecture = if ($env:PROCESSOR_ARCHITEW6432) {
        $env:PROCESSOR_ARCHITEW6432
    } else {
        $env:PROCESSOR_ARCHITECTURE
    }
    if ($env:OS -ne "Windows_NT" -or $nativeArchitecture -ne "AMD64") {
        throw "Plateforme non prise en charge: Windows x86-64 (AMD64) est requis; observe: OS=$($env:OS), architecture=$nativeArchitecture."
    }
    if ($PlanSeulement) {
        $planArguments = @("-m", "reproducibility.replication_complete", "plan", "--scope", $replicationScope)
        if ($PythonExe) { Invoke-External $PythonExe $planArguments }
        else { Invoke-External "py" (@("-3") + $planArguments) }
        return
    }
    $limitMessage = (("Limites par estimation : KRT {0} h; NLS {1} min; NLS RxC {2} min; " +
        "covariables {3} min; King R {4} h; attente memoire R {5} min; heartbeat {6} s.") -f
        $LimiteKRTHeures, $LimiteNLSMinutes, $LimiteNLSRxCMinutes,
        $LimiteCovariablesMinutes, $LimiteKingRHeures, $LimiteAttenteMemoireRMinutes,
        $IntervalleHeartbeatSecondes)
    Write-Host $limitMessage
    if (-not $PythonExe) {
        $projectEnvironment = Join-Path $PSScriptRoot ".venv-reproduction"
        $PythonExe = Join-Path $projectEnvironment "Scripts\python.exe"
        $creationMarker = Join-Path $projectEnvironment ".creation-in-progress"
        $existingStatus = $null
        if ((Test-Path -LiteralPath $PythonExe) -and -not (Test-Path -LiteralPath $creationMarker)) {
            $existingStatus = Get-PythonRuntimeStatus $PythonExe
        }
        if (-not (Test-PythonRuntimeStatus $existingStatus -RequireVirtualEnvironment)) {
            if ($SansInstallation) {
                throw "Environnement local absent ou incomplet (Python 3.12.10 Windows x86-64 avec pip requis); retirer -SansInstallation ou fournir -PythonExe."
            }
            $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
            if (-not $pyLauncher) {
                throw "Python Launcher absent. Installer Python 3.12.10 x86-64 avec l'option 'py launcher', puis relancer."
            }
            $bootstrapStatus = Get-PythonRuntimeStatus $pyLauncher.Source @("-3.12")
            if (-not (Test-PythonRuntimeStatus $bootstrapStatus)) {
                $observed = if ($null -eq $bootstrapStatus) { "indisponible ou pip absent" } else {
                    "$($bootstrapStatus.version), $($bootstrapStatus.system), $($bootstrapStatus.machine), $($bootstrapStatus.pointer_bits) bits"
                }
                throw "Python 3.12.10 Windows x86-64 avec pip est requis pour creer l'environnement; observe : $observed"
            }
            if (Test-Path -LiteralPath $projectEnvironment) {
                Write-Warning "Environnement local incomplet detecte; reconstruction de .venv-reproduction."
                Remove-Item -LiteralPath $projectEnvironment -Recurse -Force
            }
            New-Item -ItemType Directory -Path $projectEnvironment | Out-Null
            Set-Content -LiteralPath $creationMarker -Value ([DateTime]::UtcNow.ToString("o")) -Encoding ascii
            Invoke-External $pyLauncher.Source @("-3.12", "-m", "venv", $projectEnvironment)
            $createdStatus = Get-PythonRuntimeStatus $PythonExe
            if (-not (Test-PythonRuntimeStatus $createdStatus -RequireVirtualEnvironment)) {
                throw "Creation de l'environnement Python incomplete; relancer reconstruira automatiquement .venv-reproduction."
            }
            Remove-Item -LiteralPath $creationMarker -Force
        }
    }
    $PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
    $pythonStatus = Get-PythonRuntimeStatus $PythonExe
    if (-not (Test-PythonRuntimeStatus $pythonStatus)) {
        throw "Python 3.12.10 Windows x86-64 avec pip attendu pour -PythonExe."
    }
    # Les 31 sources sont vérifiées avant d'installer ou de lancer un seul estimateur.
    Invoke-External $PythonExe @("-m", "reproducibility.replication_complete", "raw", "--raw-dir", $DossierDonneesBrutes)
    $lockPath = Join-Path $PSScriptRoot "reproducibility\requirements-python312.lock.txt"
    $dependencyStatus = Get-PythonDependencyStatus $PythonExe $lockPath
    $mismatches = @($dependencyStatus.mismatches)
    $installedPackages = $false
    if ($mismatches.Count -gt 0) {
        $missingDescription = ($mismatches | ForEach-Object { "$($_.requirement) (observe: $($_.observed))" }) -join ", "
        if ($SansInstallation) { throw "Dependances manquantes ou differentes; -SansInstallation interdit leur installation: $missingDescription" }
        $projectPython = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".venv-reproduction\Scripts\python.exe"))
        $usesProjectEnvironment = $PythonExe -ieq $projectPython
        if (-not $usesProjectEnvironment -and -not $AutoriserInstallationExterne) {
            throw "Environnement -PythonExe externe incomplet, laisse intact: $missingDescription. Utiliser l'environnement local par defaut, ou ajouter -AutoriserInstallationExterne pour autoriser uniquement la mise a niveau de cet environnement virtuel."
        }
        if (-not $dependencyStatus.is_venv) {
            throw "Installation refusee dans un Python global. Utiliser l'environnement local par defaut ou fournir un environnement virtuel avec -PythonExe."
        }
        $requirementsToInstall = @($mismatches | ForEach-Object { $_.requirement })
        Write-Host "Installation locale des seuls paquets manquants ou differents: $($requirementsToInstall -join ', ')"
        # Isolated pip ignores host user/target settings; no shared download cache
        # or unrelated dependency upgrade is created by this bootstrap.
        Invoke-External $PythonExe (@("-m", "pip", "--isolated", "install", "--no-user", "--no-cache-dir", "--disable-pip-version-check", "--no-deps") + $requirementsToInstall)
        $dependencyStatus = Get-PythonDependencyStatus $PythonExe $lockPath
        if (@($dependencyStatus.mismatches).Count -gt 0) { throw "L'environnement ne respecte toujours pas le verrou apres installation." }
        $installedPackages = $true
    }
    # Exact versions do not authorize silently repairing unrelated pip conflicts.
    Invoke-External $PythonExe @("-m", "pip", "--isolated", "check")
    if (-not $installedPackages) { Write-Host "Environnement reutilise: $($dependencyStatus.checked) versions exactes, aucun paquet installe." }
    if (-not $RscriptExe -and $env:LONGITUDINAL_RSCRIPT) { $RscriptExe = $env:LONGITUDINAL_RSCRIPT }
    if (-not $RscriptExe) {
        # Prefer the exact documented R even when an older Rscript appears first on PATH.
        $rRoot = Join-Path $env:ProgramFiles "R"
        if (Test-Path -LiteralPath $rRoot) {
            $r = Get-ChildItem -LiteralPath $rRoot -Recurse -Filter Rscript.exe -File |
                Where-Object { $_.FullName -match 'R-4\.6\.0' } | Select-Object -First 1
            if ($r) { $RscriptExe = $r.FullName }
        }
        if (-not $RscriptExe) {
            $r = Get-Command Rscript.exe -ErrorAction SilentlyContinue
            if ($r) { $RscriptExe = $r.Source }
        }
    }
    if (-not $RscriptExe) { throw "R 4.6.0 requis; fournir -RscriptExe chemin\vers\Rscript.exe." }
    if (-not $NavigateurExe) {
        $candidates = @(
            (Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"),
            (Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe"),
            (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
            (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
        )
        foreach ($c in $candidates) {
            if (Test-Path -LiteralPath $c) { $NavigateurExe = $c; break }
        }
    }
    if (-not $NavigateurExe) { throw "Edge/Chrome requis pour recalculer le PDF; fournir -NavigateurExe." }
    $action = if ($PreflightSeulement) { "preflight" } else { "run" }
    $pipelineArguments = @("-m", "reproducibility.replication_complete", $action, "--scope", $replicationScope,
        "--raw-dir", $DossierDonneesBrutes, "--rscript", $RscriptExe, "--browser", $NavigateurExe,
        "--reference-results", $ArchiveResultatsReference)
    if ($ReessayerEchecs) { $pipelineArguments += "--retry-failed" }
    Invoke-External $PythonExe $pipelineArguments
    Write-Host "Journal : $journal"
    # SansPresentation est conservé pour compatibilité. Le périmètre résultats ne contient pas de PPTX.
} catch {
    # Also works when Python or a prerequisite is missing: no AI or Python is
    # required to read this handoff. Keep the richer worker report when fresh.
    $failureJson = Join-Path $journalDir "DERNIER_ECHEC.json"
    $failureText = Join-Path $journalDir "DERNIER_ECHEC.txt"
    $freshFailure = (Test-Path -LiteralPath $failureJson) -and
        ((Get-Item -LiteralPath $failureJson).LastWriteTimeUtc -ge $launcherStartedUtc)
    if (-not $freshFailure) {
        $failureMessage = $_.Exception.Message
        $handoff = [ordered]@{
            schema_version = 'professor_failure_handoff_v1'; status = 'launcher_failed';
            recorded_at_utc = [DateTime]::UtcNow.ToString('o'); scope = $replicationScope;
            stage = 'preparation_du_lanceur'; message = $failureMessage;
            transcript = $journal; resume_command = $resumeCommand;
            scientific_certification = $false; preserve_completed_outputs = $true
        }
        $instructions = @(
            'CE LANCEMENT A ECHOUE - AUCUNE NOUVELLE CERTIFICATION',
            '', ('Erreur : ' + $failureMessage), '',
            'Ne pas supprimer le dossier ni les resultats deja produits.',
            'Corriger le prerequis ou la cause indiquee avant de relancer votre commande initiale dans ce meme dossier.',
            'Commande de reprise exacte (chemins et options conserves) :',
            $resumeCommand, '',
            'Si la meme erreur revient, ne pas relancer en boucle : contacter l''auteur.',
            'Transmettre DERNIER_ECHEC.txt, DERNIER_ECHEC.json et le journal suivant :',
            $journal, '',
            'Ne pas modifier le code dans ce dossier; un paquet corrige exige une extraction neuve.'
        )
        try {
            $handoff | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $failureJson -Encoding utf8
            $instructions | Set-Content -LiteralPath $failureText -Encoding utf8
        } catch {
            Write-Warning ('Impossible d''ecrire le resume; conserver le message et le journal : ' + $journal)
        }
    }
    Write-Host ('ECHEC - consignes a lire : ' + $failureText) -ForegroundColor Red
    throw
} finally {
    if ($transcriptStarted) {
        try { Stop-Transcript | Out-Null } catch { Write-Warning "Impossible d'arreter proprement le transcript PowerShell." }
    }
}
