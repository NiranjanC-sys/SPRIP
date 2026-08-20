# Installs a portable Node.js toolchain into .tools/node (no administrator rights required).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$tools = Join-Path $root '.tools'
New-Item -ItemType Directory -Force -Path $tools | Out-Null

Write-Host 'Resolving latest Node.js LTS...'
$index = Invoke-RestMethod -Uri 'https://nodejs.org/dist/index.json' -UseBasicParsing
$lts = $index | Where-Object { $_.lts -ne $false } | Select-Object -First 1
$version = $lts.version
Write-Host "Latest LTS: $version ($($lts.lts))"

$zipName = "node-$version-win-x64.zip"
$zipPath = Join-Path $tools $zipName
$url = "https://nodejs.org/dist/$version/$zipName"

if (-not (Test-Path $zipPath)) {
    Write-Host "Downloading $url"
    Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing
}

$target = Join-Path $tools 'node'
if (Test-Path $target) { Remove-Item -Recurse -Force $target }
Write-Host 'Extracting...'
Expand-Archive -Path $zipPath -DestinationPath $tools -Force
Rename-Item -Path (Join-Path $tools "node-$version-win-x64") -NewName 'node'
Remove-Item $zipPath -Force

$env:PATH = "$target;$env:PATH"
& (Join-Path $target 'node.exe') --version
& (Join-Path $target 'npm.cmd') --version
Write-Host "NODE_OK $target"
