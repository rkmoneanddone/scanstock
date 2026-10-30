"""One long-only RSI recovery -> MA retest -> price confirmation research strategy.

Signal is determined exclusively at the close of completed candles. No order execution.
"""
from .learning import D, evaluate_setup, validate_bars

def rsi_sma(bars, rsi_period=14, ma_period=14):
    if rsi_period<2 or ma_period<2:raise ValueError("Periods must be >= 2")
    changes=[bars[i].close-bars[i-1].close for i in range(1,len(bars))]
    rsis=[None]*len(bars)
    if len(changes)<rsi_period:return rsis,[None]*len(bars)
    gains=[max(d,D(0)) for d in changes]
    losses=[max(-d,D(0)) for d in changes]
    gain=sum(gains[:rsi_period],D(0))/rsi_period
    loss=sum(losses[:rsi_period],D(0))/rsi_period
    def value(g,l):
        if l==0:return D(100) if g>0 else D(50)
        return D(100)-D(100)/(D(1)+g/l)
    rsis[rsi_period]=value(gain,loss)
    for i in range(rsi_period+1,len(bars)):
        gain=(gain*(rsi_period-1)+gains[i-1])/rsi_period
        loss=(loss*(rsi_period-1)+losses[i-1])/rsi_period
        rsis[i]=value(gain,loss)
    mas=[None]*len(bars)
    for i in range(rsi_period+ma_period-1,len(bars)):
        mas[i]=sum(rsis[i-ma_period+1:i+1],D(0))/ma_period
    return rsis,mas

def ema_alignment(bars):
    """Causal close-based EMA 9 > 21 > 50 > 200; unavailable until 200 closes."""
    periods=(9,21,50,200)
    aligned=[False]*len(bars)
    values={}
    for period in periods:
        series=[None]*len(bars)
        if len(bars)>=period:
            ema=sum((b.close for b in bars[:period]),D(0))/D(period)
            series[period-1]=ema
            alpha=D(2)/D(period+1)
            for i in range(period,len(bars)):
                ema=alpha*bars[i].close+(D(1)-alpha)*ema
                series[i]=ema
        values[period]=series
    for i in range(199,len(bars)):
        aligned[i]=values[9][i]>values[21][i]>values[50][i]>values[200][i]
    return aligned

def detect_rsi_retests(symbol,bars,rsi_period=14,ma_period=14,retest_window=10,
                       tolerance_pct="5",horizon=5,strict_retest=False,extension_pct="5"):
    """Fresh crossover, later retest near RSI SMA, then bullish RSI and price close.

    RSI retest must occur on a candle AFTER crossover; confirmation on a later candle.
    RSI must stay above its MA at retest and confirmation (strict hold).
    """
    validate_bars(bars)
    if retest_window<2 or horizon<1 or D(tolerance_pct)<0 or D(extension_pct)<0:raise ValueError("Invalid parameters")
    rsis,mas=rsi_sma(bars,rsi_period,ma_period)
    trend_aligned=ema_alignment(bars)
    records=[]
    state=None
    for i in range(1,len(bars)):
        if rsis[i] is None or mas[i] is None or rsis[i-1] is None or mas[i-1] is None:continue
        cross=rsis[i-1]<=mas[i-1] and rsis[i]>mas[i]
        if state and (i-state["cross"]>retest_window or rsis[i]<mas[i]):
            state=None
        if state and i>state["cross"]:
            # Extension must occur before the retest candle, never on that candle.
            was_extended=state["extended"]
            distance=abs(rsis[i]-mas[i])/max(mas[i],D("0.000001"))*D(100)
            if state["retest"] is None:
                if (rsis[i]>=mas[i] and distance<=D(tolerance_pct)
                    and (not strict_retest or (was_extended and rsis[i]<rsis[i-1]))):
                    state["retest"]=i
                    state["swing_low"]=bars[i].low
            elif i>state["retest"]:
                state["swing_low"]=min(state["swing_low"],bars[i].low)
                if (rsis[i]>rsis[i-1] and rsis[i]>mas[i]
                    and bars[i].close>bars[i-1].high and trend_aligned[i]):
                    if i+1>=len(bars):
                        records.append(dict(symbol=symbol,setup="RSI_MA_RETEST_STRICT_1D" if strict_retest else "RSI_MA_RETEST_1D",
                                            signal_at=bars[i].timestamp,status="PENDING",
                                            reason="NO_ENTRY_CANDLE"))
                    else:
                        entry=bars[i+1].open
                        stop=min(bars[j].low for j in range(state["retest"],i+1))
                        event=dict(symbol=symbol,setup=("RSI_MA_RETEST_STRICT_1D" if strict_retest else "RSI_MA_RETEST_1D"),
                                   cross_at=bars[state["cross"]].timestamp,
                                   retest_at=bars[state["retest"]].timestamp,
                                   signal_at=bars[i].timestamp,entry_at=bars[i+1].timestamp,
                                   entry=str(entry),stop=str(stop),
                                   rsi=str(rsis[i]),rsi_sma=str(mas[i]))
                        if entry<=stop:
                            event.update(status="SKIPPED",reason="ENTRY_AT_OR_BELOW_STOP")
                        else:
                            target=entry+D(2)*(entry-stop)
                            event["target"]=str(target)
                            result=evaluate_setup(symbol,event["setup"],i,bars,entry,stop,target,horizon)
                            event.update(result)
                            event["status"]="COMPLETE" if result["complete"] else "PENDING"
                        records.append(event)
                    state=None
        if state and i>state["cross"] and state["retest"] is None:
            state["extended"] = state["extended"] or rsis[i]>mas[i]*(D(1)+D(extension_pct)/D(100))
        if cross and state is None:
            state={"cross":i,"retest":None,"swing_low":None,"extended":False}
    return records
