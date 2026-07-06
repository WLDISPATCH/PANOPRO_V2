# PANO PRO one-click updater.
#
# Downloads the latest code from GitHub and re-installs dependencies into the
# existing .venv, WITHOUT touching your data (.pano_namer_data) or environment.
# Close the app before running. Re-runnable and safe.
#
# Works two ways:
#   - as a local file: scripts\update.ps1 updates the repo it lives in
#   - fetched remotely: a copied-in update.bat sets $env:PANOPRO_UPDATE_DIR to
#     the folder to update and runs `irm .../update.ps1 | iex`
# Set $env:PANOPRO_UPDATE_FORCE = "1" to reinstall even when already current.

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# --- Where updates come from (public repo, no auth needed) ---
$Repo = "WLDISPATCH/PANOPRO_V2"
$Branch = "main"
$VersionUrl = "https://raw.githubusercontent.com/$Repo/$Branch/pano_namer/__init__.py"
$ZipUrl = "https://github.com/$Repo/archive/refs/heads/$Branch.zip"

# Directories/files never overwritten by an update (user data + local setup).
$Protected = @(
    ".pano_namer_data", ".venv", ".git", ".claude", ".env",
    "build", "dist", "_release", ".test_tmp", "__pycache__", "node_modules"
)

$Force = ($env:PANOPRO_UPDATE_FORCE -eq "1")

# Which folder to update: an explicit env var (set by a copied-in update.bat)
# wins; otherwise the repo this script file lives in; otherwise the current dir.
if ($env:PANOPRO_UPDATE_DIR) {
    $repoRoot = $env:PANOPRO_UPDATE_DIR.TrimEnd("\")
} elseif ($MyInvocation.MyCommand.Path) {
    $repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
} else {
    $repoRoot = (Get-Location).Path
}

# Guard: this is an updater for an existing install, not a fresh installer.
if (-not (Test-Path (Join-Path $repoRoot "pano_namer"))) {
    throw "This does not look like a PANO PRO folder ($repoRoot). Copy update.bat into an existing PANO PRO folder, or use install.bat / bootstrap.bat for a fresh setup."
}

function Write-Step($message) {
    Write-Host ""
    Write-Host "==> $message" -ForegroundColor Cyan
}

function Get-VersionFrom($text) {
    $m = [regex]::Match($text, '__version__\s*=\s*"([^"]+)"')
    if ($m.Success) { return $m.Groups[1].Value }
    return $null
}

function Copy-Tree($fromRoot, $toRoot) {
    foreach ($item in Get-ChildItem -LiteralPath $fromRoot -Force) {
        if ($Protected -contains $item.Name) { continue }
        $target = Join-Path $toRoot $item.Name
        if ($item.PSIsContainer) {
            if (-not (Test-Path $target)) { New-Item -ItemType Directory -Path $target -Force | Out-Null }
            Copy-Tree $item.FullName $target
        } else {
            if ($item.Extension -in @(".pyc", ".pyo")) { continue }
            Copy-Item -LiteralPath $item.FullName -Destination $target -Force
        }
    }
}

Write-Host "PANO PRO updater" -ForegroundColor Green
Write-Host "Repo: $repoRoot"

# 1. Compare versions (cheap) before downloading the full archive.
$localInit = Join-Path $repoRoot "pano_namer\__init__.py"
$localVersion = if (Test-Path $localInit) { Get-VersionFrom (Get-Content -Raw $localInit) } else { "unknown" }
Write-Step "Checking for updates (current v$localVersion)..."
$remoteVersion = $null
try {
    $remoteInit = (Invoke-WebRequest -Uri $VersionUrl -UseBasicParsing).Content
    $remoteVersion = Get-VersionFrom $remoteInit
} catch {
    throw "Could not reach GitHub to check for updates. Check the internet connection and try again."
}
Write-Host "Latest available: v$remoteVersion"

if ($remoteVersion -and ($remoteVersion -eq $localVersion) -and -not $Force) {
    Write-Host ""
    Write-Host "Already up to date (v$localVersion). Nothing to do." -ForegroundColor Green
    Write-Host "(Run with -Force to reinstall anyway.)"
    return
}

# 2. Download + extract the latest code to a temp area.
$temp = Join-Path ([System.IO.Path]::GetTempPath()) ("panopro_update_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $temp -Force | Out-Null
try {
    $zipPath = Join-Path $temp "latest.zip"
    Write-Step "Downloading latest code..."
    Invoke-WebRequest -Uri $ZipUrl -OutFile $zipPath -UseBasicParsing

    Write-Step "Extracting..."
    Expand-Archive -LiteralPath $zipPath -DestinationPath $temp -Force
    # GitHub archives extract to a single top-level folder (e.g. REPO-main).
    $extractedRoot = Get-ChildItem -LiteralPath $temp -Directory | Select-Object -First 1
    if (-not $extractedRoot) { throw "Downloaded archive did not contain the expected files." }

    # 3. Copy the new code over the app, preserving protected data.
    Write-Step "Applying update (your data and settings are preserved)..."
    Copy-Tree $extractedRoot.FullName $repoRoot

    # 4. Refresh dependencies in the existing venv (fast if unchanged).
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        Write-Step "Updating dependencies..."
        & $venvPython -m pip install -r (Join-Path $repoRoot "requirements.txt")
    } else {
        Write-Host "No .venv found - run install.bat once to finish setup." -ForegroundColor Yellow
    }

    $newVersion = Get-VersionFrom (Get-Content -Raw $localInit)
    Write-Host ""
    Write-Host "Updated: v$localVersion -> v$newVersion" -ForegroundColor Green
    Write-Host "Relaunch PANO PRO from the desktop icon."
} finally {
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
