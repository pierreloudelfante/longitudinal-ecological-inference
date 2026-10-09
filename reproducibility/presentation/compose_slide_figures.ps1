param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$figureRoot = Join-Path $ProjectRoot 'work\longitudinal_2000_release_professeur_candidate\03_FIGURES\trajectoires_KRT_R_NLS_toutes_hypotheses'
$outputRoot = Join-Path $figureRoot 'combined'
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null

foreach ($scenario in @('H0B', 'H0C', 'H2', 'H3', 'H4', 'H5', 'H6', 'H7')) {
    $leftPath = Join-Path $figureRoot "$scenario\${scenario}_legislative.png"
    $rightPath = Join-Path $figureRoot "$scenario\${scenario}_presidential.png"
    if (-not (Test-Path -LiteralPath $leftPath) -or -not (Test-Path -LiteralPath $rightPath)) {
        throw "Missing trajectory figure for $scenario"
    }

    $left = [System.Drawing.Image]::FromFile($leftPath)
    $right = [System.Drawing.Image]::FromFile($rightPath)
    try {
        $targetHeight = 900
        $gutter = 24
        $leftWidth = [int][Math]::Round($left.Width * $targetHeight / $left.Height)
        $rightWidth = [int][Math]::Round($right.Width * $targetHeight / $right.Height)
        $canvas = New-Object System.Drawing.Bitmap ($leftWidth + $gutter + $rightWidth), $targetHeight
        try {
            $graphics = [System.Drawing.Graphics]::FromImage($canvas)
            try {
                $graphics.Clear([System.Drawing.Color]::White)
                $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $graphics.DrawImage($left, 0, 0, $leftWidth, $targetHeight)
                $graphics.DrawImage($right, $leftWidth + $gutter, 0, $rightWidth, $targetHeight)
            }
            finally {
                $graphics.Dispose()
            }
            $outputPath = Join-Path $outputRoot "${scenario}_legislative_presidential.png"
            $canvas.Save($outputPath, [System.Drawing.Imaging.ImageFormat]::Png)
        }
        finally {
            $canvas.Dispose()
        }
    }
    finally {
        $left.Dispose()
        $right.Dispose()
    }
}

Get-ChildItem -LiteralPath $outputRoot -Filter '*.png' | Select-Object Name, Length
