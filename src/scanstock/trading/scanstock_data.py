"""Read ScanStock OHLC data without modifying the production SQLite database."""
import sqlite3
from decimal import Decimal
from pathlib import Path
from .learning import Bar, validate_bars

def load_daily(db_path, symbol):
    path = Path(db_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
    try:
        conn.execute("PRAGMA query_only=ON")
        rows = conn.execute(
            "SELECT timestamp, open, high, low, close, volume FROM candles "
            "WHERE symbol=? AND timeframe='1D' ORDER BY timestamp", (symbol.upper(),)
        ).fetchall()
    finally:
        conn.close()
    bars = [Bar(str(t), *(Decimal(str(x)) for x in (o,h,l,c)), int(v))
            for t,o,h,l,c,v in rows]
    validate_bars(bars)
    return bars

def symbols_with_daily(db_path):
    path = Path(db_path).resolve()
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
    try:
        conn.execute("PRAGMA query_only=ON")
        return [r[0] for r in conn.execute(
            "SELECT DISTINCT symbol FROM candles WHERE timeframe='1D' ORDER BY symbol")]
    finally:
        conn.close()
