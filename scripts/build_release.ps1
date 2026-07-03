param(
    [switch]$Installer,
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
# Resolve Python without depending on any one machine's install path:
# explicit override first, then the py launcher, then python.exe on PATH.
$pyLauncher = & py -3 -c "import sys; print(sys.executable)" 2>$null

$pythonCandidates = @(
    $env:PANO_PRO_PYTHON,
    $pyLauncher,
    (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue)
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique

if (-not $pythonCandidates) {
    throw "Python was not found. Set PANO_PRO_PYTHON or install Python 3.13."
}

$python = $pythonCandidates[0]
$version = & $python -c "from pano_namer import __version__; print(__version__)" 2>$null
if (-not $version) {
    throw "Could not read the PanoPro version from pano_namer.__init__."
}

Push-Location $projectRoot
try {
    Write-Host "Using Python:" $python
    Write-Host "Building PANO PRO v$version"

    & $python -m PyInstaller --noconfirm --clean "PANO-PRO.spec"

    $distRoot = Join-Path $projectRoot "dist"
    $appDir = Join-Path $distRoot "PANO-PRO"
    if (-not (Test-Path $appDir)) {
        throw "PyInstaller build did not produce '$appDir'."
    }

    if (-not $SkipZip) {
        $zipPath = Join-Path $distRoot ("PANO-PRO-v{0}-windows.zip" -f $version)
        if (Test-Path $zipPath) {
            Remove-Item $zipPath -Force
        }
        Compress-Archive -Path (Join-Path $appDir "*") -DestinationPath $zipPath
        Write-Host "Portable zip created:" $zipPath
    }

    if ($Installer) {
        $isccCandidates = @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
        ) | Where-Object { Test-Path $_ }

        if (-not $isccCandidates) {
            throw "Inno Setup 6 was not found. Install it or rerun without -Installer."
        }

        $iscc = $isccCandidates[0]
        & $iscc "/DAppVersion=$version" "installer\PANO-PRO.iss"
        Write-Host "Installer created in dist\installer"
    }

    Write-Host "Build complete."
}
finally {
    Pop-Location
}
