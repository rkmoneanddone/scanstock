import sqlite3
from decimal import Decimal
from pathlib import Path
from scanstock.trading.scanstock_data import load_daily, symbols_with_daily

def test_readonly_daily_adapter(tmp_path):
    path=tmp_path/"test.db"
    conn=sqlite3.connect(path)
    conn.execute("CREATE TABLE candles (symbol TEXT,timeframe TEXT,timestamp TEXT,open REAL,high REAL,low REAL,close REAL,volume INTEGER)")
    conn.execute("INSERT INTO candles VALUES ('ABC','1D','2026-01-01T18:30:00+00:00',10,12,9,11,100)")
    conn.execute("INSERT INTO candles VALUES ('ABC','1D','2026-01-02T18:30:00+00:00',11,13,10,12,150)")
    conn.commit()
    conn.close()
    assert symbols_with_daily(path)==['ABC']
    bars=load_daily(path,'abc')
    assert len(bars)==2 and bars[0].close==Decimal('11')
    assert not (tmp_path/"test.db-wal").exists()
