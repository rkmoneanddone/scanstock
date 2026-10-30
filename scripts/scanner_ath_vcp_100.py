"""Research-only 100-stock historical ATH-retest and VCP validation.

Reuses ScanStock's production scanner functions, not rewritten approximations.
No brokerage, order or paper-engine integration.
"""
import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from statistics import fmean

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from scanstock.domain import Candle
from scanstock.scanner import add_ath_interaction_metrics, add_vcp_metrics
from scanstock.trading.scanstock_data import load_daily, symbols_with_daily
from scanstock.trading.historical import walkforward
from scanstock.trading.research_report import aggregate_symbol_reports
from scanstock.trading.learning import D, evaluate_setup

RULES = {
    "SCANSTOCK_ATH_RETEST": "Exact add_ath_interaction_metrics scanner; 5+ closes above old ATH, 5% advance, current retest and SMA50 support",
    "SCANSTOCK_VCP_BREAKOUT": "Exact add_vcp_metrics scanner; three contractions, <=25%/15% range, prior 60-high pivot, 1.5x volume, SMA50 trend",
}

def detect(bars, symbol):
    candles = [
        Candle(symbol, "1D", datetime.fromisoformat(b.timestamp.replace("Z","+00:00")),
               b.open,b.high,b.low,b.close,b.volume,"local")
        for b in bars
    ]
    found = {name:[] for name in RULES}
    # Historical prior-ATH baseline is the maximum high BEFORE the window starts.
    # Never use the final/current full-history ATH for earlier signals.
    running_max = []
    peak = Decimal(0)
    for c in candles:
        running_max.append(peak)
        peak = max(peak,c.high)
    closes = [float(c.close) for c in candles]
    for i in range(200,len(candles)-1):
        window = candles[max(0,i-61):i+1]
        metrics = {"sma50":D(fmean(closes[i-49:i+1]))}
        add_vcp_metrics(window,metrics)
        if metrics["vcp_breakout"] == 1:
            found["SCANSTOCK_VCP_BREAKOUT"].append(i)
        # 62-candle historical window matches the existing latest-candle scanner.
        # The first candle's own high is included in the rolling baseline by production logic.
        window_start = max(0,i-61)
        historical_baseline = running_max[window_start]
        prior_ath = running_max[i]
        previous_ath = running_max[i-1]
        add_ath_interaction_metrics(window,metrics,prior_ath,previous_ath,historical_baseline)
        if metrics["ath_breakout_retest"] == 1:
            found["SCANSTOCK_ATH_RETEST"].append(i)
    return found

def evaluate(symbol,bars,indices,horizon,fee_bps):
    events=[]
    next_eligible=0
    for i in indices:
        if i < next_eligible:
            continue  # no overlapping entries in the same stock/setup
        entry=bars[i+1].open
        stop=bars[i].low
        event={"symbol":symbol,"signal_at":bars[i].timestamp,"status":"SKIPPED"}
        if stop<=0 or entry<=stop:
            events.append(event);continue
        target=entry+2*(entry-stop)
        outcome=evaluate_setup(symbol,"SCANNER_PILOT",i,bars,entry,stop,target,horizon)
        event.update(outcome)
        event["status"]="COMPLETE" if outcome["complete"] else "PENDING"
        if outcome["complete"]:
            exit_price=D(outcome["exit_price"])
            event["r_multiple"]=str((exit_price-entry-(entry+exit_price)*D(fee_bps)/D(10000))/(entry-stop))
            # Conservative lockout through exit bar, preventing overlapping positions.
            exit_time=outcome["exit_at"]
            next_eligible=next((j+1 for j in range(i+1,min(len(bars),i+horizon+1))
                               if bars[j].timestamp==exit_time),i+horizon+1)
        events.append(event)
    return events

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--db",default="data/scanstock.db")
    p.add_argument("--limit",type=int,default=100)
    p.add_argument("--split-at",default="2025-01-01")
    p.add_argument("--horizon",type=int,default=5)
    p.add_argument("--fee-bps",type=float,default=10)
    p.add_argument("--output",default="data/scanner_ath_vcp_100.json")
    args=p.parse_args()
    datetime.fromisoformat(args.split_at)
    if args.limit<1 or args.horizon<1 or args.fee_bps<0:
        p.error("Invalid limit/horizon/fees")
    symbols=symbols_with_daily(args.db)[:args.limit]
    per_rule={name:{} for name in RULES}
    exclusions={}
    counts={name:0 for name in RULES}
    for n,symbol in enumerate(symbols,1):
        try:
            bars=load_daily(args.db,symbol)
            if len(bars)<250:
                exclusions[symbol]="fewer than 250 bars"
                continue
            hits=detect(bars,symbol)
            for name,indices in hits.items():
                counts[name]+=len(indices)
                per_rule[name][symbol]=walkforward(evaluate(symbol,bars,indices,args.horizon,args.fee_bps),args.split_at)
        except (ValueError,TypeError,KeyError,ZeroDivisionError) as exc:
            exclusions[symbol]=str(exc)
        if n%10==0:
            print(f"Processed {n}/{len(symbols)}",flush=True)
    report={"research_only":True,"sample":"first N alphabetically sorted 1D symbols",
            "selected":symbols,"excluded":exclusions,"split_at":args.split_at,
            "horizon":args.horizon,"fee_bps_each_side":args.fee_bps,
            "note":"ATH uses rolling prior highs and production 62-candle window; VCP reuses production metric function. Next-open fills, 1:2 target, signal-low stop; no overlap within each setup/symbol. Not portfolio simulation.",
            "setups":{name:{"rule":RULES[name],"signals":counts[name],
                            "summary":aggregate_symbol_reports(per_rule[name])}
                      for name in RULES}}
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    temp=out.with_suffix(out.suffix+".tmp")
    temp.write_text(json.dumps(report,indent=2),encoding="utf-8")
    temp.replace(out)
    print("Saved:",out)
    for name,item in report["setups"].items():
        print(name,"signals",item["signals"],"unseen",json.dumps(item["summary"]["unseen"]))
    print("Excluded:",len(exclusions),"— no orders")
if __name__=="__main__":
    main()
