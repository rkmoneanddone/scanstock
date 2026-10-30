"""Auditable forward-outcome learning from completed OHLC bars; no order authority."""
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
import json
from pathlib import Path

D=lambda v:Decimal(str(v))
@dataclass(frozen=True)
class Bar:
    timestamp:str
    open:Decimal
    high:Decimal
    low:Decimal
    close:Decimal
    volume:int=0

def validate_bars(bars):
    previous=None
    for b in bars:
        t=datetime.fromisoformat(b.timestamp.replace("Z","+00:00"))
        if previous is not None and t<=previous:raise ValueError("Bars must be strictly chronological")
        previous=t
        if not all(v.is_finite() and v>0 for v in (b.open,b.high,b.low,b.close)):
            raise ValueError("Invalid OHLC")
        if b.high<max(b.open,b.close,b.low) or b.low>min(b.open,b.close,b.high):
            raise ValueError("Inconsistent OHLC")
        if b.volume<0:raise ValueError("Negative volume")

def evaluate_setup(symbol,setup,signal_index,bars,entry,stop,target,horizon=5):
    """Evaluate AFTER signal bar; if SL and TP hit in same bar, assume SL first."""
    validate_bars(bars)
    if not (0<=signal_index<len(bars)-1):raise ValueError("Signal requires future bars")
    entry,stop,target=map(D,(entry,stop,target))
    if not (0<stop<entry<target):raise ValueError("Long-only setup requires SL < entry < TP")
    if horizon<1:raise ValueError("Horizon must be positive")
    future=bars[signal_index+1:signal_index+1+horizon]
    outcome="UNRESOLVED";exit_price=None;exit_at=None
    for b in future:
        if b.open<=stop:
            outcome="STOP_GAP";exit_price=b.open;exit_at=b.timestamp;break
        if b.open>=target:
            outcome="TARGET_GAP";exit_price=b.open;exit_at=b.timestamp;break
        if b.low<=stop:
            outcome="STOP";exit_price=stop;exit_at=b.timestamp;break
        if b.high>=target:
            outcome="TARGET";exit_price=target;exit_at=b.timestamp;break
    complete=len(future)>=horizon or exit_price is not None
    if complete and exit_price is None:
        outcome="TIMEOUT";exit_price=future[-1].close;exit_at=future[-1].timestamp
    risk=entry-stop
    return dict(symbol=symbol,setup=setup,signal_at=bars[signal_index].timestamp,
                entry=str(entry),stop=str(stop),target=str(target),horizon=horizon,
                outcome=outcome,complete=complete,exit_at=exit_at,
                exit_price=str(exit_price) if exit_price is not None else None,
                r_multiple=str((exit_price-entry)/risk) if exit_price is not None else None,
                bars_evaluated=len(future),conservative_same_bar_stop_first=True)

def summarize(records):
    complete=[r for r in records if r["complete"]]
    wins=[r for r in complete if D(r["r_multiple"])>0]
    return dict(total=len(records),complete=len(complete),pending=len(records)-len(complete),
                wins=len(wins),win_rate=str(D(len(wins))/len(complete)*100) if complete else None,
                mean_r=str(sum((D(r["r_multiple"]) for r in complete),D(0))/len(complete)) if complete else None)

def append_record(path,record):
    """Append-only JSONL evidence; callers must serialize concurrent writes."""
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("a",encoding="utf-8") as f:
        f.write(json.dumps(record,sort_keys=True)+"\n")
        f.flush()
        import os
        os.fsync(f.fileno())
