[CmdletBinding()]
param(
    [string]$DossierDestination = '',
    [switch]$VerifierSeulement
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'Continue'

$ManifestPath = Join-Path $PSScriptRoot 'reproducibility\contract_v2\raw_sources_31.json'
if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    throw "Manifeste introuvable : $ManifestPath"
}

$sources = @((Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json).raw_sources)
if ($sources.Count -ne 31) {
    throw "Le manifeste contient $($sources.Count) archives au lieu de 31."
}

if ([string]::IsNullOrWhiteSpace($DossierDestination)) {
    $DossierDestination = Join-Path $PSScriptRoot 'DONNEES_BRUTES'
}
$destination = [System.IO.Path]::GetFullPath($DossierDestination)
if (-not (Test-Path -LiteralPath $destination -PathType Container)) {
    if ($VerifierSeulement) {
        throw "Dossier de donnees absent : $destination"
    }
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
}

# Windows PowerShell 5.1 peut encore choisir un protocole TLS ancien par defaut.
if ([Net.ServicePointManager]::SecurityProtocol -band [Net.SecurityProtocolType]::Tls12 -eq 0) {
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
}

function Test-SourceFile {
    param(
        [Parameter(Mandatory)] [string]$Path,
        [Parameter(Mandatory)] [object]$Source
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }
    $item = Get-Item -LiteralPath $Path
    if ([int64]$item.Length -ne [int64]$Source.bytes) {
        return $false
    }
    $observed = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    return $observed -eq ([string]$Source.required_sha256).ToLowerInvariant()
}

$verified = 0
$totalBytes = [int64]0
foreach ($source in $sources) {
    $finalPath = Join-Path $destination ([string]$source.name)
    $downloadPath = Join-Path $destination ([string]$source.download_name)
    $candidatePaths = @($finalPath)
    if (-not [StringComparer]::OrdinalIgnoreCase.Equals($downloadPath, $finalPath)) {
        $candidatePaths += $downloadPath
    }

    # Le manifeste publie un nom canonique et le nom original du serveur.
    # Les deux sont acceptes par le lanceur scientifique; l'acquisition et son
    # mode de verification doivent appliquer exactement la meme convention.
    $authenticatedPath = $null
    $nonconforming = @()
    foreach ($candidatePath in $candidatePaths) {
        if (Test-SourceFile -Path $candidatePath -Source $source) {
            if ($null -eq $authenticatedPath) {
                $authenticatedPath = $candidatePath
            }
        }
        elseif (Test-Path -LiteralPath $candidatePath) {
            $nonconforming += $candidatePath
        }
    }
    if ($null -ne $authenticatedPath) {
        if ($nonconforming.Count -gt 0) {
            Write-Warning ("Copie supplementaire ignoree car non conforme : " + ($nonconforming -join ', '))
        }
        $verified++
        $totalBytes += [int64]$source.bytes
        Write-Host "[$verified/31] deja authentifiee : $([System.IO.Path]::GetFileName($authenticatedPath))"
        continue
    }

    if ($nonconforming.Count -gt 0) {
        throw "Archive presente mais non conforme : $($nonconforming -join ', '). Deplacez-la hors du dossier puis relancez."
    }
    if ($VerifierSeulement) {
        throw "Archive absente : attendu $($candidatePaths -join ' ou ')"
    }

    $temporaryPath = "$finalPath.telechargement-$PID.part"
    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath -Force
    }
    try {
        Write-Host "Telechargement : $($source.name)"
        Invoke-WebRequest -Uri ([string]$source.source_url) -OutFile $temporaryPath `
            -UseBasicParsing -MaximumRedirection 5 -TimeoutSec 7200
        if (-not (Test-SourceFile -Path $temporaryPath -Source $source)) {
            throw "Le fichier telecharge ne correspond ni a la taille ni au SHA-256 attendu : $($source.name)"
        }
        Move-Item -LiteralPath $temporaryPath -Destination $finalPath
    }
    catch {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
        throw
    }

    $verified++
    $totalBytes += [int64]$source.bytes
    Write-Host "[$verified/31] telechargee et authentifiee : $($source.name)"
}

if ($verified -ne 31 -or $totalBytes -ne 1620387967) {
    throw "Controle incomplet : $verified/31 archives, $totalBytes octets."
}

Write-Host ''
Write-Host 'DONNEES BRUTES PRETES : 31/31 archives, 1 620 387 967 octets, SHA-256 conformes.'
Write-Host 'Le preflight de REPRODUIRE_TOUT.ps1 verifiera ensuite integralement ZIP, decompression et CRC.'
