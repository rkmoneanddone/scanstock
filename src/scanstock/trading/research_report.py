"""Aggregate out-of-sample strategy evidence without treating stocks as independent trades."""
from decimal import Decimal
from .learning import D

def aggregate_symbol_reports(symbol_reports):
    totals = {part: {"stocks_with_trades": 0, "trades": 0, "wins": 0, "weighted_r_sum": D(0), "positive_stocks": 0} for part in ("train", "unseen")}
    errors = {}
    for symbol, report in symbol_reports.items():
        if "error" in report:
            errors[symbol] = report["error"]
            continue
        for part in ("train", "unseen"):
            stats = report.get(part, {})
            count = int(stats.get("complete", 0))
            if count <= 0:
                continue
            target = totals[part]
            target["stocks_with_trades"] += 1
            target["trades"] += count
            target["wins"] += int(stats.get("wins", 0))
            mean = D(stats["mean_r"])
            target["weighted_r_sum"] += mean * count
            if mean > 0:
                target["positive_stocks"] += 1
    result = {}
    for part, stats in totals.items():
        n = stats["trades"]
        stocks = stats["stocks_with_trades"]
        result[part] = {
            "completed_trades": n,
            "stocks_with_trades": stocks,
            "wins": stats["wins"],
            "win_rate_pct": str(D(stats["wins"]) * 100 / n) if n else None,
            "mean_net_r": str(stats["weighted_r_sum"] / n) if n else None,
            "positive_stock_share_pct": str(D(stats["positive_stocks"]) * 100 / stocks) if stocks else None,
        }
    return {"train": result["train"], "unseen": result["unseen"],
            "symbols_reported": len(symbol_reports), "symbols_with_errors": len(errors),
            "errors": errors}

def rank_unseen(symbol_reports, minimum_trades=5):
    ranked = []
    for symbol, report in symbol_reports.items():
        if "error" in report:
            continue
        stats = report.get("unseen", {})
        count = int(stats.get("complete", 0))
        if count < minimum_trades or stats.get("mean_r") is None:
            continue
        ranked.append({"symbol": symbol, "trades": count, "wins": int(stats["wins"]),
                       "win_rate_pct": stats["win_rate"],
                       "mean_net_r": stats["mean_r"]})
    return sorted(ranked, key=lambda x: (D(x["mean_net_r"]), x["trades"]), reverse=True)
