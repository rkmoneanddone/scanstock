"""Standalone weekly/daily Trade Lab using existing daily SQLite data. No orders."""
import json, sqlite3, threading
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from datetime import datetime as utc_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse,parse_qs
DB=Path(__file__).resolve().parents[1]/"data"/"scanstock.db"
IST=timezone(timedelta(hours=5,minutes=30))
MEMORY_DB=DB.parent/"trade_lab_memory.db"
MEMORY_LOCK=threading.Lock()
def save_replay(symbol,cutoff,end,plan,outcome):
    """Save both winning and losing replay cases, without altering market candles."""
    payload=json.dumps(plan,sort_keys=True)
    with MEMORY_LOCK:
        con=sqlite3.connect(MEMORY_DB)
        try:
            con.execute("""CREATE TABLE IF NOT EXISTS trade_cases (
                symbol TEXT NOT NULL, cutoff TEXT NOT NULL, replay_end TEXT NOT NULL,
                setup TEXT NOT NULL, decision TEXT NOT NULL, proposal_json TEXT NOT NULL,
                outcome_json TEXT NOT NULL, saved_at TEXT NOT NULL,
                PRIMARY KEY(symbol,cutoff,replay_end))""")
            con.execute("""INSERT INTO trade_cases
                (symbol,cutoff,replay_end,setup,decision,proposal_json,outcome_json,saved_at)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol,cutoff,replay_end) DO UPDATE SET
                setup=excluded.setup,decision=excluded.decision,
                proposal_json=excluded.proposal_json,outcome_json=excluded.outcome_json,
                saved_at=excluded.saved_at""",
                (symbol,cutoff,end,plan.get("setup",""),plan["decision"],payload,
                 json.dumps(outcome,sort_keys=True),utc_datetime.now(timezone.utc).isoformat()))
            con.commit()
        finally:con.close()

def load(symbol, end):
    if not symbol.replace("&","").replace("-","").isalnum() or len(symbol)>32: raise ValueError("Invalid symbol")
    con=sqlite3.connect(DB.resolve().as_uri()+"?mode=ro",uri=True)
    try:
        rows=con.execute("SELECT timestamp,open,high,low,close,volume FROM candles WHERE symbol=? AND timeframe='1D' ORDER BY timestamp",(symbol,)).fetchall()
    finally:con.close()
    out=[]
    for t,o,h,l,c,v in rows:
        dt=datetime.fromisoformat(t.replace("Z","+00:00"))
        day=dt.astimezone(IST).date().isoformat() if dt.tzinfo else dt.date().isoformat()
        if day<=end:out.append(dict(t=day,o=float(o),h=float(h),l=float(l),c=float(c),v=int(v)))
    return out
def weekly(daily,cutoff):
    groups={}
    for b in daily:
        d=date.fromisoformat(b["t"]);mon=d-timedelta(days=d.weekday());fri=mon+timedelta(days=4)
        if fri.isoformat()>cutoff:continue
        key=mon.isoformat()
        if key not in groups:groups[key]=dict(t=fri.isoformat(),o=b["o"],h=b["h"],l=b["l"],c=b["c"],v=b["v"])
        else:
            w=groups[key];w["h"]=max(w["h"],b["h"]);w["l"]=min(w["l"],b["l"]);w["c"]=b["c"];w["v"]+=b["v"]
    return list(groups.values())
def ema(values, period):
    alpha = 2 / (period + 1)
    value = values[0]
    for x in values[1:]:
        value = alpha * x + (1 - alpha) * value
    return value

def rsi(closes, period=14):
    changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    if len(changes) < period: return 50.0
    gains = [max(0, x) for x in changes]
    losses = [max(0, -x) for x in changes]
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for g,l in zip(gains[period:], losses[period:]):
        avg_g = (avg_g * (period-1) + g) / period
        avg_l = (avg_l * (period-1) + l) / period
    return 100 if avg_l == 0 else 100 - 100/(1 + avg_g/avg_l)

def propose(d,w):
    if len(d)<60 or len(w)<12:
        return dict(decision="INSUFFICIENT DATA",reason=f"Need 60 daily and 12 completed weekly bars; found {len(d)} and {len(w)}.")
    closes=[x["c"] for x in d]
    current=d[-1]
    e9,e21,e50=(ema(closes[-max(100,n*3):],n) for n in (9,21,50))
    momentum=rsi(closes)
    last20=d[-20:]
    support=min(x["l"] for x in last20)
    resistance=max(x["h"] for x in last20)
    recent=d[-5:]
    # Pattern signals are hypotheses, not guaranteed profitable trades.
    rebound = current["c"] > current["o"] and current["c"] > d[-2]["c"] and min(x["l"] for x in recent) <= support*1.015
    recovery = current["c"] > e9 and d[-2]["c"] <= e9
    breakout = current["c"] > max(x["h"] for x in d[-21:-1])
    bullish_trend = current["c"] > e21 > e50 and w[-1]["c"] > sum(x["c"] for x in w[-10:])/10
    candidates=[]
    if rebound:candidates.append("Support rebound")
    if recovery:candidates.append("EMA9 recovery")
    if breakout:candidates.append("20-day breakout")
    if bullish_trend:candidates.append("Weekly/daily trend")
    # Provide a watchlist hypothesis even when no immediate trigger exists.
    setup=candidates[0] if candidates else "Support reversal watch"
    entry=round(current["h"]+0.05,2)
    stop=round(min(x["l"] for x in d[-10:])-0.05,2)
    if stop>=entry or stop<=0:
        return dict(decision="NO TRADE",reason="No valid positive-risk long entry.")
    risk=entry-stop
    # R-based targets are projections, explicitly not historical resistance.
    tp1=round(entry+1.5*risk,2)
    tp2=round(entry+2.5*risk,2)
    triggered=bool(candidates)
    return dict(decision="BUY SETUP" if triggered else "WATCH",
        setup=setup,signals=candidates,reason=("Potential long setup; entry requires a subsequent breakout above the cutoff candle." if triggered else "No confirmed bullish trigger at cutoff; conditional breakout watch only, not an immediate BUY."),
        entry=entry,sl=stop,tp1=tp1,tp2=tp2,
        rsi14=round(momentum,1),ema9=round(e9,2),ema21=round(e21,2),ema50=round(e50,2),
        support=round(support,2),resistance=round(resistance,2),
        target_method="Projected 1.5R / 2.5R; not verified resistance",risk_reward_tp1=1.5)

def replay(plan,bars):
    if plan["decision"]!="BUY SETUP":return dict(status="NOT ELIGIBLE",events=[],note="WATCH/NO TRADE proposals are not executed in replay.")
    entry,sl,tp1,tp2=(plan[k] for k in ("entry","sl","tp1","tp2"))
    events=[];fill=None;remaining=1;realized=0
    for b in bars:
        if fill is None:
            if b["h"]<entry:continue
            fill=max(entry,b["o"]);events.append(dict(kind="ENTRY",t=b["t"],price=fill))
            if b["l"]<=sl:
                price=min(sl,b["o"]);events.append(dict(kind="SL",t=b["t"],price=price))
                return dict(status="STOPPED",events=events,gross_pnl_per_share=round(price-fill,2))
            # Do not assume a target occurred after an entry in the same daily bar.
            continue
        if b["l"]<=sl:
            price=min(sl,b["o"]);realized+=remaining*(price-fill);events.append(dict(kind="SL",t=b["t"],price=price))
            return dict(status="STOPPED",events=events,gross_pnl_per_share=round(realized,2))
        if remaining==1 and b["h"]>=tp1:
            price=max(tp1,b["o"]);realized+=.5*(price-fill);remaining=.5
            events.append(dict(kind="TP1",t=b["t"],price=price));continue
        if remaining==.5 and b["h"]>=tp2:
            price=max(tp2,b["o"]);realized+=.5*(price-fill)
            events.append(dict(kind="TP2",t=b["t"],price=price))
            return dict(status="TP2 HIT",events=events,gross_pnl_per_share=round(realized,2))
    return dict(status="OPEN" if fill is not None else "NOT TRIGGERED",events=events,gross_realized_pnl_per_share=round(realized,2))
HTML="""<!doctype html><html><head><meta charset="utf-8"><title>ScanStock Trade Lab</title>
<style>body{background:#0b1422;color:#e6edf7;font:14px system-ui;padding:20px}main{max-width:1400px;margin:auto}
nav,.panels,.actions{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}section{background:#142139;border:1px solid #35445b;border-radius:12px;padding:14px;flex:1;min-width:350px}
svg{width:100%;height:320px}button,input{background:#203351;color:white;border:1px solid #52647d;border-radius:6px;padding:9px}
#symbol-results{position:absolute;top:100%;left:0;z-index:10;width:340px;max-height:260px;overflow:auto;background:#192940;border:1px solid #52647d;border-radius:7px;box-shadow:0 12px 30px #0009}#symbol-results:empty{display:none}#symbol-results button{display:block;width:100%;text-align:left;border:0;border-bottom:1px solid #35445b;border-radius:0;background:transparent}#symbol-results button:hover{background:#304966}.stock-wrap{position:relative;display:inline-flex;align-items:center;gap:6px}#refresh{background:#275b8f}button{cursor:pointer}button:disabled{opacity:.4}#result{background:#142139;padding:16px;border-radius:10px}small{color:#a6b5ca}
</style></head><body><main><h1>ScanStock | Historical Trade Lab</h1><small>Weekly + Daily · Existing stored data · No orders</small>
<nav><span class="stock-wrap">Stock <input id="symbol" value="APOLLOHOSP" size="18" autocomplete="off" placeholder="Search symbol or company"><div id="symbol-results"></div></span>Start <input id="start" type="date" value="2026-01-01">
Cutoff <input id="cutoff" type="date" value="2026-01-31">Replay end <input id="end" type="date" value="2026-02-28">
<button id="refresh" type="button">↻ Refresh Charts</button><button id="propose">Propose Trade</button><button id="replay" disabled>Run February Replay</button></nav>
<div class="panels"><section><h3>1W · Higher timeframe</h3><small id="ws"></small><svg id="w" viewBox="0 0 600 320"></svg></section>
<section><h3>1D · Lower timeframe</h3><small id="ds"></small><svg id="d" viewBox="0 0 600 320"></svg></section></div>
<div id="result">Loading January candles…</div><div class="actions"><button id="buy" disabled>BUY (simulation)</button><button id="ignore" disabled>IGNORE</button><small id="choice">Dhan trading disabled</small></div>
<script>
const $=id=>document.getElementById(id);let proposal=null,requestVersion=0;
async function get(mode){let q=new URLSearchParams({mode,symbol:$('symbol').value,start:$('start').value,cutoff:$('cutoff').value,end:$('end').value});
let r=await fetch('/api?'+q),j=await r.json();if(!r.ok)throw Error(j.error);return j}
function draw(id,bars,p={}){
let svg=$(id);svg.replaceChildren();const el=(n,a)=>{let x=document.createElementNS('http://www.w3.org/2000/svg',n);Object.entries(a).forEach(([k,v])=>x.setAttribute(k,v));svg.appendChild(x);return x};
if(!bars.length){el('text',{x:20,y:150,fill:'#ffb869'}).textContent='No candles in selected period';return}
let values=bars.flatMap(b=>[b.l,b.h]).concat(['entry','sl','tp1','tp2'].map(k=>p[k]).filter(Number.isFinite));
let low=Math.min(...values),high=Math.max(...values),scale=high-low||1,y=v=>290-(v-low)/scale*260,width=580/bars.length;
bars.forEach((b,i)=>{let x=10+(i+.5)*width,c=b.c>=b.o?'#3dc891':'#f06c7b';
el('line',{x1:x,y1:y(b.h),x2:x,y2:y(b.l),stroke:c});el('rect',{x:x-Math.max(1,width*.28),y:Math.min(y(b.o),y(b.c)),width:Math.max(2,width*.56),height:Math.max(1,Math.abs(y(b.o)-y(b.c))),fill:c})});
['entry','sl','tp1','tp2'].forEach(k=>{if(!Number.isFinite(p[k]))return;let c=k==='sl'?'#f66':k==='entry'?'#6aa9ff':'#60e7b0';
el('line',{x1:5,y1:y(p[k]),x2:590,y2:y(p[k]),stroke:c,'stroke-dasharray':'5 4'});
el('text',{x:510,y:y(p[k])-5,fill:c,'font-size':11}).textContent=k.toUpperCase()+' '+p[k]})}
function show(j,withPlan=false){draw('w',j.weekly,withPlan?j.plan:{});draw('d',j.daily,withPlan?j.plan:{});
$('ws').textContent=j.weekly.length+' completed weekly candles';$('ds').textContent=j.daily.length+' daily candles'}
async function load(){
 const version=++requestVersion;
 draw('w',[]);draw('d',[]);
 $('ws').textContent='Loading selected range…';$('ds').textContent='Loading selected range…';
 $('result').textContent='Loading candles for '+$('symbol').value+'…';
 try{let j=await get('charts');if(version!==requestVersion)return;
 show(j);$('result').textContent='Charts loaded. Propose Trade uses only candles through cutoff.';
 }catch(e){if(version===requestVersion)$('result').textContent=e.message}
}
$('propose').onclick=async()=>{try{let j=await get('propose');proposal=j.plan;show(j,true);
$('result').innerHTML='<h3>'+j.plan.decision+' · '+(j.plan.setup||'')+'</h3><p>'+j.plan.reason+'</p><pre>'+JSON.stringify(j.plan,null,2)+'</pre>';$('replay').disabled=false;
$('buy').disabled=j.plan.decision!=='BUY SETUP';$('ignore').disabled=false}catch(e){$('result').textContent=e.message}};
$('replay').onclick=async()=>{try{let j=await get('replay');show(j,true);$('result').innerHTML='<h3>'+j.plan.decision+' · '+j.replay.status+'</h3><pre>'+JSON.stringify({proposal:j.plan,replay:j.replay},null,2)+'</pre>'}catch(e){$('result').textContent=e.message}};
$('buy').onclick=()=>{$('choice').textContent='BUY selected for simulation only; no order sent'};
$('ignore').onclick=()=>{$('choice').textContent='IGNORED; no order sent'};
let universe=[];
async function searchStocks(){
 const term=$('symbol').value.trim().toUpperCase();
 const matches=universe.filter(x=>x.symbol.includes(term)||x.name.toUpperCase().includes(term)).slice(0,12);
 const box=$('symbol-results');box.replaceChildren();
 if(!term)return;
 matches.forEach(item=>{
   let b=document.createElement('button');b.type='button';
   b.textContent=item.name&&item.name!==item.symbol?item.symbol+' · '+item.name:item.symbol;
   b.onpointerdown=e=>{e.preventDefault();$('symbol').value=item.symbol;box.replaceChildren();reset();};
   box.appendChild(b);
 });
}
async function loadUniverse(){
 try{let r=await fetch('/api?mode=symbols');if(!r.ok)throw Error('Universe unavailable');
 universe=(await r.json()).symbols;searchStocks();
 }catch(e){$('choice').textContent='Stock lookup unavailable: '+e.message}
}
function reset(){proposal=null;$('replay').disabled=true;$('buy').disabled=true;$('ignore').disabled=true;$('choice').textContent='Dhan trading disabled';load()}
$('refresh').onclick=reset;
$('symbol').addEventListener('input',searchStocks);
$('symbol').addEventListener('blur',()=>setTimeout(()=>{$('symbol-results').replaceChildren()},180));
function plusMonths(iso, months){
 const [year,month,day]=iso.split('-').map(Number);
 if(!year||!month||!day)return iso;
 const first=new Date(Date.UTC(year,month-1+months,1));
 const lastDay=new Date(Date.UTC(first.getUTCFullYear(),first.getUTCMonth()+1,0)).getUTCDate();
 return first.getUTCFullYear()+'-'+String(first.getUTCMonth()+1).padStart(2,'0')+'-'+String(Math.min(day,lastDay)).padStart(2,'0');
}
$('start').addEventListener('change',()=>{
 const start=$('start').value;
 if(start){
   // Inclusive calendar-month windows: January 1 -> January 31 -> February 28.
   // Use the end of the start month as the analysis cutoff, not February 1.
   const [year,month]=start.split('-').map(Number);
   const cutoff=new Date(Date.UTC(year,month,0));
   const replayEnd=new Date(Date.UTC(year,month+1,0));
   $('cutoff').value=cutoff.toISOString().slice(0,10);
   $('end').value=replayEnd.toISOString().slice(0,10);
 }
 reset();
});
['symbol','cutoff','end'].forEach(id=>$(id).onchange=reset);
loadUniverse();load();</script></main></body></html>"""
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if urlparse(self.path).path!="/api":body=HTML.encode();status=200;typ="text/html; charset=utf-8"
        else:
            try:
                q={k:v[0] for k,v in parse_qs(urlparse(self.path).query).items()}
                if q.get("mode")=="symbols":
                    con=sqlite3.connect(DB.resolve().as_uri()+"?mode=ro",uri=True)
                    try:
                        # The stored candle universe is the authoritative list of selectable stocks.
                        rows=con.execute("SELECT DISTINCT symbol FROM candles WHERE timeframe='1D' ORDER BY symbol").fetchall()
                        symbols=[dict(symbol=row[0],name=row[0]) for row in rows]
                        # Enrich with optional metadata only when an existing table has compatible columns.
                        for table in ("instruments","stocks","stock_universe"):
                            cols={row[1].lower():row[1] for row in con.execute("PRAGMA table_info("+table+")")}
                            sym=next((cols[k] for k in ("symbol","trading_symbol","tradingsymbol") if k in cols),None)
                            name=next((cols[k] for k in ("company_name","name","display_name") if k in cols),None)
                            if sym and name:
                                lookup=dict(con.execute('SELECT "'+sym+'","'+name+'" FROM "'+table+'" WHERE "'+sym+'" IS NOT NULL').fetchall())
                                for item in symbols:item["name"]=str(lookup.get(item["symbol"]) or item["symbol"])
                                break
                    finally:con.close()
                    body=json.dumps(dict(symbols=symbols)).encode()
                    self.send_response(200);self.send_header("Content-Type","application/json")
                    self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
                    return
                mode=q.get("mode");symbol=q.get("symbol","APOLLOHOSP").upper()
                start=date.fromisoformat(q.get("start","2026-01-01")).isoformat()
                cutoff=date.fromisoformat(q.get("cutoff","2026-01-31")).isoformat()
                end=date.fromisoformat(q.get("end","2026-02-28")).isoformat()
                if not start<=cutoff<end or mode not in ("charts","propose","replay"):raise ValueError("Invalid date range or mode")
                all_daily=load(symbol,end if mode=="replay" else cutoff)
                known=[b for b in all_daily if b["t"]<=cutoff]
                plan=propose(known,weekly(known,cutoff))
                view_end=end if mode=="replay" else cutoff
                result=dict(plan=plan,daily=[b for b in all_daily if b["t"]>=start],
                            weekly=[b for b in weekly(all_daily,view_end) if b["t"]>=start])
                if mode=="replay":
                    result["replay"]=replay(plan,[b for b in all_daily if cutoff<b["t"]<=end])
                    save_replay(symbol,cutoff,end,plan,result["replay"])
                body=json.dumps(result).encode();status=200
            except (ValueError,sqlite3.Error,OSError) as e:
                body=json.dumps(dict(error=str(e))).encode();status=400
            typ="application/json"
        self.send_response(status);self.send_header("Content-Type",typ);self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
if __name__=="__main__":
    print("Weekly/Daily Trade Lab: http://127.0.0.1:8767 (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1",8767),Handler).serve_forever()
