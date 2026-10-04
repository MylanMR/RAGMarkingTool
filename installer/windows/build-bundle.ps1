<#
.SYNOPSIS
  Stage an offline installation bundle for Windows Server 2019+ / Windows 11.
  Run on an internet-connected build host (PowerShell 5.1+), then move the
  resulting folder across the boundary through your approved transfer process.

.NOTES
  pgvector has no official Windows binaries. Build it once with the Visual
  Studio Build Tools (see README "Building pgvector for Windows") and pass the
  folder holding vector.dll, vector.control and the vector--*.sql files.
#>
param(
  [Parameter(Mandatory = $true)][string]$PgvectorBuildDir,
  [string]$OutDir = ".\ragmt-bundle-windows",
  [string]$PythonVersion = "3.12.7",
  [string]$PostgresZipUrl = "https://get.enterprisedb.com/postgresql/postgresql-16.4-1-windows-x64-binaries.zip",
  [string]$WinSWUrl = "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe"
)
$ErrorActionPreference = "Stop"
$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$OutDir = Resolve-Path $OutDir

function Get-File($url, $dest) {
  Write-Host "Downloading $url"
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
}

Get-File "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" "$OutDir\python-embed.zip"
Get-File $PostgresZipUrl "$OutDir\postgresql.zip"
Get-File $WinSWUrl "$OutDir\winsw.exe"

# Python dependencies, resolved for the target and installed into a folder:
# the target host never needs pip or internet access.
$py = (Get-Command python -ErrorAction Stop).Source
$pyMinor = ($PythonVersion -split '\.')[0..1] -join ''
& $py -m pip install --target "$OutDir\pylib" --platform win_amd64 --python-version $pyMinor `
  --only-binary=:all: --implementation cp -r "$repo\requirements.txt"
if ($LASTEXITCODE -ne 0) { throw "pip staging failed" }
Remove-Item -Recurse -Force "$OutDir\pylib\pytest*", "$OutDir\pylib\_pytest" -ErrorAction SilentlyContinue

# Application code and built UI
Push-Location "$repo\frontend"; npm ci; npm run build; Pop-Location
New-Item -ItemType Directory -Force "$OutDir\app" | Out-Null
Copy-Item -Recurse -Force "$repo\backend" "$OutDir\app\backend"
Copy-Item -Recurse -Force "$repo\frontend\dist" "$OutDir\app\ui"
Copy-Item -Recurse -Force "$repo\installer\common" "$OutDir\common"
Copy-Item -Force "$PSScriptRoot\install.ps1", "$PSScriptRoot\uninstall.ps1" $OutDir
New-Item -ItemType Directory -Force "$OutDir\pgvector" | Out-Null
Copy-Item -Force "$PgvectorBuildDir\vector.dll", "$PgvectorBuildDir\vector.control" "$OutDir\pgvector"
Copy-Item -Force "$PgvectorBuildDir\vector--*.sql" "$OutDir\pgvector"
Get-ChildItem -Recurse "$OutDir\app" -Include "__pycache__" | Remove-Item -Recurse -Force

# Integrity manifest checked by install.ps1 before anything is extracted.
$lines = Get-ChildItem -Recurse -File $OutDir | Where-Object { $_.Name -ne "SHA256SUMS.txt" } | ForEach-Object {
  $rel = $_.FullName.Substring($OutDir.Path.Length + 1)
  "{0}  {1}" -f (Get-FileHash -Algorithm SHA256 $_.FullName).Hash.ToLower(), $rel
}
$lines | Set-Content -Encoding ASCII "$OutDir\SHA256SUMS.txt"
Write-Host "Bundle staged at $OutDir. Record the SHA-256 of SHA256SUMS.txt in your transfer paperwork:"
(Get-FileHash -Algorithm SHA256 "$OutDir\SHA256SUMS.txt").Hash
