<#
.SYNOPSIS
  Install the RAG Marking Tool on Windows Server 2019+ or Windows 11 from an
  offline bundle. Run from an elevated PowerShell 5.1+ prompt in the bundle
  folder.

.DESCRIPTION
  - Verifies every bundle file against SHA256SUMS.txt before extracting.
  - Installs embedded Python, PostgreSQL 16 with pgvector, and the app.
  - Runs PostgreSQL and the app as separate virtual service accounts
    (NT SERVICE\RagMT-Postgres, NT SERVICE\RagMT) with no interactive logon.
  - PostgreSQL listens on 127.0.0.1 only with scram-sha-256 authentication.
  - The app connects as a least-privilege role that cannot rewrite audit or
    governance history.
  - Prompts for the first administrator and AO accounts.
#>
param(
  [string]$InstallDir = "$env:ProgramFiles\RagMT",
  [string]$DataDir = "$env:ProgramData\RagMT",
  [Parameter(Mandatory = $true)][ValidateSet("U", "C", "S", "TS", "TS/SCI")][string]$SystemHigh,
  [string]$Bind = "127.0.0.1",
  [int]$Port = 8443,
  [string]$TlsCertPem = "",
  [string]$TlsKeyPem = "",
  [string]$EnclaveCidrs = "",
  [string]$EnclaveHosts = "",
  [string]$CaBundle = "",
  [int]$PgPort = 54329,
  [string]$AdRealm = "",
  [string]$AdNetbios = "",
  [string]$AdSpnHost = "",
  [ValidateSet("tool", "directory")][string]$AdAttributeSource = "tool",
  [string]$AdLdapUrl = "",
  [string]$AdBaseDn = "",
  [string]$AdGroupMapFile = ""
)
$ErrorActionPreference = "Stop"
$bundle = $PSScriptRoot

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)) { throw "Run from an elevated prompt." }
if ([Environment]::OSVersion.Version.Build -lt 17763) { throw "Requires Windows Server 2019 / Windows 10 1809 or newer." }
if ($Bind -ne "127.0.0.1" -and (-not $TlsCertPem -or -not $TlsKeyPem)) {
  throw "Binding to $Bind requires -TlsCertPem and -TlsKeyPem (PEM files)."
}

Write-Host "Verifying bundle integrity"
foreach ($line in Get-Content "$bundle\SHA256SUMS.txt") {
  $hash, $rel = $line -split "  ", 2
  $actual = (Get-FileHash -Algorithm SHA256 (Join-Path $bundle $rel)).Hash.ToLower()
  if ($actual -ne $hash) { throw "Integrity check failed: $rel" }
}

function New-Secret { $b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [Convert]::ToBase64String($b) -replace '[+/=]', 'x' }
function Lock-Path($path, [string[]]$grants) {
  & icacls $path /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
  foreach ($g in $grants) { & icacls $path /grant:r $g | Out-Null }
}

# --- files -----------------------------------------------------------------
New-Item -ItemType Directory -Force $InstallDir, "$InstallDir\app", "$DataDir\pgdata", "$DataDir\logs", "$DataDir\secrets" | Out-Null
Expand-Archive -Force "$bundle\python-embed.zip" "$InstallDir\python"
Expand-Archive -Force "$bundle\postgresql.zip" "$InstallDir"   # creates $InstallDir\pgsql
Copy-Item -Recurse -Force "$bundle\pylib" "$InstallDir\pylib"
Copy-Item -Recurse -Force "$bundle\app\*" "$InstallDir\app\"
Copy-Item -Force "$bundle\winsw.exe" "$InstallDir\RagMT-Service.exe"
Copy-Item -Force "$bundle\pgvector\vector.dll" "$InstallDir\pgsql\lib\"
Copy-Item -Force "$bundle\pgvector\vector.control", "$bundle\pgvector\vector--*.sql" "$InstallDir\pgsql\share\extension\"
Copy-Item -Recurse -Force "$bundle\common" "$InstallDir\common"
# Embedded Python search path: stdlib zip, dependencies, app.
$pth = Get-ChildItem "$InstallDir\python\python*._pth" | Select-Object -First 1
@((Get-Content $pth.FullName | Where-Object { $_ -notmatch '^#?import site' }), "..\pylib", "..\app") |
  Set-Content -Encoding ASCII $pth.FullName

# --- PostgreSQL ------------------------------------------------------------
$pgBin = "$InstallDir\pgsql\bin"
$superPw = New-Secret
$ownerPw = New-Secret
$appPw = New-Secret
$pwFile = "$DataDir\secrets\initdb.tmp"
Set-Content -NoNewline -Encoding ASCII $pwFile $superPw
& "$pgBin\initdb.exe" -D "$DataDir\pgdata" -U postgres --pwfile=$pwFile -A scram-sha-256 -E UTF8 --locale=C
Remove-Item -Force $pwFile
Add-Content "$DataDir\pgdata\postgresql.conf" "`nlisten_addresses = '127.0.0.1'`nport = $PgPort`npassword_encryption = 'scram-sha-256'`nlog_connections = on`nlog_disconnections = on`n"
Set-Content -Encoding ASCII "$DataDir\pgdata\pg_hba.conf" "host all all 127.0.0.1/32 scram-sha-256`n"
& "$pgBin\pg_ctl.exe" register -N "RagMT-Postgres" -D "$DataDir\pgdata" -S auto
& sc.exe config "RagMT-Postgres" obj= "NT SERVICE\RagMT-Postgres" | Out-Null
& icacls "$DataDir\pgdata" /grant "NT SERVICE\RagMT-Postgres:(OI)(CI)M" | Out-Null
Start-Service "RagMT-Postgres"
$env:PGPASSWORD = $superPw
$psql = "$pgBin\psql.exe"
& $psql -h 127.0.0.1 -p $PgPort -U postgres -v ON_ERROR_STOP=1 -c "CREATE ROLE ragmt_owner LOGIN PASSWORD '$ownerPw';" -c "CREATE ROLE ragmt_app LOGIN PASSWORD '$appPw';" `
  -c "CREATE DATABASE ragmt OWNER ragmt_owner;" -c "REVOKE ALL ON DATABASE ragmt FROM PUBLIC;" -c "GRANT CONNECT ON DATABASE ragmt TO ragmt_app;"
& $psql -h 127.0.0.1 -p $PgPort -U postgres -d ragmt -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector;"

# --- schema and least-privilege roles --------------------------------------
$python = "$InstallDir\python\python.exe"
$env:DATABASE_URL = "postgresql+psycopg2://ragmt_owner:$ownerPw@127.0.0.1:$PgPort/ragmt"
& $python -m backend.cli init-db
if ($LASTEXITCODE -ne 0) { throw "schema migration failed" }
$env:PGPASSWORD = $ownerPw
& $psql -h 127.0.0.1 -p $PgPort -U ragmt_owner -d ragmt -v ON_ERROR_STOP=1 -f "$InstallDir\common\roles.sql"
& $python -m backend.cli set-system-high $SystemHigh --actor ("installer:" + $env:USERNAME)
Remove-Item Env:\PGPASSWORD

# Owner and superuser secrets are kept only for upgrades, readable by admins.
Set-Content -Encoding ASCII "$DataDir\secrets\db-admin.txt" "postgres=$superPw`r`nragmt_owner=$ownerPw"
Lock-Path "$DataDir\secrets" @()

# --- first accounts --------------------------------------------------------
Write-Host "`nCreate the first system administrator account."
$u = Read-Host "Admin username"; $n = Read-Host "Admin display name"; $c = Read-Host "Admin clearance (U/C/S/TS/TS/SCI)"; $z = Read-Host "Admin citizenship trigraph"
& $python -m backend.cli create-user --username $u --display-name $n --roles admin --clearance $c --citizenship $z
Write-Host "`nCreate the first Authorizing Official account (must be a different person under the default policy)."
$u = Read-Host "AO username"; $n = Read-Host "AO display name"; $c = Read-Host "AO clearance"; $z = Read-Host "AO citizenship trigraph"
& $python -m backend.cli create-user --username $u --display-name $n --roles ao --clearance $c --citizenship $z

# --- application service ---------------------------------------------------
$envs = [ordered]@{
  DATABASE_URL = "postgresql+psycopg2://ragmt_app:$appPw@127.0.0.1:$PgPort/ragmt"
  VECTOR_STORE = "pgvector"; RAGMT_AUTH_MODE = "production"; RAGMT_BIND = $Bind; RAGMT_PORT = "$Port"
  RAGMT_TLS_CERT = $TlsCertPem; RAGMT_TLS_KEY = $TlsKeyPem; RAGMT_ENCLAVE_CIDRS = $EnclaveCidrs
  RAGMT_ENCLAVE_HOSTS = $EnclaveHosts; RAGMT_CA_BUNDLE = $CaBundle; RAGMT_FRONTEND_DIST = "$InstallDir\app\ui"
}
if ($AdRealm) {
  # SSPI validates tickets as the computer account: register HTTP/$AdSpnHost on it
  # (setspn -S HTTP/<host> <COMPUTER>$), and add the site to browsers' intranet zone.
  $envs["RAGMT_AD_ENABLED"] = "1"; $envs["RAGMT_AD_REALM"] = $AdRealm; $envs["RAGMT_AD_NETBIOS"] = $AdNetbios
  $envs["RAGMT_AD_SPN_HOST"] = $AdSpnHost; $envs["RAGMT_AD_ATTRIBUTE_SOURCE"] = $AdAttributeSource
  $envs["RAGMT_AD_LDAP_URL"] = $AdLdapUrl; $envs["RAGMT_AD_LDAP_BASE_DN"] = $AdBaseDn
  if ($AdGroupMapFile) {
    Copy-Item -Force $AdGroupMapFile "$DataDir\ad-group-map.json"
    & icacls "$DataDir\ad-group-map.json" /inheritance:r /grant:r "*S-1-5-32-544:F" "NT SERVICE\RagMT:R" | Out-Null
    $envs["RAGMT_AD_GROUP_MAP"] = "file:$DataDir\ad-group-map.json"
  }
}
$envXml = ($envs.GetEnumerator() | ForEach-Object { '  <env name="{0}" value="{1}"/>' -f $_.Key, [Security.SecurityElement]::Escape($_.Value) }) -join "`r`n"
@"
<service>
  <id>RagMT</id>
  <name>RAG Marking Tool</name>
  <description>Classification-aware RAG with AI release gate</description>
  <executable>$python</executable>
  <arguments>-m backend.serve</arguments>
  <workingdirectory>$InstallDir\app</workingdirectory>
  <depend>RagMT-Postgres</depend>
  <startmode>Automatic</startmode>
  <onfailure action="restart" delay="10 sec"/>
  <logpath>$DataDir\logs</logpath>
  <log mode="roll-by-size"><sizeThreshold>10240</sizeThreshold><keepFiles>20</keepFiles></log>
  <serviceaccount><username>NT SERVICE\RagMT</username></serviceaccount>
$envXml
</service>
"@ | Set-Content -Encoding UTF8 "$InstallDir\RagMT-Service.xml"
& "$InstallDir\RagMT-Service.exe" install
# The service XML holds the app database password: admins and the service only.
& icacls "$InstallDir\RagMT-Service.xml" /inheritance:r /grant:r "*S-1-5-18:F" "*S-1-5-32-544:F" "NT SERVICE\RagMT:R" | Out-Null
& icacls "$DataDir\logs" /grant "NT SERVICE\RagMT:(OI)(CI)M" | Out-Null
if ($TlsKeyPem) { & icacls $TlsKeyPem /inheritance:r /grant:r "*S-1-5-32-544:F" "NT SERVICE\RagMT:R" | Out-Null }
if ($Bind -ne "127.0.0.1") {
  New-NetFirewallRule -DisplayName "RAG Marking Tool (TCP $Port)" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
}
Start-Service "RagMT"
Write-Host "`nInstalled. Open https://$($Bind):$Port (or http://127.0.0.1:$Port behind a TLS reverse proxy)."
Write-Host "Verify the governance chain any time: `"$python`" -m backend.cli verify-chain (run from $InstallDir\app with DATABASE_URL set)."
