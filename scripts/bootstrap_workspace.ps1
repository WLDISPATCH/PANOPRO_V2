param(
    [string]$TargetName = "PanoPro v2",
    [string]$Version = "2.4.1-dev",
    [switch]$IncludeData,
    [switch]$NoData,
    [switch]$Overwrite,
    [string]$SourceRoot,
    [string]$DestinationRoot
)

$ErrorActionPreference = "Stop"

function Resolve-NormalizedPath {
    param([Parameter(Mandatory = $true)][string]$PathValue)
    return [System.IO.Path]::GetFullPath($PathValue)
}

function Copy-WorkspaceTree {
    param(
        [Parameter(Mandatory = $true)][string]$FromRoot,
        [Parameter(Mandatory = $true)][string]$ToRoot,
        [Parameter(Mandatory = $true)][bool]$CopyData
    )

    $skipDirectoryNames = @("build", "dist", ".test_tmp", "__pycache__")
    if (-not $CopyData) {
        $skipDirectoryNames += ".pano_namer_data"
    }

    $fromRoot = Resolve-NormalizedPath $FromRoot
    $items = Get-ChildItem -LiteralPath $fromRoot -Force
    foreach ($item in $items) {
        if ($skipDirectoryNames -contains $item.Name) {
            continue
        }

        $targetPath = Join-Path $ToRoot $item.Name
        if ($item.PSIsContainer) {
            New-Item -ItemType Directory -Path $targetPath -Force | Out-Null
            Copy-WorkspaceTree -FromRoot $item.FullName -ToRoot $targetPath -CopyData $CopyData
            continue
        }

        if ($item.Extension -in @(".pyc", ".pyo")) {
            continue
        }

        Copy-Item -LiteralPath $item.FullName -Destination $targetPath -Force
    }
}

function Update-VersionMarkers {
    param(
        [Parameter(Mandatory = $true)][string]$WorkspaceRoot,
        [Parameter(Mandatory = $true)][string]$TargetVersion
    )

    $versionFile = Join-Path $WorkspaceRoot "pano_namer\__init__.py"
    $versionContent = Get-Content -LiteralPath $versionFile -Raw
    $versionContent = [regex]::Replace($versionContent, '__version__\s*=\s*"[^"]+"', "__version__ = `"$TargetVersion`"")
    Set-Content -LiteralPath $versionFile -Value $versionContent -NoNewline

    $installerFile = Join-Path $WorkspaceRoot "installer\PANO-PRO.iss"
    if (Test-Path $installerFile) {
        $installerContent = Get-Content -LiteralPath $installerFile -Raw
        $installerContent = [regex]::Replace($installerContent, '#define AppVersion "[^"]+"', "#define AppVersion `"$TargetVersion`"")
        Set-Content -LiteralPath $installerFile -Value $installerContent -NoNewline
    }

    $readmeFile = Join-Path $WorkspaceRoot "README.md"
    if (Test-Path $readmeFile) {
        $readmeContent = Get-Content -LiteralPath $readmeFile -Raw
        $readmeContent = [regex]::Replace($readmeContent, 'PANO-PRO-v[^\\/\s`"]+-windows\.zip', "PANO-PRO-v$TargetVersion-windows.zip")
        $readmeContent = [regex]::Replace($readmeContent, 'PANO-PRO-Setup-[^\\/\s`"]+\.exe', "PANO-PRO-Setup-$TargetVersion.exe")
        $readmeContent = [regex]::Replace($readmeContent, '-Version "[^"]+"', "-Version `"$TargetVersion`"")
        Set-Content -LiteralPath $readmeFile -Value $readmeContent -NoNewline
    }
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-NormalizedPath ((Split-Path -Parent $scriptRoot))
$sourceRootResolved = Resolve-NormalizedPath ($(if ($SourceRoot) { $SourceRoot } else { $projectRoot }))
$destinationRootResolved = Resolve-NormalizedPath ($(if ($DestinationRoot) { $DestinationRoot } else { Split-Path -Parent $sourceRootResolved }))
$targetRoot = Join-Path $destinationRootResolved $TargetName
$copyData = $true
if ($NoData) {
    $copyData = $false
}
if ($IncludeData) {
    $copyData = $true
}

if (-not (Test-Path $sourceRootResolved)) {
    throw "Source root '$sourceRootResolved' was not found."
}

if ((Resolve-NormalizedPath $targetRoot) -eq $sourceRootResolved) {
    throw "Target workspace cannot be the same as the source workspace."
}

if (Test-Path $targetRoot) {
    if (-not $Overwrite) {
        throw "Target workspace '$targetRoot' already exists. Use -Overwrite to replace it."
    }
    Remove-Item -LiteralPath $targetRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null
Copy-WorkspaceTree -FromRoot $sourceRootResolved -ToRoot $targetRoot -CopyData $copyData
Update-VersionMarkers -WorkspaceRoot $targetRoot -TargetVersion $Version

Write-Host "Created workspace:" $targetRoot
Write-Host "Version:" $Version
Write-Host "Included data:" $copyData
