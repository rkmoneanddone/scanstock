$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$symbols = @(
    "AARTIIND", "ABCAPITAL", "ABFRL", "ACC", "APLAPOLLO",
    "AUBANK", "AUROPHARMA", "BALKRISIND", "BANDHANBNK", "BATAINDIA",
    "BHEL", "BIOCON", "BOSCHLTD", "BSE", "CAMS",
    "CESC", "COLPAL", "CONCOR", "CROMPTON", "CUMMINSIND",
    "DELHIVERY", "DMART", "ESCORTS", "EXIDEIND", "FEDERALBNK",
    "FORTIS", "GLENMARK", "GMRAIRPORT", "GNFC", "HDFCAMC",
    "HDFCLIFE", "HINDPETRO", "HUDCO", "ICICIGI", "ICICIPRULI",
    "IDFCFIRSTB", "IEX", "IGL", "INDHOTEL", "INDIGO",
    "INDUSTOWER", "IRB", "IRFC", "JIOFIN", "JUBLFOOD",
    "KPITTECH", "LAURUSLABS", "LODHA", "LTIM", "LTF",
    "MARICO", "MAXHEALTH", "MAZDOCK", "MFSL", "MOTHERSON",
    "MPHASIS", "MRPL", "MUTHOOTFIN", "NATIONALUM", "NHPC",
    "NMDC", "OBEROIRLTY", "OFSS", "OIL", "PAGEIND",
    "PATANJALI", "PAYTM", "PERSISTENT", "PETRONET", "PHOENIXLTD",
    "POLYCAB", "PRESTIGE", "RECLTD", "RVNL", "SAIL",
    "SBICARD", "SBILIFE", "SHREECEM", "SIEMENS", "SOLARINDS",
    "SONACOMS", "SUPREMEIND", "SUZLON", "TATACHEM", "TATACOMM",
    "TATAELXSI", "TATAPOWER", "TORNTPHARM", "TORNTPOWER", "TVSMOTOR",
    "UBL", "UNIONBANK", "UNITDSPR", "UPL", "VBL",
    "VOLTAS", "YESBANK", "ZYDUSLIFE", "KALYANKJIL", "KEI"
)

& ".\\.venv\\Scripts\\scanstock.exe" init-db
# Refresh all existing and new instruments through the current attempted date.
& ".\\.venv\\Scripts\\scanstock.exe" sync-daily
# Explicit retry of the 100-stock expansion remains safe and progressive.
& ".\\.venv\\Scripts\\scanstock.exe" sync-daily --symbols $symbols
& ".\\.venv\\Scripts\\scanstock.exe" status
