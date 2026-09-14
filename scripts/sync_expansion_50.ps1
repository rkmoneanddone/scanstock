$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$symbols = @(
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "VEDL",
    "BEL", "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT",
    "ETERNAL", "GRASIM", "HCLTECH", "HEROMOTOCO", "INDUSINDBK",
    "JSWSTEEL", "NESTLEIND", "ONGC", "SHRIRAMFIN", "TATACONSUM",
    "TATAMOTORS", "TATASTEEL", "TECHM", "TRENT", "WIPRO",
    "ABB", "ADANIGREEN", "AMBUJACEM", "BANKBARODA", "BPCL",
    "BRITANNIA", "CANBK", "CGPOWER", "CHOLAFIN", "DABUR",
    "DIVISLAB", "DLF", "GAIL", "GODREJCP", "HAL",
    "HAVELLS", "IOC", "IRCTC", "JINDALSTEL", "LICI",
    "LUPIN", "MANKIND", "NAUKRI", "PIDILITIND", "PNB"
)

& ".\.venv\Scripts\scanstock.exe" init-db
& ".\.venv\Scripts\scanstock.exe" sync-daily --symbols $symbols
& ".\.venv\Scripts\scanstock.exe" status
