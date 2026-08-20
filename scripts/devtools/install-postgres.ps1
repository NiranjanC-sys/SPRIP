<#
.SYNOPSIS
    Install a portable PostgreSQL 16 under .tools/pgsql. No administrator rights,
    no Windows service, no registry keys.

.DESCRIPTION
    The `pgserver` wheel is a tempting shortcut for a no-Docker development
    database, but its build ships no contrib modules - no btree_gist, so the
    effective-dated EXCLUDE constraints that stop overlapping finance assumptions
    cannot be created at all. A development database that silently cannot hold
    the production schema is worse than no development database, so this script
    fetches the same official binaries the production image is built from.

    Everything lands under .tools/, which is gitignored. Removing that directory
    is a complete uninstall.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/devtools/install-postgres.ps1
#>
[CmdletBinding()]
param(
    [string]$Version = '16.9-1',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$tools = Join-Path $root '.tools'
$cache = Join-Path $tools 'cache'
$target = Join-Path $tools 'pgsql'
$zipName = "postgresql-$Version-windows-x64-binaries.zip"
$zipPath = Join-Path $cache $zipName
$url = "https://get.enterprisedb.com/postgresql/$zipName"

$markerExe = Join-Path $target 'bin\initdb.exe'
$markerExt = Join-Path $target 'share\extension\btree_gist.control'

if ((Test-Path $markerExe) -and (Test-Path $markerExt) -and -not $Force) {
    Write-Host "PostgreSQL already installed at $target"
    & (Join-Path $target 'bin\postgres.exe') --version
    exit 0
}

New-Item -ItemType Directory -Force -Path $cache | Out-Null

if (-not (Test-Path $zipPath)) {
    Write-Host "Downloading $url"
    # curl.exe rather than Invoke-WebRequest: the latter goes through the .NET
    # proxy stack, which times out on some corporate configurations where curl
    # and pip work fine.
    & curl.exe -sS -L --retry 3 --max-time 1800 -o $zipPath $url
    if ($LASTEXITCODE -ne 0) { throw "download failed (curl exit $LASTEXITCODE)" }
}

$size = (Get-Item $zipPath).Length
if ($size -lt 100MB) { throw "downloaded archive is only $size bytes; delete $zipPath and retry" }

if (Test-Path $target) { Remove-Item -Recurse -Force $target }
Write-Host "Extracting to $target (this takes a minute)"
$staging = Join-Path $tools 'pgsql-staging'
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
# ExtractToDirectory rather than Expand-Archive: the cmdlet pushes every entry
# through the PowerShell pipeline, which on a 300 MB / 4,000-file archive costs
# minutes. The .NET call does the same work in seconds.
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::ExtractToDirectory($zipPath, $staging)

# The archive contains a single top-level `pgsql/` directory.
$inner = Join-Path $staging 'pgsql'
if (Test-Path $inner) { Move-Item $inner $target } else { Move-Item $staging $target }
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }

foreach ($marker in @($markerExe, $markerExt)) {
    if (-not (Test-Path $marker)) { throw "install looks incomplete: missing $marker" }
}

& (Join-Path $target 'bin\postgres.exe') --version
Write-Host "Installed. Next: python scripts/devtools/pg.py start"
