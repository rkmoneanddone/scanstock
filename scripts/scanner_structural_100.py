"""Run five existing daily scanners with a common structure-based exit model."""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from scanstock.trading.scanstock_data import load_daily,symbols_with_daily
from scanstock.trading.structural import evaluate_signals
from scanstock.trading.research_report import aggregate_symbol_reports
from scanner_pilot_100 import signals as basic_signals
from scanner_ath_vcp_100 import detect as advanced_signals

def split_results(events,split_at):
    # Only fully exited before split counts as train. Never assign straddling
    # trades to either sample, avoiding contamination.
    def stats(rows):
        complete=[r for r in rows if r["status"]=="COMPLETE"]
        wins=sum(float(r["r_multiple"])>0 for r in complete)
        from decimal import Decimal
        net=sum((Decimal(r["r_multiple"]) for r in complete),Decimal(0))
        return {"completed_trades":len(complete),"wins":wins,
                "win_rate_pct":str(Decimal(wins)*100/len(complete)) if complete else None,
                "mean_net_r":str(net/len(complete)) if complete else None}
    train=[r for r in events if r["signal_at"]<split_at and r["status"]=="COMPLETE" and r["exit_at"]<split_at]
    unseen=[r for r in events if r["signal_at"]>=split_at and r["status"]=="COMPLETE"]
    return {"train":stats(train),"unseen":stats(unseen),
            "pending":sum(r["status"]=="PENDING" for r in events),
            "skipped":sum(r["status"]=="SKIPPED" for r in events),
            "cross_split_excluded":sum(r["signal_at"]<split_at and r["status"]=="COMPLETE" and r["exit_at"]>=split_at for r in events)}

def aggregate(per_symbol,phase):
    from decimal import Decimal
    rows=[item[phase] for item in per_symbol.values()]
    n=sum(r["completed_trades"] for r in rows)
    wins=sum(r["wins"] for r in rows)
    weighted=sum((Decimal(r["mean_net_r"])*r["completed_trades"] for r in rows if r["completed_trades"]),Decimal(0))
    positive=sum(r["completed_trades"]>0 and Decimal(r["mean_net_r"])>0 for r in rows)
    stocks=sum(r["completed_trades"]>0 for r in rows)
    return {"completed_trades":n,"stocks_with_trades":stocks,"wins":wins,
            "win_rate_pct":str(Decimal(wins)*100/n) if n else None,
            "mean_net_r":str(weighted/n) if n else None,
            "positive_stock_share_pct":str(Decimal(positive)*100/stocks) if stocks else None}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--db",default="data/scanstock.db")
    p.add_argument("--limit",type=int,default=100)
    p.add_argument("--split-at",default="2025-01-01")
    p.add_argument("--fee-bps",type=float,default=10)
    p.add_argument("--min-rr",type=float,default=1)
    p.add_argument("--output",default="data/scanner_structural_100.json")
    args=p.parse_args()
    date.fromisoformat(args.split_at)
    if args.limit<1 or args.fee_bps<0 or args.min_rr<=0:p.error("Invalid limits, fees or reward/risk")
    selected=symbols_with_daily(args.db)[:args.limit]
    results={}; excluded={};sample_trades={}
    for n,symbol in enumerate(selected,1):
        try:
            bars=load_daily(args.db,symbol)
            if len(bars)<250:
                excluded[symbol]="fewer than 250 bars";continue
            detected={**basic_signals(bars),**advanced_signals(bars,symbol)}
            for setup,indices in detected.items():
                events=evaluate_signals(symbol,setup,bars,indices,args.fee_bps,args.min_rr)
                results.setdefault(setup,{})[symbol]=split_results(events,args.split_at)
                sample_trades.setdefault(setup,[])
                for e in events:
                    if e["status"]=="COMPLETE" and e["signal_at"]>=args.split_at and len(sample_trades[setup])<10:
                        sample_trades[setup].append(e)
        except (ValueError,TypeError,KeyError,ZeroDivisionError) as exc:
            excluded[symbol]=str(exc)
        if n%10==0:print(f"Processed {n}/{len(selected)}",flush=True)
    report={"research_only":True,"method":"Causal confirmed swing low stop, nearest prior confirmed swing high target; if no resistance, 1.618 historical range Fibonacci extension; next-open entry, stop-first, no fixed candle timeout; no overlapping same-symbol/setup positions; 10 bps each side by default. No portfolio constraints.",
            "sample_method":"first N alphabetically sorted symbols with 1D data",
            "selected":selected,"excluded":excluded,"split_at":args.split_at,
            "min_rr":args.min_rr,"fee_bps_each_side":args.fee_bps,
            "setups":{name:{"train":aggregate(per_symbol,"train"),"unseen":aggregate(per_symbol,"unseen"),
                            "pending":sum(v["pending"] for v in per_symbol.values()),
                            "skipped":sum(v["skipped"] for v in per_symbol.values()),
                            "cross_split_excluded":sum(v["cross_split_excluded"] for v in per_symbol.values()),
                            "sample_unseen_trades":sample_trades.get(name,[])}
                      for name,per_symbol in results.items()}}
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    temp=out.with_suffix(out.suffix+".tmp")
    temp.write_text(json.dumps(report,indent=2),encoding="utf-8");temp.replace(out)
    print("Saved:",out)
    for name,summary in report["setups"].items():
        print(name,json.dumps(summary["unseen"]))
    print("Excluded:",len(excluded),"— research only, no orders")
if __name__=="__main__":main()
