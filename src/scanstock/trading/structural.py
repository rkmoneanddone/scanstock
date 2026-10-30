"""Causal, price-structure exits for daily OHLCV research. No order authority."""
from decimal import Decimal
from .learning import D

def structural_levels(bars, signal_index, entry, lookback=120, swing_span=2, min_rr=1):
    """Levels only from completed candles through signal_index; next-open entry supplied."""
    if signal_index < 2*swing_span+1:
        return None, "INSUFFICIENT_HISTORY"
    history=bars[max(0,signal_index-lookback+1):signal_index+1]
    lows=[]; highs=[]
    for k in range(swing_span,len(history)-swing_span):
        pivot=history[k]
        neighbors=history[k-swing_span:k]+history[k+1:k+swing_span+1]
        if all(pivot.low < b.low for b in neighbors): lows.append(pivot.low)
        if all(pivot.high > b.high for b in neighbors): highs.append(pivot.high)
    # Strictly use support below entry; the nearest confirmed swing low is the invalidation.
    supports=[p for p in lows if p<entry]
    stop=max(supports) if supports else None
    if stop is None or stop<=0:
        return None,"NO_CONFIRMED_SUPPORT"
    risk=entry-stop
    # Do not move a structural stop to manufacture acceptable risk.
    # Reject stops smaller than market noise, tick-size or modeled round-trip fees.
    true_ranges=[]
    for k in range(max(1,len(history)-15),len(history)):
        bar=history[k];previous=history[k-1].close
        true_ranges.append(max(bar.high-bar.low,abs(bar.high-previous),abs(bar.low-previous)))
    atr14=sum(true_ranges,Decimal(0))/D(len(true_ranges)) if true_ranges else D(0)
    min_distance=max(entry*D("0.005"),atr14*D("0.5"),entry*D("0.002")*D("2"))
    if risk<min_distance:
        return None,"STOP_TOO_TIGHT"
    if risk<=0:
        return None,"INVALID_RISK"
    resistances=sorted(set(p for p in highs if p>entry))
    if resistances:
        target=resistances[0]; target_type="PREVIOUS_SWING_HIGH"
    else:
        # Fib 1.618 extension from the most recent confirmed upswing.
        # Both anchors are confirmed pivots inside the historical window.
        confirmed_highs=[(k,history[k].high) for k in range(swing_span,len(history)-swing_span)
                         if all(history[k].high>b.high for b in
                                history[k-swing_span:k]+history[k+1:k+swing_span+1])]
        confirmed_lows=[(k,history[k].low) for k in range(swing_span,len(history)-swing_span)
                        if all(history[k].low<b.low for b in
                               history[k-swing_span:k]+history[k+1:k+swing_span+1])]
        swings=[(lk,lp,hk,hp) for hk,hp in confirmed_highs for lk,lp in confirmed_lows
                if lk<hk and hp>lp]
        if not swings:
            return None,"NO_CONFIRMED_FIB_SWING"
        lk,lo,hk,hi=max(swings,key=lambda x:(x[2],x[0]))
        target=hi+(hi-lo)*D("0.618")
        target_type="FIB_1_618_RANGE_EXTENSION"
        if target<=entry:
            return None,"FIB_TARGET_BELOW_ENTRY"
    rr=(target-entry)/risk
    if rr<D(min_rr):
        return None,"INSUFFICIENT_REWARD_RISK"
    return {"stop":stop,"target":target,"target_type":target_type,
            "initial_rr":rr,"support_type":"CONFIRMED_SWING_LOW",
            "lookback":lookback,"swing_span":swing_span},None

def structural_trade(symbol,setup,bars,signal_index,fee_bps=10,min_rr=1):
    """Enter next open; stop-first on ambiguous daily candles; no time-based forced exit."""
    if signal_index>=len(bars)-1:
        return {"symbol":symbol,"setup":setup,"signal_at":bars[signal_index].timestamp,
                "status":"PENDING","reason":"NO_NEXT_OPEN"}
    entry_index=signal_index+1
    entry=bars[entry_index].open
    base={"symbol":symbol,"setup":setup,"signal_at":bars[signal_index].timestamp,
          "entry_at":bars[entry_index].timestamp,"entry":str(entry)}
    levels,reason=structural_levels(bars,signal_index,entry,min_rr=min_rr)
    if reason:
        return {**base,"status":"SKIPPED","reason":reason}
    stop=levels["stop"];target=levels["target"];risk=entry-stop
    base.update(stop=str(stop),target=str(target),target_type=levels["target_type"],
                support_type=levels["support_type"],initial_rr=str(levels["initial_rr"]))
    for j in range(entry_index,len(bars)):
        candle=bars[j]
        exit_price=None; outcome=None
        if candle.open<=stop:
            exit_price=candle.open;outcome="STOP_GAP"
        elif candle.open>=target:
            exit_price=candle.open;outcome="TARGET_GAP"
        elif candle.low<=stop:
            exit_price=stop;outcome="STOP"
        elif candle.high>=target:
            exit_price=target;outcome="TARGET"
        if exit_price is not None:
            fee=(entry+exit_price)*D(fee_bps)/D(10000)
            return {**base,"status":"COMPLETE","complete":True,
                    "exit_at":candle.timestamp,"exit_index":j,
                    "exit_price":str(exit_price),"outcome":outcome,
                    "holding_candles":j-entry_index+1,
                    "r_multiple":str((exit_price-entry-fee)/risk)}
    return {**base,"status":"PENDING","complete":False,
            "reason":"OPEN_AT_DATA_END","holding_candles":len(bars)-entry_index}

def evaluate_signals(symbol,setup,bars,indices,fee_bps=10,min_rr=1):
    """At most one position per symbol per setup, through exit bar."""
    events=[];next_allowed=0
    for i in indices:
        if i<next_allowed:continue
        result=structural_trade(symbol,setup,bars,i,fee_bps,min_rr)
        events.append(result)
        if result["status"]=="COMPLETE":
            next_allowed=result["exit_index"]+1
        elif result["status"]=="PENDING":
            break
    return events
