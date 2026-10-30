from scanstock.trading.research_report import aggregate_symbol_reports, rank_unseen

def _part(n, wins, mean):
    return {"complete": n, "wins": wins, "mean_r": str(mean), "win_rate": str(wins*100/n) if n else None}

def test_trade_weighted_aggregation_and_stock_breadth():
    data = {
        "A": {"train": _part(1, 1, 1), "unseen": _part(2, 2, 1)},
        "B": {"train": _part(1, 0, -1), "unseen": _part(8, 2, -0.5)},
        "C": {"error": "bad data"},
    }
    result = aggregate_symbol_reports(data)
    assert result["unseen"]["completed_trades"] == 10
    assert result["unseen"]["wins"] == 4
    assert result["unseen"]["win_rate_pct"] == "40"
    assert result["unseen"]["mean_net_r"] == "-0.2"
    assert result["unseen"]["positive_stock_share_pct"] == "50"
    assert result["symbols_with_errors"] == 1
    assert [r["symbol"] for r in rank_unseen(data, minimum_trades=2)] == ["A", "B"]

def test_empty_universe_has_no_invented_metrics():
    result = aggregate_symbol_reports({})
    assert result["unseen"]["mean_net_r"] is None
    assert result["unseen"]["completed_trades"] == 0
