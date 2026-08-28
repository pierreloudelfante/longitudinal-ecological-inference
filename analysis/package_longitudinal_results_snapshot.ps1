param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'

function Copy-DirectoryContents {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        throw "Dossier source introuvable : $Source"
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $Destination -Recurse -Force
    }
}

$snapshotLocal = Get-Date
$stamp = $snapshotLocal.ToString('yyyyMMdd_HHmmss')
$deliverablesRoot = Join-Path $ProjectRoot 'deliverables'
$packageName = "resultats_longitudinaux_R_Python_snapshot_$stamp"
$packageDir = Join-Path $deliverablesRoot $packageName
$zipPath = "$packageDir.zip"

New-Item -ItemType Directory -Path $deliverablesRoot -Force | Out-Null
if ((Test-Path -LiteralPath $packageDir) -or (Test-Path -LiteralPath $zipPath)) {
    throw "La destination existe deja : $packageName"
}

$pythonCandidate = Join-Path $ProjectRoot 'outputs\longitudinal_2000_v1\production\all_2x2_candidate'
$pythonProduction = Join-Path $ProjectRoot 'outputs\longitudinal_2000_v1\production'
$rRoot = Join-Path $ProjectRoot 'outputs\longitudinal_2000_v1\r_replication'

$pythonSelectionPath = Join-Path $pythonCandidate 'krt_240_candidate_selection.csv'
$pythonManifestPath = Join-Path $pythonCandidate 'krt_240_candidate_manifest.json'
if (-not (Test-Path -LiteralPath $pythonSelectionPath -PathType Leaf)) {
    throw "Selection Python introuvable : $pythonSelectionPath"
}
if (-not (Test-Path -LiteralPath $pythonManifestPath -PathType Leaf)) {
    throw "Manifeste Python introuvable : $pythonManifestPath"
}

$pythonSelection = @(Import-Csv -LiteralPath $pythonSelectionPath)
$pythonManifest = Get-Content -LiteralPath $pythonManifestPath -Raw | ConvertFrom-Json

# Fige la liste des runs R reussis avant toute copie. Pour un doublon, conserve le
# manifeste reussi le plus recent pour chaque couple scrutin-hypothese.
$rSuccessfulManifests = @(
    Get-ChildItem -LiteralPath $rRoot -Recurse -File -Filter 'manifest_r.json' | ForEach-Object {
        try {
            $manifest = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
            if ([string]$manifest.status -eq 'success') {
                [pscustomobject]@{
                    Election = [string]$manifest.election_id
                    Hypothesis = [string]$manifest.scenario_id
                    ManifestPath = $_.FullName
                    SourceDirectory = $_.Directory.FullName
                    Modified = $_.LastWriteTime
                    ElapsedSeconds = if ($null -ne $manifest.elapsed_seconds) { [double]$manifest.elapsed_seconds } else { $null }
                    Model = [string]$manifest.model
                }
            }
        } catch {
            Write-Warning "Manifeste R illisible ignore : $($_.FullName)"
        }
    }
)

$rKingSuccessfulManifests = @(
    $rSuccessfulManifests | Where-Object Model -eq 'King_1997_truncated_bivariate_normal_EI'
)
$rUnique = @(
    $rKingSuccessfulManifests |
        Group-Object Election, Hypothesis |
        ForEach-Object { $_.Group | Sort-Object Modified -Descending | Select-Object -First 1 } |
        Sort-Object Hypothesis, Election
)
$rExactUnique = @(
    $rSuccessfulManifests |
        Where-Object Model -eq 'exact_reimplementation_of_pyei_ei_beta_binom_model' |
        Group-Object Model, Election, Hypothesis |
        ForEach-Object { $_.Group | Sort-Object Modified -Descending | Select-Object -First 1 } |
        Sort-Object Hypothesis, Election
)

if ($rUnique.Count -eq 0) {
    throw 'Aucun run R reussi n a ete trouve.'
}

$expectedByHypothesis = [ordered]@{
    H0A = 26
    H0B = 26
    H0C = 26
    H1 = 26
    H2 = 26
    H3 = 26
    H4 = 26
    H5 = 26
    H6 = 16
    H7 = 16
}

$hypothesisLabels = [ordered]@{
    H0A = 'Ouvriers-employes et abstention'
    H0B = 'Ouvriers et abstention'
    H0C = 'Employes et abstention'
    H1 = 'Ouvriers-employes et vote a gauche'
    H2 = 'Ouvriers et vote a gauche'
    H3 = 'Employes et vote a gauche'
    H4 = 'Agriculteurs-independants versus salaries et vote a droite'
    H5 = 'Cadres et vote au centre'
    H6 = 'Ouvriers et vote FN/RN'
    H7 = 'Employes et vote FN/RN'
}

New-Item -ItemType Directory -Path $packageDir | Out-Null

# Python : tables communales et agregees, selection, audit et manifeste consolides.
$pythonOut = Join-Path $packageDir 'python\krt_beta_binomial_selection_consolidee'
Copy-DirectoryContents -Source $pythonCandidate -Destination $pythonOut

$pythonMetadataOut = Join-Path $packageDir 'python\metadonnees_production'
New-Item -ItemType Directory -Path $pythonMetadataOut -Force | Out-Null
@(
    'current_estimation_coverage.csv',
    'current_estimation_coverage.json',
    'runtime_final_scope_status_20260826.json',
    'runtime_final_scope_plan_20260826.json',
    'runtime_priority_queue_status_20260825.json',
    'runtime_priority_queue_plan_20260825.json',
    'pymc_parallel_remaining_stream_status.json',
    'pymc_remaining_hypotheses_chain_status.json',
    'pymc_h0bc_pilot_stream_status.json',
    'pymc_h45_pilot_stream_status.json'
) | ForEach-Object {
    $source = Join-Path $pythonProduction $_
    if (Test-Path -LiteralPath $source -PathType Leaf) {
        Copy-Item -LiteralPath $source -Destination $pythonMetadataOut -Force
    }
}

$runtimeEstimateBase = Join-Path $ProjectRoot 'analysis\king_backend_runtime_estimates_20260827'
@('.csv', '.json') | ForEach-Object {
    $source = "$runtimeEstimateBase$_"
    if (Test-Path -LiteralPath $source -PathType Leaf) {
        Copy-Item -LiteralPath $source -Destination $pythonMetadataOut -Force
    }
}

# R : chaque couple unique reussi, y compris les CSV communaux/agreges, le
# manifeste et l'objet RDS lorsqu'il a ete produit.
$rRunsOut = Join-Path $packageDir 'r\king_ei_eiPack\runs_reussis'
New-Item -ItemType Directory -Path $rRunsOut -Force | Out-Null
foreach ($run in $rUnique) {
    $pairName = "$($run.Election)__$($run.Hypothesis)"
    $pairOut = Join-Path $rRunsOut $pairName
    New-Item -ItemType Directory -Path $pairOut -Force | Out-Null
    Get-ChildItem -LiteralPath $run.SourceDirectory -File | Where-Object {
        $_.Extension -in @('.csv', '.json', '.rds')
    } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $pairOut -Force
    }
}

# Les essais R/NIMBLE de reimplementation exacte du KRT Python sont conserves,
# mais dans un dossier distinct pour ne jamais remplacer un resultat ei/eiPack.
if ($rExactUnique.Count -gt 0) {
    $rExactOut = Join-Path $packageDir 'r\krt_exact_nimble_tests\runs_reussis'
    New-Item -ItemType Directory -Path $rExactOut -Force | Out-Null
    foreach ($run in $rExactUnique) {
        $pairName = "$($run.Election)__$($run.Hypothesis)"
        $pairOut = Join-Path $rExactOut $pairName
        New-Item -ItemType Directory -Path $pairOut -Force | Out-Null
        Get-ChildItem -LiteralPath $run.SourceDirectory -File | Where-Object {
            $_.Extension -in @('.csv', '.json', '.rds')
        } | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $pairOut -Force
        }
    }
    $rExactUnique | Select-Object Election, Hypothesis, Model, ElapsedSeconds, Modified, ManifestPath |
        Export-Csv -LiteralPath (Join-Path $packageDir 'r\krt_exact_nimble_tests\index_tests_R_exacts.csv') -NoTypeInformation -Encoding utf8
}

$rCoverage = foreach ($hypothesis in $expectedByHypothesis.Keys) {
    $runs = @($rUnique | Where-Object Hypothesis -eq $hypothesis)
    $elapsed = @($runs | Where-Object { $null -ne $_.ElapsedSeconds } | ForEach-Object ElapsedSeconds)
    [pscustomobject]@{
        hypothesis = $hypothesis
        description = $hypothesisLabels[$hypothesis]
        expected_scrutins = $expectedByHypothesis[$hypothesis]
        completed_unique_pairs = $runs.Count
        missing_pairs = $expectedByHypothesis[$hypothesis] - $runs.Count
        mean_elapsed_seconds = if ($elapsed.Count -gt 0) { [math]::Round((($elapsed | Measure-Object -Average).Average), 2) } else { $null }
    }
}
$rCoveragePath = Join-Path $packageDir 'r\king_ei_eiPack\couverture_R_snapshot.csv'
$rCoverage | Export-Csv -LiteralPath $rCoveragePath -NoTypeInformation -Encoding utf8

$rRunsIndex = $rUnique | Select-Object Election, Hypothesis, Model, ElapsedSeconds, Modified, ManifestPath
$rRunsIndex | Export-Csv -LiteralPath (Join-Path $packageDir 'r\king_ei_eiPack\index_runs_R.csv') -NoTypeInformation -Encoding utf8

# Metadonnees et comparaisons R deja produites. Les consolidations anciennes sont
# isolees pour qu'elles ne soient pas confondues avec le snapshot par manifests.
$rMetadataOut = Join-Path $packageDir 'r\metadonnees_et_comparaisons'
New-Item -ItemType Directory -Path $rMetadataOut -Force | Out-Null
@(
    'king_ei_all_2x2_status.json',
    'king_ei_postprocess_watcher_status.json',
    'king_ei_progress_all_2x2.parquet',
    'king_ei_r_runtime_by_hypothesis.csv',
    'king_ei_r_runtime_by_hypothesis.parquet',
    'king_ei_r_runtime_by_run.csv',
    'king_ei_r_runtime_by_run.parquet',
    'king_ei_r_runtime_manifest.json',
    'longitudinal_nls_r.parquet',
    'nls_python_r_comparison.parquet',
    'nls_r_manifest.json',
    'nls_r_progress.parquet',
    'king_python_r_aggregate_comparison.parquet',
    'king_python_r_commune_comparison.parquet',
    'king_python_r_commune_comparison_summary.parquet',
    'king_python_r_comparison_manifest.json'
) | ForEach-Object {
    $source = Join-Path $rRoot $_
    if (Test-Path -LiteralPath $source -PathType Leaf) {
        Copy-Item -LiteralPath $source -Destination $rMetadataOut -Force
    }
}

# Figures existantes : trajectoires longitudinales, recap professeur et densites
# comparatives R/Python produites dans le projet.
$figuresOut = Join-Path $packageDir 'figures'
New-Item -ItemType Directory -Path $figuresOut -Force | Out-Null
@('longitudinal', 'longitudinal_2000_v1', 'professor_recap', 'densities') | ForEach-Object {
    $source = Join-Path (Join-Path $ProjectRoot 'figures') $_
    if (Test-Path -LiteralPath $source -PathType Container) {
        Copy-DirectoryContents -Source $source -Destination (Join-Path $figuresOut $_)
    }
}

$docsOut = Join-Path $packageDir 'documentation'
New-Item -ItemType Directory -Path $docsOut -Force | Out-Null
@(
    (Join-Path $ProjectRoot 'docs\FIGURE_CATALOG.md'),
    (Join-Path $ProjectRoot 'analysis\r_replication_longitudinal_2000_v1\README.md')
) | ForEach-Object {
    if (Test-Path -LiteralPath $_ -PathType Leaf) {
        Copy-Item -LiteralPath $_ -Destination $docsOut -Force
    }
}

$pythonCoverageRows = foreach ($hypothesis in $expectedByHypothesis.Keys) {
    $count = @($pythonSelection | Where-Object scenario_id -eq $hypothesis).Count
    [pscustomobject]@{
        hypothesis = $hypothesis
        description = $hypothesisLabels[$hypothesis]
        expected_scrutins = $expectedByHypothesis[$hypothesis]
        selected_python_pairs = $count
        missing_pairs = $expectedByHypothesis[$hypothesis] - $count
    }
}
$pythonCoverageRows | Export-Csv -LiteralPath (Join-Path $packageDir 'python\couverture_Python_snapshot.csv') -NoTypeInformation -Encoding utf8

$readmeLines = @(
    '# Resultats longitudinaux R et Python - instantane',
    '',
    "Instantane cree le $($snapshotLocal.ToString('yyyy-MM-dd HH:mm:ss zzz')).",
    '',
    '## Contenu principal',
    '',
    "- Python : $($pythonSelection.Count) couples hypothese-scrutin selectionnes sur $($pythonManifest.expected_pairs) prevus. Les tables Parquet communales et agregees, la selection, les diagnostics de selection et les audits sont dans `python/krt_beta_binomial_selection_consolidee`.",
    "- R : $($rUnique.Count) couples uniques termines avec succes au moment de l instantane, sur les 136 couples du perimetre R actuellement lance (H0A, H0B, H0C, H1, H6 et H7). Les doublons techniques sont ecartes en conservant le run reussi le plus recent.",
    ("- R/NIMBLE exact : {0} couple de test reussi est conserve separement dans r/krt_exact_nimble_tests ; il n est pas compte parmi les resultats classiques ei/eiPack." -f $rExactUnique.Count),
    '- Figures : trajectoires longitudinales, recapitulatif professeur et densites/comparaisons deja generees dans le projet.',
    '- NLS R et comparaisons R/Python : fichiers deja produits, ranges dans `r/metadonnees_et_comparaisons`.',
    '',
    '## Couverture par hypothese',
    '',
    '| Hypothese | Objet | Python | R | Attendu |',
    '|---|---|---:|---:|---:|'
)
foreach ($hypothesis in $expectedByHypothesis.Keys) {
    $pyCount = @($pythonSelection | Where-Object scenario_id -eq $hypothesis).Count
    $rCount = @($rUnique | Where-Object Hypothesis -eq $hypothesis).Count
    $readmeLines += "| $hypothesis | $($hypothesisLabels[$hypothesis]) | $pyCount | $rCount | $($expectedByHypothesis[$hypothesis]) |"
}
$readmeLines += @(
    '',
    '## Precautions d interpretation',
    '',
    '- Les estimations Python correspondent au modele KRT beta-binomial. La selection est partielle : son manifeste indique aussi les selections provisoires et les diagnostics MCMC non resolus.',
    '- Les estimations R correspondent au modele classique de King a normale bivariee tronquee via `ei`/`eiPack`. Ce modele n est pas mathematiquement identique au KRT beta-binomial Python : la comparaison constitue une validation croisee, pas une reproduction backend-pour-backend.',
    '- Le dossier `r/krt_exact_nimble_tests` contient une reimplementation R/NIMBLE experimentale du KRT beta-binomial. Elle est explicitement separee des estimations classiques de King.',
    '- Le calcul R etait encore en cours pendant la creation de cette archive. Cette livraison est donc un instantane des seuls manifests `success` figes avant la copie.',
    '- Les anciens fichiers consolides R n ont pas ete utilises pour compter la couverture, car ils etaient moins recents que les dossiers de runs. Les CSV/RDS de chaque run reussi sont la source de verite de cet instantane.',
    '- Les donnees sources brutes, environnements logiciels, caches et traces MCMC NetCDF ne sont pas inclus afin de garder une archive portable. Les estimations, diagnostics, manifests, objets RDS disponibles et figures le sont.',
    '',
    '## Reperes',
    '',
    '- `MANIFEST_SHA256.csv` donne la taille et le SHA-256 de chaque fichier de l archive avant compression.',
    '- `python/couverture_Python_snapshot.csv` et `r/king_ei_eiPack/couverture_R_snapshot.csv` donnent les comptes exacts par hypothese.',
    '- `r/king_ei_eiPack/index_runs_R.csv` indique le manifeste source et le temps de chaque run R retenu.'
)
$readmePath = Join-Path $packageDir 'README.md'
[System.IO.File]::WriteAllLines($readmePath, $readmeLines, [System.Text.UTF8Encoding]::new($false))

$manifestRows = Get-ChildItem -LiteralPath $packageDir -Recurse -File | Sort-Object FullName | ForEach-Object {
    [pscustomobject]@{
        relative_path = $_.FullName.Substring($packageDir.Length + 1).Replace('\', '/')
        size_bytes = $_.Length
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$manifestPath = Join-Path $packageDir 'MANIFEST_SHA256.csv'
$manifestRows | Export-Csv -LiteralPath $manifestPath -NoTypeInformation -Encoding utf8

$uncompressedBytes = (Get-ChildItem -LiteralPath $packageDir -Recurse -File | Measure-Object Length -Sum).Sum
Compress-Archive -LiteralPath $packageDir -DestinationPath $zipPath -CompressionLevel Optimal

# Verification lisible : ouvre chaque entree et lit son flux complet.
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
$buffer = New-Object byte[] 1048576
$verifiedEntries = 0
try {
    foreach ($entry in $archive.Entries) {
        if ([string]::IsNullOrEmpty($entry.Name)) { continue }
        $stream = $entry.Open()
        try {
            while ($stream.Read($buffer, 0, $buffer.Length) -gt 0) { }
        } finally {
            $stream.Dispose()
        }
        $verifiedEntries += 1
    }
} finally {
    $archive.Dispose()
}

$zipInfo = Get-Item -LiteralPath $zipPath
[pscustomobject]@{
    package_directory = $packageDir
    zip_path = $zipPath
    snapshot_local = $snapshotLocal.ToString('o')
    python_pairs = $pythonSelection.Count
    r_unique_success_pairs = $rUnique.Count
    r_king_success_manifests_seen = $rKingSuccessfulManifests.Count
    r_exact_unique_success_pairs = $rExactUnique.Count
    files_before_zip = (Get-ChildItem -LiteralPath $packageDir -Recurse -File).Count
    verified_zip_entries = $verifiedEntries
    uncompressed_mb = [math]::Round($uncompressedBytes / 1MB, 2)
    zip_mb = [math]::Round($zipInfo.Length / 1MB, 2)
    zip_sha256 = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
} | ConvertTo-Json -Depth 3
