$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
& ".\.venv\Scripts\scanstock.exe" sync-daily
& ".\.venv\Scripts\scanstock.exe" status

