$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
$url = "http://127.0.0.1:8765"
Start-Job -ScriptBlock {
    param($browserUrl)
    Start-Sleep -Seconds 2
    Start-Process $browserUrl
} -ArgumentList $url | Out-Null
& ".\.venv\Scripts\scanstock.exe" serve --host 127.0.0.1 --port 8765
