$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

& ".\.venv\Scripts\scanstock.exe" init-db
& ".\.venv\Scripts\scanstock.exe" sync-batches --batch-size 100 --batch-pause-seconds 600
