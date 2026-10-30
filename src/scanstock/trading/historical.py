"""Historical 1D setup detection and chronological forward evaluation. No order execution."""
import argparse
import json
from pathlib import Path
from decimal import Decimal
from .learning import Bar, D, evaluate_setup, summarize, append_record, validate_bars

def load_parquet(path):
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("Install pandas and pyarrow to read parquet") from exc
    df=pd.read_parquet(path)
    names={str(c).lower():c for c in df.columns}
    date_col=next((names[k] for k in ("decision_timestamp","timestamp","datetime","date","time") if k in names),None)
    if date_col is None:
        if not isinstance(df.index,pd.DatetimeIndex):raise ValueError("OHLC parquet needs datetime index or date column")
        times=df.index
    else:times=pd.to_datetime(df[date_col],utc=True)
    required=("open","high","low","close")
    if any(k not in names for k in required):raise ValueError("Missing OHLC columns")
    volume=names.get("volume")
    bars=[]
    for i,(_,row) in enumerate(df.iterrows()):
        values=[row[names[k]] for k in required]
        if any(pd.isna(v) for v in values):continue
        stamp=times[i].isoformat()
        bars.append(Bar(stamp,*[D(v) for v in values],int(row[volume]) if volume and pd.notna(row[volume]) else 0))
    validate_bars(bars)
    return bars

def detect_setups(symbol,bars,lookback=20,horizon=5):
    """Strict prior-high breakout on completed daily close; first breakout only.
    Entry at next open, stop at signal low; no future bar enters detection.
    """
    if lookback<2 or horizon<1:raise ValueError("Invalid parameters")
    validate_bars(bars)
    records=[]
    for i in range(lookback+1,len(bars)-1):
        prior_high=max(b.high for b in bars[i-lookback:i])
        prev_high=max(b.high for b in bars[i-lookback-1:i-1])
        b=bars[i]
        if not (b.close>prior_high and bars[i-1].close<=prev_high):continue
        next_open=bars[i+1].open
        stop=b.low
        event=dict(symbol=symbol,setup="PRIOR_HIGH_BREAKOUT_1D",signal_at=b.timestamp,
                   entry_at=bars[i+1].timestamp,entry=str(next_open),stop=str(stop))
        if next_open<=stop:
            event.update(status="SKIPPED",reason="NEXT_OPEN_AT_OR_BELOW_STOP")
        elif next_open>stop*D("1.10"):
            event.update(status="SKIPPED",reason="ENTRY_GAP_GT_10PCT_STOP_DISTANCE")
        else:
            target=next_open+2*(next_open-stop)
            event.update(status="ELIGIBLE",target=str(target))
            if i+1>=len(bars):
                event.update(status="PENDING",reason="NO_POST_ENTRY_BARS")
            else:
                # Entry occurs at next open; evaluate that entry candle and later bars.
                result=evaluate_setup(symbol,event["setup"],i,bars,next_open,stop,target,horizon)
                event.update(result)
                event["status"]="COMPLETE" if result["complete"] else "PENDING"
        records.append(event)
    return records

def walkforward(records,split_at):
    """Split by signal time; no parameters fitted on evaluation period."""
    train=[r for r in records if r["signal_at"]<split_at and r["status"]=="COMPLETE" and r.get("exit_at","")<split_at]
    test=[r for r in records if r["signal_at"]>=split_at and r["status"]=="COMPLETE"]
    return dict(split_at=split_at,train=summarize(train),unseen=summarize(test),
                skipped=sum(r["status"]=="SKIPPED" for r in records),
                pending=sum(r["status"]=="PENDING" for r in records))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--parquet",required=True)
    p.add_argument("--symbol",required=True)
    p.add_argument("--split-at",required=True,help="ISO date YYYY-MM-DD")
    p.add_argument("--lookback",type=int,default=20)
    p.add_argument("--horizon",type=int,default=5)
    p.add_argument("--output",default="data/autotrader/learning_evidence.jsonl")
    args=p.parse_args()
    bars=load_parquet(args.parquet)
    records=detect_setups(args.symbol,bars,args.lookback,args.horizon)
    report=walkforward(records,args.split_at)
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    # Replace complete snapshot atomically, so repeated runs do not double-count.
    tmp=out.with_suffix(out.suffix+".tmp")
    with tmp.open("w",encoding="utf-8") as f:
        for record in records:f.write(json.dumps(record,sort_keys=True)+"\n")
    tmp.replace(out)
    print(json.dumps(report,indent=2))
if __name__=="__main__":main()
