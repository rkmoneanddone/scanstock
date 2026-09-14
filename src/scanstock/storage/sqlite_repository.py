from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterator, Sequence
from zoneinfo import ZoneInfo

from scanstock.domain import Candle, Instrument


class SQLiteMarketRepository:
    _market_timezone = ZoneInfo("Asia/Kolkata")

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._revision = 0
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA busy_timeout = 5000")

    @contextmanager
    def transaction(self) -> Iterator["SQLiteMarketRepository"]:
        with self._lock:
            try:
                self._connection.execute("BEGIN")
                yield self
                self._connection.commit()
            except BaseException:
                self._connection.rollback()
                raise

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def migrate(self) -> None:
        with self._lock:
            self._connection.executescript("""
        CREATE TABLE IF NOT EXISTS instruments (
            symbol TEXT PRIMARY KEY,
            security_id TEXT NOT NULL,
            display_name TEXT NOT NULL,
            exchange_segment TEXT NOT NULL,
            instrument_type TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS candles (
            symbol TEXT NOT NULL REFERENCES instruments(symbol),
            timeframe TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            open NUMERIC NOT NULL,
            high NUMERIC NOT NULL,
            low NUMERIC NOT NULL,
            close NUMERIC NOT NULL,
            volume INTEGER NOT NULL,
            provider TEXT NOT NULL,
            PRIMARY KEY (symbol, timeframe, timestamp),
            CHECK (high >= low),
            CHECK (open >= low AND open <= high),
            CHECK (close >= low AND close <= high),
            CHECK (volume >= 0)
        );
        CREATE INDEX IF NOT EXISTS ix_candles_tf_time ON candles(timeframe, timestamp);
        CREATE INDEX IF NOT EXISTS ix_candles_tf_symbol_time ON candles(timeframe, symbol, timestamp);
        CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            status TEXT NOT NULL,
            rows_written INTEGER NOT NULL DEFAULT 0,
            message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sync_watermarks (
            symbol TEXT NOT NULL REFERENCES instruments(symbol),
            timeframe TEXT NOT NULL,
            attempted_through TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (symbol, timeframe)
        );
        CREATE TABLE IF NOT EXISTS history_bounds (
            symbol TEXT NOT NULL REFERENCES instruments(symbol),
            timeframe TEXT NOT NULL,
            checked_from TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (symbol, timeframe)
        );
        CREATE TABLE IF NOT EXISTS scan_definitions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            definition_json TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scan_runs (
            id TEXT PRIMARY KEY,
            scan_definition_id TEXT NOT NULL REFERENCES scan_definitions(id),
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scan_matches (
            scan_run_id TEXT NOT NULL REFERENCES scan_runs(id),
            symbol TEXT NOT NULL REFERENCES instruments(symbol),
            candle_timestamp TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            PRIMARY KEY (scan_run_id, symbol)
        );
        CREATE TABLE IF NOT EXISTS latest_metrics (
            symbol TEXT NOT NULL REFERENCES instruments(symbol),
            timeframe TEXT NOT NULL,
            candle_timestamp TEXT NOT NULL,
            open NUMERIC NOT NULL,
            high NUMERIC NOT NULL,
            low NUMERIC NOT NULL,
            close NUMERIC NOT NULL,
            volume INTEGER NOT NULL,
            provider TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (symbol, timeframe)
        );
        CREATE INDEX IF NOT EXISTS ix_latest_metrics_timeframe ON latest_metrics(timeframe, symbol);
        """)
            self._connection.execute("""
                INSERT OR IGNORE INTO history_bounds(symbol,timeframe,checked_from,updated_at)
                SELECT symbol,timeframe,?,MAX(created_at) FROM sync_runs
                WHERE (status='SUCCESS' AND (
                         message='FULL' OR message='BACKFILL'
                         OR message LIKE 'FULL through %' OR message LIKE 'BACKFILL through %'
                       ))
                   OR (status='FAILED' AND message LIKE 'BACKFILL:%DH-907%')
                GROUP BY symbol,timeframe
            """, (date(1990, 1, 1).isoformat(),))
            self._connection.commit()

    def upsert_instruments(self, instruments: Sequence[Instrument]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._connection.executemany("""
            INSERT INTO instruments(symbol, security_id, display_name, exchange_segment, instrument_type, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
              security_id=excluded.security_id, display_name=excluded.display_name,
              exchange_segment=excluded.exchange_segment, instrument_type=excluded.instrument_type,
              active=1, updated_at=excluded.updated_at
        """, [(i.symbol, i.security_id, i.display_name, i.exchange_segment, i.instrument_type, now) for i in instruments])

    def upsert_candles(self, candles: Sequence[Candle]) -> int:
        self._connection.executemany("""
            INSERT INTO candles(symbol,timeframe,timestamp,open,high,low,close,volume,provider)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol,timeframe,timestamp) DO UPDATE SET
              open=excluded.open, high=excluded.high, low=excluded.low,
              close=excluded.close, volume=excluded.volume, provider=excluded.provider
        """, [(c.symbol, c.timeframe, c.timestamp.isoformat(), str(c.open), str(c.high), str(c.low), str(c.close), c.volume, c.provider) for c in candles])
        if candles:
            self._connection.executemany(
                "DELETE FROM latest_metrics WHERE symbol=?",
                [(symbol,) for symbol in sorted({c.symbol for c in candles})],
            )
            self._revision += 1
        return len(candles)

    def data_version(self) -> tuple[int, int]:
        """Changes for this connection plus changes committed by another process."""
        with self._lock:
            external_version = int(self._connection.execute("PRAGMA data_version").fetchone()[0])
            return self._revision, external_version

    def _boundary_candle_date(self, aggregate: str, symbol: str, timeframe: str) -> date | None:
        if aggregate not in {"MIN", "MAX"}:
            raise ValueError("Unsupported boundary aggregate")
        with self._lock:
            row = self._connection.execute(
                f"SELECT {aggregate}(timestamp) FROM candles WHERE symbol=? AND timeframe=?", (symbol, timeframe)
            ).fetchone()
        return datetime.fromisoformat(row[0]).astimezone(self._market_timezone).date() if row and row[0] else None

    def first_candle_date(self, symbol: str, timeframe: str) -> date | None:
        return self._boundary_candle_date("MIN", symbol, timeframe)

    def last_candle_date(self, symbol: str, timeframe: str) -> date | None:
        return self._boundary_candle_date("MAX", symbol, timeframe)

    def last_sync_through(self, symbol: str, timeframe: str) -> date | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT attempted_through FROM sync_watermarks WHERE symbol=? AND timeframe=?", (symbol, timeframe)
            ).fetchone()
        return date.fromisoformat(row[0]) if row else None

    def is_backfill_complete(self, symbol: str, timeframe: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM history_bounds WHERE symbol=? AND timeframe=?", (symbol, timeframe)
            ).fetchone()
        return row is not None

    def mark_backfill_complete(self, symbol: str, timeframe: str, checked_from: date) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._connection.execute("""
            INSERT INTO history_bounds(symbol,timeframe,checked_from,updated_at) VALUES(?,?,?,?)
            ON CONFLICT(symbol,timeframe) DO UPDATE SET
              checked_from=excluded.checked_from, updated_at=excluded.updated_at
        """, (symbol, timeframe, checked_from.isoformat(), now))

    def latest_candles(self, timeframe: str) -> list[Candle]:
        with self._lock:
            rows = self._connection.execute("""
                SELECT c.symbol,c.timeframe,c.timestamp,c.open,c.high,c.low,c.close,c.volume,c.provider
                FROM candles c
                JOIN instruments i ON i.symbol=c.symbol AND i.active=1
                JOIN (
                    SELECT symbol, MAX(timestamp) AS timestamp
                    FROM candles WHERE timeframe=? GROUP BY symbol
                ) latest ON latest.symbol=c.symbol AND latest.timestamp=c.timestamp
                WHERE c.timeframe=? ORDER BY c.symbol
            """, (timeframe, timeframe)).fetchall()
        return [Candle(
            symbol=row[0], timeframe=row[1], timestamp=datetime.fromisoformat(row[2]),
            open=Decimal(str(row[3])), high=Decimal(str(row[4])), low=Decimal(str(row[5])),
            close=Decimal(str(row[6])), volume=int(row[7]), provider=row[8],
        ) for row in rows]

    def candle_series(self, timeframe: str, limit_per_symbol: int | None = None) -> dict[str, list[Candle]]:
        with self._lock:
            if limit_per_symbol is None:
                rows = self._connection.execute("""
                    SELECT c.symbol,c.timeframe,c.timestamp,c.open,c.high,c.low,c.close,c.volume,c.provider
                    FROM candles c JOIN instruments i ON i.symbol=c.symbol AND i.active=1
                    WHERE c.timeframe=? ORDER BY c.symbol,c.timestamp
                """, (timeframe,)).fetchall()
            else:
                rows = self._connection.execute("""
                    SELECT symbol,timeframe,timestamp,open,high,low,close,volume,provider FROM (
                        SELECT c.symbol,c.timeframe,c.timestamp,c.open,c.high,c.low,c.close,c.volume,c.provider,
                               ROW_NUMBER() OVER (PARTITION BY c.symbol ORDER BY c.timestamp DESC) AS position
                        FROM candles c JOIN instruments i ON i.symbol=c.symbol AND i.active=1
                        WHERE c.timeframe=?
                    ) WHERE position<=? ORDER BY symbol,timestamp
                """, (timeframe, limit_per_symbol)).fetchall()
        series: dict[str, list[Candle]] = {}
        for row in rows:
            candle = Candle(
                symbol=row[0], timeframe=row[1], timestamp=datetime.fromisoformat(row[2]),
                open=Decimal(str(row[3])), high=Decimal(str(row[4])), low=Decimal(str(row[5])),
                close=Decimal(str(row[6])), volume=int(row[7]), provider=row[8],
            )
            series.setdefault(candle.symbol, []).append(candle)
        return series

    def candles_for_symbol(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        """Return one active symbol's latest candles in chronological order."""
        with self._lock:
            rows = self._connection.execute("""
                SELECT c.symbol,c.timeframe,c.timestamp,c.open,c.high,c.low,c.close,c.volume,c.provider
                FROM candles c JOIN instruments i ON i.symbol=c.symbol AND i.active=1
                WHERE c.symbol=? AND c.timeframe=?
                ORDER BY c.timestamp DESC LIMIT ?
            """, (symbol.upper(), timeframe, limit)).fetchall()
        return [Candle(
            symbol=row[0], timeframe=row[1], timestamp=datetime.fromisoformat(row[2]),
            open=Decimal(str(row[3])), high=Decimal(str(row[4])), low=Decimal(str(row[5])),
            close=Decimal(str(row[6])), volume=int(row[7]), provider=row[8],
        ) for row in reversed(rows)]

    def loaded_symbol_count(self, timeframe: str) -> int:
        with self._lock:
            return int(self._connection.execute("""
                SELECT COUNT(DISTINCT c.symbol) FROM candles c
                JOIN instruments i ON i.symbol=c.symbol AND i.active=1
                WHERE c.timeframe=?
            """, (timeframe,)).fetchone()[0])

    def metric_snapshots(self, timeframe: str) -> dict[str, tuple[Candle, dict[str, Decimal]]]:
        with self._lock:
            rows = self._connection.execute("""
                SELECT m.symbol,m.candle_timestamp,m.open,m.high,m.low,m.close,m.volume,m.provider,m.metrics_json
                FROM latest_metrics m JOIN instruments i ON i.symbol=m.symbol AND i.active=1
                WHERE m.timeframe=? ORDER BY m.symbol
            """, (timeframe,)).fetchall()
        snapshots = {}
        for row in rows:
            candle = Candle(row[0], timeframe, datetime.fromisoformat(row[1]), Decimal(str(row[2])),
                            Decimal(str(row[3])), Decimal(str(row[4])), Decimal(str(row[5])), int(row[6]), row[7])
            snapshots[row[0]] = (candle, {key: Decimal(value) for key, value in json.loads(row[8]).items()})
        return snapshots

    def save_metric_snapshots(self, timeframe: str, snapshots: Sequence[tuple[Candle, dict[str, Decimal]]]) -> None:
        if not snapshots:
            return
        now = datetime.now(timezone.utc).isoformat()
        rows = [(c.symbol, timeframe, c.timestamp.isoformat(), str(c.open), str(c.high), str(c.low), str(c.close),
                 c.volume, c.provider, json.dumps({key: str(value) for key, value in metrics.items()}, separators=(",", ":")), now)
                for c, metrics in snapshots]
        with self._lock:
            self._connection.executemany("""
                INSERT INTO latest_metrics(symbol,timeframe,candle_timestamp,open,high,low,close,volume,provider,metrics_json,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol,timeframe) DO UPDATE SET
                  candle_timestamp=excluded.candle_timestamp,open=excluded.open,high=excluded.high,
                  low=excluded.low,close=excluded.close,volume=excluded.volume,provider=excluded.provider,
                  metrics_json=excluded.metrics_json,updated_at=excluded.updated_at
            """, rows)
            self._connection.commit()

    def record_sync(self, symbol: str, timeframe: str, status: str, rows: int, message: str = "", attempted_through: date | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._connection.execute(
            "INSERT INTO sync_runs(symbol,timeframe,status,rows_written,message,created_at) VALUES(?,?,?,?,?,?)",
            (symbol, timeframe, status, rows, message, now),
        )
        if status == "SUCCESS" and attempted_through is not None:
            self._connection.execute("""
                INSERT INTO sync_watermarks(symbol,timeframe,attempted_through,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(symbol,timeframe) DO UPDATE SET
                  attempted_through=excluded.attempted_through, updated_at=excluded.updated_at
            """, (symbol, timeframe, attempted_through.isoformat(), now))

    def status_rows(self) -> list[tuple]:
        with self._lock:
            return self._connection.execute("""
                SELECT i.symbol, COUNT(c.timestamp), MIN(c.timestamp), MAX(c.timestamp),
                       w.attempted_through, b.checked_from
                FROM instruments i LEFT JOIN candles c ON c.symbol=i.symbol AND c.timeframe='1D'
                LEFT JOIN sync_watermarks w ON w.symbol=i.symbol AND w.timeframe='1D'
                LEFT JOIN history_bounds b ON b.symbol=i.symbol AND b.timeframe='1D'
                WHERE i.active=1 GROUP BY i.symbol,w.attempted_through,b.checked_from ORDER BY i.symbol
            """).fetchall()
