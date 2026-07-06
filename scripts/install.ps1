# PANO PRO one-click installer.
#
# Run by double-clicking install.bat in the repo root. Installs Python 3.13 if
# missing (via winget), creates a local virtual environment, installs all
# dependencies, and drops a "PANO PRO" shortcut on the desktop and Start Menu.
# Safe to re-run: an existing venv is reused.

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot

function Write-Step($message) {
    Write-Host ""
    Write-Host "==> $message" -ForegroundColor Cyan
}

# The app imports datetime.UTC, so 3.11 is the real minimum. Any already
# installed Python at or above this is used as-is; nothing is upgraded.
$MinPython = "(3, 11)"

function Test-PythonVersion($exe) {
    # Returns $true when $exe is a working Python >= the minimum.
    if (-not $exe) { return $false }
    try {
        $ok = & $exe -c "import sys; print(1 if sys.version_info[:2] >= $MinPython else 0)" 2>$null
    } catch {
        return $false
    }
    return ($ok -eq "1")
}

function Resolve-Python {
    # Use whatever suitable Python is already on the machine; do not force a
    # particular version or upgrade. Probe the newest installed 3.x, then
    # python/python3 on PATH, then the default per-user install location.
    $candidates = @()

    try {
        $path = & py -3 -c "import sys; print(sys.executable)" 2>$null
        if ($path) { $candidates += $path.Trim() }
    } catch {}

    foreach ($name in @("python", "python3")) {
        $onPath = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue
        if ($onPath) { $candidates += $onPath }
    }

    $candidates += (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe")

    foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
        if ((Test-Path $candidate) -and (Test-PythonVersion $candidate)) {
            return $candidate
        }
    }
    return $null
}

function Install-Python {
    Write-Step "No suitable Python (3.11+) found. Installing Python 3.13 with winget..."
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget is not available on this machine. Install Python 3.11 or newer from https://www.python.org/downloads/ (check 'Add python.exe to PATH'), then run install.bat again."
    }
    winget install --id Python.Python.3.13 -e --accept-package-agreements --accept-source-agreements --disable-interactivity
    # winget does not refresh this session's PATH, so resolve at the known
    # per-user install location rather than relying on `python` on PATH.
    $installed = Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"
    if ((Test-Path $installed) -and (Test-PythonVersion $installed)) {
        return $installed
    }
    $resolved = Resolve-Python
    if ($resolved) { return $resolved }
    throw "Python was installed but could not be located. Close this window, reopen it, and run install.bat again."
}

function New-BrandIcon($python, $iconPath) {
    # Best-effort: build a branded .ico from the app wordmark. Non-fatal.
    $source = Join-Path $repoRoot "pano_namer\static\brand-wordmark.png"
    if (-not (Test-Path $source)) { return $null }
    $code = @"
from PIL import Image
img = Image.open(r'$source').convert('RGBA')
side = max(img.size)
canvas = Image.new('RGBA', (side, side), (255, 255, 255, 0))
canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2), img)
canvas.save(r'$iconPath', sizes=[(256, 256), (48, 48), (32, 32), (16, 16)])
print('ok')
"@
    try {
        $result = & $python -c $code 2>$null
        if ($result -eq "ok" -and (Test-Path $iconPath)) { return $iconPath }
    } catch {}
    return $null
}

function New-Shortcut($shortcutPath, $target, $arguments, $workDir, $iconPath) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $target
    $shortcut.Arguments = $arguments
    $shortcut.WorkingDirectory = $workDir
    $shortcut.Description = "PANO PRO"
    if ($iconPath -and (Test-Path $iconPath)) {
        $shortcut.IconLocation = $iconPath
    }
    $shortcut.Save()
}

Write-Host "PANO PRO installer" -ForegroundColor Green
Write-Host "Repo: $repoRoot"

# 1. Python
Write-Step "Looking for an existing Python (3.11+)..."
$python = Resolve-Python
if (-not $python) {
    $python = Install-Python
}
Write-Host "Using Python: $python"

# 2. Virtual environment
$venv = Join-Path $repoRoot ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"
$venvPythonw = Join-Path $venv "Scripts\pythonw.exe"
if (Test-Path $venvPython) {
    Write-Step "Reusing existing environment (.venv)."
} else {
    Write-Step "Creating environment (.venv)..."
    & $python -m venv $venv
    if (-not (Test-Path $venvPython)) {
        throw "Failed to create the virtual environment at $venv."
    }
}

# 3. Dependencies (this is the slow step; PySide6 is large)
Write-Step "Installing dependencies (this can take a few minutes)..."
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $repoRoot "requirements.txt")

# 4. Branded icon (best-effort)
Write-Step "Preparing app shortcut..."
$iconPath = New-BrandIcon $venvPython (Join-Path $repoRoot "installer\pano_pro.ico")

# 5. Shortcuts (desktop + Start Menu), launching without a console window
$desktop = [Environment]::GetFolderPath("Desktop")
$startMenu = [Environment]::GetFolderPath("Programs")
New-Shortcut (Join-Path $desktop "PANO PRO.lnk") $venvPythonw "-m pano_namer.desktop" $repoRoot $iconPath
New-Shortcut (Join-Path $startMenu "PANO PRO.lnk") $venvPythonw "-m pano_namer.desktop" $repoRoot $iconPath

Write-Host ""
Write-Host "Done. PANO PRO is installed." -ForegroundColor Green
Write-Host "Launch it from the 'PANO PRO' icon on your desktop."

$launch = Read-Host "Start PANO PRO now? (Y/N)"
if ($launch -match '^[Yy]') {
    Start-Process -FilePath $venvPythonw -ArgumentList "-m", "pano_namer.desktop" -WorkingDirectory $repoRoot
}
