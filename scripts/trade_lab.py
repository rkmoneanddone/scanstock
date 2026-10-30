"""Standalone read-only historical Trade Lab. Run: python scripts/trade_lab.py"""
import json
import sqlite3
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "scanstock.db"
IST = timezone(timedelta(hours=5, minutes=30))

def day_of(timestamp):
    dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.date().isoformat()
    return dt.astimezone(IST).date().isoformat()

def candles(symbol, tf, through):
    if not DB.exists():
        raise ValueError("Missing data/scanstock.db")
    if not symbol.replace("-", "").replace("&", "").isalnum() or len(symbol) > 32:
        raise ValueError("Invalid symbol")
    con = sqlite3.connect(DB.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT timestamp,open,high,low,close,volume FROM candles "
            "WHERE symbol=? AND timeframe=? ORDER BY timestamp",
            (symbol.upper(), tf)).fetchall()
    finally:
        con.close()
    return [dict(t=day_of(r[0]), timestamp=str(r[0]), o=float(r[1]), h=float(r[2]),
                 l=float(r[3]), c=float(r[4]), v=int(r[5])) for r in rows
            if day_of(r[0]) <= through]

def propose(daily, hourly):
    # Deliberately simple baseline: transparent, deterministic, never an LLM guess.
    if len(daily) < 60 or len(hourly) < 25:
        return dict(decision="NO TRADE", reason="Need at least 60 daily and 25 hourly candles before cutoff.")
    d = daily[-1]
    ma21 = sum(x["c"] for x in daily[-21:]) / 21
    ma50 = sum(x["c"] for x in daily[-50:]) / 50
    h = hourly[-1]
    ema9 = hourly[-9]["c"]
    # Baseline uses mean of 9 bars, not an EMA; label accurately.
    mean9 = sum(x["c"] for x in hourly[-9:]) / 9
    mean21 = sum(x["c"] for x in hourly[-21:]) / 21
    if not (d["c"] > ma21 > ma50 and h["c"] > mean9 > mean21):
        return dict(decision="NO TRADE", reason="Daily trend and hourly momentum are not both bullish (SMA21/SMA50, SMA9/SMA21).")
    entry = round(h["h"] + 0.05, 2)
    stop = round(min(x["l"] for x in hourly[-10:]) - 0.05, 2)
    risk = entry - stop
    if stop <= 0 or risk <= entry * 0.005:
        return dict(decision="NO TRADE", reason="Invalid or too-tight structural stop.")
    resistance = [x["h"] for x in daily[-60:-1] if x["h"] > entry]
    if not resistance:
        return dict(decision="NO TRADE", reason="No prior daily resistance to anchor two targets; no speculative extension.")
    tp1 = round(min(resistance), 2)
    higher = sorted(set(round(x["h"], 2) for x in daily[-60:-1] if x["h"] > tp1))
    if not higher:
        return dict(decision="NO TRADE", reason="No second historical resistance target.")
    tp2 = higher[0]
    if (tp1 - entry) / risk < 1.5:
        return dict(decision="NO TRADE", reason="Gross TP1 reward/risk below 1.5; costs make it worse.")
    return dict(decision="BUY SETUP", reason="Daily bullish SMA alignment and hourly bullish SMA alignment; entry above last hourly high. Baseline hypothesis only, not validated edge.",
                entry=entry, sl=stop, tp1=tp1, tp2=tp2,
                gross_rr=round((tp1-entry)/risk, 2))

def replay(plan, future):
    if plan["decision"] != "BUY SETUP":
        return dict(status="NO TRADE", events=[])
    entry, sl, tp1, tp2 = (plan[k] for k in ("entry", "sl", "tp1", "tp2"))
    events = []
    active = False
    remaining = 1.0
    net = 0.0
    for b in future:
        if not active:
            if b["h"] < entry:
                continue
            # Buy stop: opening gap fills at open, not at favorable trigger.
            fill = max(entry, b["o"])
            active = True
            events.append(dict(kind="ENTRY", t=b["timestamp"], price=fill))
            # A bar containing both entry and a stop has unknowable order: assume stop first.
            if b["l"] <= sl:
                net += sl - fill if b["o"] > sl else min(sl, b["o"]) - fill
                events.append(dict(kind="SL", t=b["timestamp"], price=min(sl, b["o"])))
                return dict(status="STOPPED", events=events, gross_pnl_per_share=round(net, 2),
                            note="Conservative entry/stop same-bar assumption")
        if b["o"] <= sl or b["l"] <= sl:
            exit_price = min(sl, b["o"])
            net += remaining * (exit_price - fill)
            events.append(dict(kind="SL", t=b["timestamp"], price=exit_price))
            return dict(status="STOPPED", events=events, gross_pnl_per_share=round(net, 2))
        if remaining == 1 and b["h"] >= tp1:
            exit_price = max(tp1, b["o"])
            net += 0.5 * (exit_price - fill)
            remaining = 0.5
            events.append(dict(kind="TP1", t=b["timestamp"], price=exit_price))
        if remaining == 0.5 and b["h"] >= tp2:
            # If both targets hit same bar, order is unobservable; conservatively
            # credit TP1 only and keep second half pending until another bar.
            if events[-1]["kind"] == "TP1" and events[-1]["t"] == b["timestamp"]:
                continue
            exit_price = max(tp2, b["o"])
            net += 0.5 * (exit_price - fill)
            events.append(dict(kind="TP2", t=b["timestamp"], price=exit_price))
            return dict(status="TP2 HIT", events=events, gross_pnl_per_share=round(net, 2))
    return dict(status="OPEN" if active else "NOT TRIGGERED", events=events,
                gross_realized_pnl_per_share=round(net, 2),
                note="Position not forcibly closed; fees/slippage not yet modeled.")

HTML = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>ScanStock Trade Lab</title><style>
body{font:14px system-ui;background:#0c1422;color:#e6edf7;margin:0;padding:24px}
header,nav,.panels,.bottom{display:flex;gap:12px;align-items:center;justify-content:space-between}
h1{margin:0;font-size:24px}small{color:#a7b4c8}
main{max-width:1500px;margin:auto}nav{margin:24px 0;justify-content:flex-start;flex-wrap:wrap}
input,button{background:#17243a;color:white;border:1px solid #354966;border-radius:7px;padding:10px}
button{cursor:pointer}button.primary{background:#2165bd}button:disabled{opacity:.4;cursor:not-allowed}
.panels{align-items:stretch}.pane{flex:1;min-width:0;background:#111e31;border:1px solid #34445d;border-radius:12px;padding:14px}
svg{width:100%;height:320px}.result{background:#111e31;border:1px solid #34445d;border-radius:12px;margin:16px 0;padding:18px}
.bottom{justify-content:flex-end}b{color:#79e3a1}.warn{color:#ffca70}
@media(max-width:800px){.panels{flex-direction:column}svg{height:240px}}
</style></head><body><main>
<header><div><h1>ScanStock | Historical Trade Lab</h1><small>Read-only research • No Dhan orders • No future data in proposal</small></div><span>LOCAL</span></header>
<nav><label>Stock <input id="symbol" value="SBIN" size="9"></label>
<label>Start <input type="date" id="start" value="2026-01-01"></label>
<label>Cutoff <input type="date" id="cutoff" value="2026-01-31"></label>
<label>Replay end <input type="date" id="end" value="2026-02-28"></label>
<button class="primary" id="propose">Propose Trade</button><button id="replay" disabled>Run Replay</button></nav>
<div class="panels"><section class="pane"><h3>1D • Higher timeframe</h3><svg id="daily" viewBox="0 0 620 320"></svg></section>
<section class="pane"><h3>1H • Lower timeframe</h3><svg id="hourly" viewBox="0 0 620 320"></svg></section></div>
<div class="result" id="result">Choose a cutoff and click Propose Trade. Only candles through the cutoff are analysed.</div>
<div class="bottom"><button id="buy" disabled>BUY (simulation only)</button><button id="ignore" disabled>IGNORE</button><small id="choice">Live trading disabled</small></div>
</main><script>
let plan=null, approved=false;
const $=id=>document.getElementById(id);
async function api(params){let r=await fetch('/api?'+new URLSearchParams(params));let j=await r.json();if(!r.ok)throw Error(j.error||'Request failed');return j}
function chart(id, bars, levels={}){
 let svg=$(id);svg.replaceChildren();if(!bars.length){svg.textContent='No candles available';return}
 let vals=bars.flatMap(b=>[b.h,b.l]).concat(Object.values(levels).filter(v=>typeof v==='number'));
 let lo=Math.min(...vals),hi=Math.max(...vals),range=hi-lo||1;
 const el=(name,attrs)=>{let n=document.createElementNS('http://www.w3.org/2000/svg',name);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));svg.appendChild(n);return n};
 const y=v=>290-(v-lo)/range*260;let w=600/bars.length;
 bars.forEach((b,i)=>{let x=10+(i+.5)*w,c=b.c>=b.o?'#31bb85':'#e36c71';
 el('line',{x1:x,y1:y(b.h),x2:x,y2:y(b.l),stroke:c,'stroke-width':1});
 el('rect',{x:x-Math.max(1,w*.27),y:Math.min(y(b.o),y(b.c)),width:Math.max(2,w*.54),height:Math.max(1,Math.abs(y(b.c)-y(b.o))),fill:c})});
 Object.entries(levels).forEach(([k,v])=>{if(typeof v!=='number')return;let c=k==='sl'?'#f66':k==='entry'?'#68a8ff':'#6ee7b7';
 el('line',{x1:5,y1:y(v),x2:610,y2:y(v),stroke:c,'stroke-dasharray':'5 4'});
 let t=el('text',{x:535,y:y(v)-5,fill:c,'font-size':12});t.textContent=k.toUpperCase()+' '+v});
}
function describe(p){return '<strong>'+p.decision+'</strong><p>'+p.reason+'</p>'+
(p.entry?'<p>Entry: <b>'+p.entry+'</b> | SL: <b>'+p.sl+'</b> | TP1: <b>'+p.tp1+'</b> | TP2: <b>'+p.tp2+'</b> | Gross RR to TP1: '+p.gross_rr+'</p>':'')+
'<small>Research-only baseline; no proven edge. No live trade authority.</small>'}
$('propose').onclick=async()=>{try{
 let j=await api({mode:'propose',symbol:$('symbol').value,start:$('start').value,cutoff:$('cutoff').value});
 plan=j.plan;approved=false;chart('daily',j.daily,plan);chart('hourly',j.hourly,plan);
 $('result').innerHTML=describe(plan);$('replay').disabled=false;$('buy').disabled=plan.decision!=='BUY SETUP';$('ignore').disabled=false;$('choice').textContent='Awaiting simulation choice'
}catch(e){$('result').textContent=e.message}};
$('buy').onclick=()=>{approved=true;$('choice').textContent='BUY selected for historical simulation only'};
$('ignore').onclick=()=>{approved=false;$('choice').textContent='IGNORED: no simulated position'};
$('replay').onclick=async()=>{try{
 let j=await api({mode:'replay',symbol:$('symbol').value,start:$('start').value,cutoff:$('cutoff').value,end:$('end').value});
 // Server independently recomputes proposal; never trusts client-supplied prices.
 plan=j.plan;chart('daily',j.daily,plan);chart('hourly',j.hourly,plan);
 $('result').innerHTML=describe(plan)+'<hr><h3>Forward replay: '+j.replay.status+'</h3><pre>'+JSON.stringify(j.replay,null,2)+'</pre>'+
 '<small>BUY/IGNORE is a local UI selection only. Replay always shows hypothetical outcome, even if ignored.</small>';
}catch(e){$('result').textContent=e.message}};
</script></body></html>"""

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api":
            payload = HTML.encode()
            self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8")
        else:
            try:
                q = {k:v[0] for k,v in parse_qs(parsed.query).items()}
                symbol = q.get("symbol","SBIN").upper()
                start = date.fromisoformat(q.get("start","2026-01-01")).isoformat()
                cutoff = date.fromisoformat(q.get("cutoff","2026-01-31")).isoformat()
                end = date.fromisoformat(q.get("end","2026-02-28")).isoformat()
                if not start <= cutoff < end: raise ValueError("Require start <= cutoff < replay end")
                if q.get("mode") not in ("propose","replay"): raise ValueError("Invalid mode")
                daily = candles(symbol,"1D",end if q["mode"]=="replay" else cutoff)
                hourly = candles(symbol,"1H",end if q["mode"]=="replay" else cutoff)
                before_d = [b for b in daily if b["t"] <= cutoff]
                before_h = [b for b in hourly if b["t"] <= cutoff]
                plan = propose(before_d,before_h)
                shown_d = [b for b in daily if b["t"] >= start]
                shown_h = [b for b in hourly if b["t"] >= start]
                result = dict(plan=plan,daily=shown_d,hourly=shown_h)
                if q["mode"]=="replay":
                    result["replay"]=replay(plan,[b for b in hourly if cutoff < b["t"] <= end])
                payload = json.dumps(result).encode()
                self.send_response(200);self.send_header("Content-Type","application/json")
            except (ValueError,sqlite3.Error,TypeError) as exc:
                payload=json.dumps(dict(error=str(exc))).encode()
                self.send_response(400);self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(payload)));self.end_headers();self.wfile.write(payload)

if __name__=="__main__":
    print("Trade Lab: http://127.0.0.1:8766 (read-only; Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1",8766),Handler).serve_forever()
