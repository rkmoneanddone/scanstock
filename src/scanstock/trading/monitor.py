"""Paper-only continuous quote monitor with replay, safety and observability.

No broker calls. Demo strategy is opt-in; default is observation-only.
"""
import csv
import json
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from .engine import AutoTrader
from .hard_checks import HardCheckRejected

@dataclass(frozen=True)
class Quote:
    symbol: str
    price: Decimal
    volume: int | None = None
    oi: int | None = None
    timestamp: str | None = None

class PaperMonitor:
    def __init__(self, engine: AutoTrader, *, demo_signals=False, max_age_seconds=120):
        self.engine=engine
        self.demo_signals=demo_signals
        self.max_age_seconds=max_age_seconds
        self.latest={}
        self.events=deque(maxlen=100)
        self.errors=0
        self.stopped=False

    def ingest(self, quote: Quote):
        if self.stopped:
            raise RuntimeError("Monitor halted")
        if quote.symbol not in self.engine.watchlist:
            raise HardCheckRejected("Symbol outside active watchlist")
        price=Decimal(str(quote.price))
        if not price.is_finite() or price<=0:
            raise ValueError("Invalid market price")
        if quote.volume is not None and quote.volume<0:
            raise ValueError("Negative volume")
        if quote.oi is not None and quote.oi<0:
            raise ValueError("Negative open interest")
        now=datetime.now(timezone.utc)
        if quote.timestamp is not None:
            stamp=datetime.fromisoformat(quote.timestamp.replace("Z","+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("Quote timestamp must be timezone aware")
            if abs((now-stamp).total_seconds())>self.max_age_seconds:
                raise HardCheckRejected("Stale or future quote rejected")
        self.latest[quote.symbol]=dict(price=str(price),volume=quote.volume,oi=quote.oi,
                                      updated_at=now.isoformat())
        # Protective SL/TP exits are evaluated even with demonstration signals off.
        if self.demo_signals:
            result=self.engine.on_quote(quote.symbol,price,quote.volume,quote.oi)
        elif quote.symbol in self.engine.positions:
            p=self.engine.positions[quote.symbol]
            if price<=Decimal(p["stop"]):
                result=self.engine.sell(quote.symbol,price,"STOP_LOSS")
            elif price>=Decimal(p["target"]):
                result=self.engine.sell(quote.symbol,price,"TAKE_PROFIT")
            else:
                result=None
        else:
            result=None
        self.engine.last[quote.symbol]=price
        if result is not None:
            self.events.append(dict(symbol=quote.symbol,event=result,at=now.isoformat()))
        return result

    def run(self, source, *, interval_seconds=0, max_quotes=None):
        if interval_seconds<0:
            raise ValueError("Negative interval")
        processed=0
        for quote in source:
            if self.stopped or (max_quotes is not None and processed>=max_quotes):
                break
            try:
                self.ingest(quote)
            except (ValueError,HardCheckRejected) as exc:
                self.errors+=1
                self.events.append(dict(error=str(exc),symbol=quote.symbol))
            processed+=1
            if interval_seconds:
                time.sleep(interval_seconds)
        return self.status()

    def status(self):
        return dict(mode="PAPER",demo_signals=self.demo_signals,watchlist=list(self.engine.watchlist),
                    quotes=self.latest,positions=self.engine.positions,cash=str(self.engine.cash),
                    entries_today=self.engine.entries,errors=self.errors,
                    recent_events=list(self.events),daily=self.engine.report("daily"),
                    weekly=self.engine.report("weekly"))

    def stop(self):
        self.stopped=True

def csv_replay(path, symbols):
    """CSV rows: symbol,price,volume,oi. Timestamp omitted for historical replay."""
    with Path(path).open(newline="",encoding="utf-8-sig") as handle:
        reader=csv.DictReader(handle)
        if not reader.fieldnames or not {"symbol","price"}.issubset(reader.fieldnames):
            raise ValueError("CSV requires symbol,price columns")
        for row in reader:
            if row["symbol"] not in symbols:
                continue
            yield Quote(row["symbol"],Decimal(row["price"]),
                        int(row["volume"]) if row.get("volume") else None,
                        int(row["oi"]) if row.get("oi") else None)

def save_status(monitor,path):
    target=Path(path)
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_suffix(".tmp")
    temporary.write_text(json.dumps(monitor.status(),indent=2),encoding="utf8")
    temporary.replace(target)
