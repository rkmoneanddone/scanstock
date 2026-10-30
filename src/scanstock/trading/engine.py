"""Paper-only end-to-end engine. No Dhan calls, no real orders."""
import json
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

MARKET_TZ = ZoneInfo("Asia/Kolkata")
def market_date():
    return datetime.now(MARKET_TZ).date()
def trade_market_date(timestamp):
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(MARKET_TZ).date()
from decimal import Decimal
from pathlib import Path
from .core import make_trade_plan
from .hard_checks import AccountState, HardLimits, OrderRequest, HardCheckRejected, validate_order, validate_watchlist
D=lambda x:Decimal(str(x))

class AutoTrader:
    def __init__(self, watchlist=("SBIN","BEL","ITC"), capital=10000, journal=None):
        self.limits=HardLimits()
        self.watchlist=validate_watchlist(watchlist,self.limits)
        self.capital=D(capital)
        if not D(0)<self.capital<=self.limits.max_capital: raise ValueError("Invalid capital")
        self.journal=Path(journal) if journal else None
        self.cash=self.capital
        self.positions={}
        self.trades=[]
        self.prices={s:[] for s in self.watchlist}
        self.last={}
        self.entries=0
        self.day=market_date().isoformat()
        self.daily_pnl=D(0)
        self.halted=False
        self.halt_reason=None
        if self.journal and self.journal.exists(): self._load()

    def _roll(self):
        if self.day!=market_date().isoformat():
            self.day=market_date().isoformat()
            self.entries=0
            self.daily_pnl=D(0)
            self._save()

    def _state(self):
        return AccountState(confirmed_positions={s:p["quantity"] for s,p in self.positions.items()},
            open_position_cost=sum((D(p["entry"])*p["quantity"] for p in self.positions.values()),D(0)),
            available_cash=self.cash,daily_entries=self.entries,reconciled=True,
            trading_enabled=not self.halted,daily_loss_limit_reached=self.daily_pnl<=D(-200))

    def _save(self):
        if not self.journal:return
        self.journal.parent.mkdir(parents=True,exist_ok=True)
        data=dict(capital=str(self.capital),cash=str(self.cash),watchlist=self.watchlist,positions=self.positions,trades=self.trades,
                  entries=self.entries,day=self.day,daily_pnl=str(self.daily_pnl),halted=self.halted,
                  halt_reason=self.halt_reason)
        tmp=self.journal.with_suffix(".tmp")
        with tmp.open("w",encoding="utf8") as f:
            json.dump(data,f,indent=2)
            f.flush()
            import os
            os.fsync(f.fileno())
        import os
        os.replace(tmp,self.journal)

    def _load(self):
        data=json.loads(self.journal.read_text(encoding="utf8"))
        if D(data["capital"])!=self.capital:raise ValueError("Capital mismatch")
        self.cash=D(data["cash"])
        self.positions=data["positions"]
        self.trades=data["trades"]
        self.entries=int(data["entries"])
        self.day=data["day"]
        self.daily_pnl=D(data["daily_pnl"])
        self.halted=bool(data["halted"])
        if "watchlist" in data:
            self.watchlist=validate_watchlist(data["watchlist"],self.limits)
            self.prices={s:[] for s in self.watchlist}
        self.halt_reason=data.get("halt_reason")
        self._roll()

    def buy(self,symbol,price,stop):
        """BUY is triggered only by the demo signal or explicit paper test."""
        self._roll()
        if symbol not in self.watchlist or symbol in self.positions:
            raise HardCheckRejected("Not watched or already held")
        price=D(price)
        committed=self._state().open_position_cost
        plan=make_trade_plan(symbol,price,stop,capital=min(self.cash,self.limits.max_capital-committed),
                             risk_limit=self.limits.max_risk_per_trade)
        validate_order(OrderRequest(symbol,"BUY",plan.quantity,price),self._state(),self.limits)
        self.cash-=price*plan.quantity
        self.positions[symbol]=dict(quantity=plan.quantity,entry=str(price),stop=str(plan.stop_loss),
                                    target=str(plan.take_profit),opened=datetime.now(timezone.utc).isoformat())
        self.entries+=1
        self._save()
        return self.positions[symbol]

    def sell(self,symbol,price,reason="MANUAL"):
        if symbol not in self.positions:raise HardCheckRejected("No SELL before BUY")
        p=self.positions[symbol]
        price=D(price)
        validate_order(OrderRequest(symbol,"SELL",p["quantity"],price),self._state(),self.limits)
        pnl=(price-D(p["entry"]))*p["quantity"]
        self.cash+=price*p["quantity"]
        trade=dict(symbol=symbol,quantity=p["quantity"],entry=p["entry"],exit=str(price),
                   stop=p["stop"],target=p["target"],pnl=str(pnl),reason=reason,
                   opened=p["opened"],closed=datetime.now(timezone.utc).isoformat())
        self.trades.append(trade)
        self.daily_pnl+=pnl
        del self.positions[symbol]
        if self.daily_pnl <= D("-200"):
            self.halted = True
            self.halt_reason = "DAILY_LOSS_LIMIT"
        if self.cash <= 0 and not self.positions:
            self.halted = True
            self.halt_reason = "CAPITAL_EXHAUSTED"
        self._save()
        return trade

    def update_watchlist(self, symbols):
        updated=validate_watchlist(symbols,self.limits)
        if any(s not in updated for s in self.positions):
            raise HardCheckRejected("Cannot remove a stock with an open position")
        self.watchlist=updated
        self.prices={s:self.prices.get(s,[]) for s in updated}
        self.last={s:v for s,v in self.last.items() if s in updated}
        self._save()
        return updated

    def emergency_flatten(self, quotes):
        """Paper-only: halt new entries and close at valid observed quotes."""
        self.halt("EMERGENCY_FLATTEN")
        closed=[]
        errors={}
        for symbol in tuple(self.positions):
            try:
                price=D(quotes[symbol])
                if not price.is_finite() or price<=0: raise ValueError("Invalid price")
                closed.append(self.sell(symbol,price,"EMERGENCY_EXIT"))
            except (KeyError,ValueError,HardCheckRejected) as exc:
                errors[symbol]=str(exc)
        return dict(closed=closed,errors=errors,remaining=list(self.positions))

    def start(self):
        """Resume only an operator STOP; never override risk/emergency halts."""
        self._roll()
        if not self.halted:
            return "ALREADY_RUNNING"
        if self.halt_reason not in ("OPERATOR_STOP","EXIT_INCOMPLETE"):
            raise HardCheckRejected("Risk or emergency halt cannot be reset by START")
        if self.positions:
            raise HardCheckRejected("Cannot START while positions remain open")
        if self.daily_pnl <= D("-200"):
            raise HardCheckRejected("Daily loss limit reached")
        self.halted=False
        self.halt_reason=None
        self._save()
        return "STARTED"

    def stop(self):
        """Stop new paper entries without closing existing positions."""
        if self.halted and self.halt_reason not in ("OPERATOR_STOP",):
            raise HardCheckRejected("Existing risk/emergency halt remains active")
        self.halt("OPERATOR_STOP")
        return "STOPPED"

    def stop_and_exit(self, quotes):
        """Paper STOP; unpriced positions remain open and entries remain blocked."""
        result=self.emergency_flatten(quotes)
        self.halt_reason="OPERATOR_STOP" if not result["remaining"] else "EXIT_INCOMPLETE"
        self._save()
        return result

    def halt(self,reason="MANUAL_KILL_SWITCH"):
        """Persistently disable new BUYs; protective SELLs remain permitted."""
        self.halted=True
        self.halt_reason=reason
        self._save()

    def on_quote(self,symbol,price,volume=None,oi=None):
        """Quote -> protective exit -> optional 3/5 SMA demo entry.
        Demo SMA is NOT a validated strategy. No breakout/retest implementation.
        """
        if symbol not in self.watchlist:return None
        price=D(price)
        if not price.is_finite() or price<=0:raise ValueError("Invalid price")
        self.last[symbol]=price
        if symbol in self.positions:
            p=self.positions[symbol]
            if price<=D(p["stop"]):return self.sell(symbol,price,"STOP_LOSS")
            if price>=D(p["target"]):return self.sell(symbol,price,"TAKE_PROFIT")
        series=self.prices[symbol]
        series.append(price)
        if len(series)>100:del series[:-100]
        if len(series)<6 or symbol in self.positions:return None
        cross=(sum(series[-4:-1])/D(3)<=sum(series[-6:-1])/D(5)
               and sum(series[-3:])/D(3)>sum(series[-5:])/D(5))
        if cross:
            try:return self.buy(symbol,price,price*D("0.99"))
            except (ValueError,HardCheckRejected):return None
        return None

    def report(self,period="all"):
        if period not in ("all","daily","weekly"):raise ValueError("Unknown period")
        today=market_date()
        trades=[t for t in self.trades if period=="all" or
                (period=="daily" and trade_market_date(t["closed"])==today) or
                (period=="weekly" and 0<=(today-trade_market_date(t["closed"])).days<7)]
        wins=sum(D(t["pnl"])>0 for t in trades)
        unrealized=sum((self.last.get(s,D(p["entry"]))-D(p["entry"]))*p["quantity"]
                       for s,p in self.positions.items())
        return dict(period=period,trades=len(trades),wins=wins,
                    win_rate=str(D(wins)*100/len(trades) if trades else D(0)),
                    realized_pnl=str(sum((D(t["pnl"]) for t in trades),D(0))),
                    unrealized_pnl=str(unrealized),cash=str(self.cash),
                    open_positions=len(self.positions),entries_today=self.entries,
                    halted=self.halted,halt_reason=self.halt_reason,
                    learning_records=[dict(symbol=t["symbol"],reason=t["reason"],
                      outcome="WIN" if D(t["pnl"])>0 else "LOSS" if D(t["pnl"])<0 else "FLAT")
                      for t in trades])
