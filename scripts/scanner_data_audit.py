"""Read-only daily candle integrity audit before interpreting scanner P&L."""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from scanstock.trading.scanstock_data import load_daily,symbols_with_daily

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--db",default="data/scanstock.db")
    p.add_argument("--limit",type=int,default=100)
    p.add_argument("--output",default="data/scanner_data_audit_100.json")
    a=p.parse_args()
    report={"symbols_checked":0,"bars_checked":0,"utc_weekdays":Counter(),
            "ist_weekdays":Counter(),"weekend_ist_examples":[],
            "invalid_ohlc_examples":[],"large_close_gap_examples":[],"timestamp_parse_errors":[]}
    for symbol in symbols_with_daily(a.db)[:a.limit]:
        bars=load_daily(a.db,symbol)
        report["symbols_checked"]+=1
        for b in bars:
            report["bars_checked"]+=1
            try:
                dt=datetime.fromisoformat(b.timestamp.replace("Z","+00:00"))
                if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
                ist=dt.astimezone(timezone(timedelta(hours=5,minutes=30)))
                report["utc_weekdays"][dt.strftime("%A")]+=1
                report["ist_weekdays"][ist.strftime("%A")]+=1
                if ist.weekday()>=5 and len(report["weekend_ist_examples"])<15:
                    report["weekend_ist_examples"].append({"symbol":symbol,"raw":b.timestamp,"ist":ist.isoformat()})
            except ValueError:
                if len(report["timestamp_parse_errors"])<15:report["timestamp_parse_errors"].append([symbol,b.timestamp])
            if not(b.low<=b.open<=b.high and b.low<=b.close<=b.high and b.low>0):
                if len(report["invalid_ohlc_examples"])<15:
                    report["invalid_ohlc_examples"].append({"symbol":symbol,"timestamp":b.timestamp})
        for before,after in zip(bars,bars[1:]):
            if before.close>0 and abs(after.open/before.close-1)>0.4:
                if len(report["large_close_gap_examples"])<15:
                    report["large_close_gap_examples"].append({"symbol":symbol,"at":after.timestamp,
                        "previous_close":str(before.close),"next_open":str(after.open)})
    report["utc_weekdays"]=dict(report["utc_weekdays"])
    report["ist_weekdays"]=dict(report["ist_weekdays"])
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print("Saved:",out)
    print(json.dumps({k:v for k,v in report.items() if k not in ("weekend_ist_examples","invalid_ohlc_examples","large_close_gap_examples","timestamp_parse_errors")},indent=2))
    print("Weekend IST examples:",len(report["weekend_ist_examples"]),"OHLC violations:",len(report["invalid_ohlc_examples"]))
if __name__=="__main__":main()
