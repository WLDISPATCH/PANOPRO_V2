# PANO PRO standalone bootstrap.
#
# Downloads the whole app from the public GitHub repo into a per-user folder
# and runs the installer. Works from nothing (no pre-existing files), and is
# safe to re-run: existing data (.pano_namer_data) and the environment (.venv)
# are preserved, so re-running updates in place.
#
# Typical use: bootstrap.bat runs
#   irm https://raw.githubusercontent.com/WLDISPATCH/PANOPRO_V2/main/scripts/bootstrap.ps1 | iex

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo = "WLDISPATCH/PANOPRO_V2"
$Branch = "main"
$ZipUrl = "https://github.com/$Repo/archive/refs/heads/$Branch.zip"
$Target = Join-Path $env:LOCALAPPDATA "PANO PRO"

# Never overwritten when updating an existing install.
$Protected = @(
    ".pano_namer_data", ".venv", ".git", ".claude", ".env",
    "build", "dist", "_release", ".test_tmp", "__pycache__", "node_modules"
)

function Copy-Tree($fromRoot, $toRoot) {
    foreach ($item in Get-ChildItem -LiteralPath $fromRoot -Force) {
        if ($Protected -contains $item.Name) { continue }
        $dest = Join-Path $toRoot $item.Name
        if ($item.PSIsContainer) {
            if (-not (Test-Path $dest)) { New-Item -ItemType Directory -Path $dest -Force | Out-Null }
            Copy-Tree $item.FullName $dest
        } else {
            if ($item.Extension -in @(".pyc", ".pyo")) { continue }
            Copy-Item -LiteralPath $item.FullName -Destination $dest -Force
        }
    }
}

Write-Host "PANO PRO bootstrap" -ForegroundColor Green
Write-Host "Installing to: $Target"

$temp = Join-Path ([System.IO.Path]::GetTempPath()) ("panopro_boot_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $temp -Force | Out-Null
try {
    $zipPath = Join-Path $temp "app.zip"
    Write-Host ""
    Write-Host "==> Downloading latest code..." -ForegroundColor Cyan
    Invoke-WebRequest -Uri $ZipUrl -OutFile $zipPath -UseBasicParsing

    Write-Host "==> Extracting..." -ForegroundColor Cyan
    Expand-Archive -LiteralPath $zipPath -DestinationPath $temp -Force
    $extracted = Get-ChildItem -LiteralPath $temp -Directory | Select-Object -First 1
    if (-not $extracted) { throw "Downloaded archive did not contain the expected files." }

    if (-not (Test-Path $Target)) { New-Item -ItemType Directory -Path $Target -Force | Out-Null }
    Write-Host "==> Copying files (existing data is preserved)..." -ForegroundColor Cyan
    Copy-Tree $extracted.FullName $Target
} finally {
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}

# Hand off to the installer that now lives in the target folder.
$installer = Join-Path $Target "scripts\install.ps1"
if (-not (Test-Path $installer)) { throw "Installer not found after download ($installer)." }
Write-Host ""
Write-Host "==> Running installer..." -ForegroundColor Cyan
& $installer
