<#
.SYNOPSIS
  Stop and remove the RAG Marking Tool services. Data in $DataDir (database,
  logs, secrets) is preserved for records retention; remove it separately
  under your site's sanitization procedure.
#>
param([string]$InstallDir = "$env:ProgramFiles\RagMT")
$ErrorActionPreference = "Continue"
Stop-Service RagMT, RagMT-Postgres -ErrorAction SilentlyContinue
& "$InstallDir\RagMT-Service.exe" uninstall
& "$InstallDir\pgsql\bin\pg_ctl.exe" unregister -N "RagMT-Postgres"
Get-NetFirewallRule -DisplayName "RAG Marking Tool*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Write-Host "Services removed. Program files remain in $InstallDir and data in $env:ProgramData\RagMT."
