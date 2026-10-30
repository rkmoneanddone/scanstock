"""Offline regression tests for Trade Lab execution and calendar handling."""
import unittest
from datetime import date
from scripts.trade_lab_weekly import replay, trading_session, audit_candles, confirmed_swing_low, structural_targets

PLAN=dict(decision="BUY SETUP",entry=100.0,sl=90.0,tp1=115.0,tp2=125.0)
def bar(day,o,h,l,c):
    return dict(t=day,o=o,h=h,l=l,c=c,v=1000)

class TradeLabTests(unittest.TestCase):
    def test_weekend_filter(self):
        valid,rejected=audit_candles([bar("2026-01-03",100,105,95,102),bar("2026-01-05",100,105,95,102)])
        self.assertEqual(len(valid),1)
        self.assertEqual(rejected,["2026-01-03"])
    def test_entry_stop_same_bar_ambiguous(self):
        result=replay(PLAN,[bar("2026-02-02",100,105,89,102)])
        self.assertEqual(result["status"],"AMBIGUOUS ENTRY BAR")
    def test_gap_entry(self):
        result=replay(PLAN,[bar("2026-02-02",110,112,101,105)])
        self.assertEqual(result["events"][0]["price"],110)
    def test_stop_before_target(self):
        result=replay(PLAN,[bar("2026-02-02",100,110,96,105),
                            bar("2026-02-03",105,120,88,100)])
        self.assertEqual(result["status"],"STOPPED")
    def test_two_targets(self):
        result=replay(PLAN,[bar("2026-02-02",100,110,96,105),
                            bar("2026-02-03",110,116,103,114),
                            bar("2026-02-04",115,127,108,126)])
        self.assertEqual(result["status"],"OPEN")
        self.assertEqual([e["kind"] for e in result["events"]],["ENTRY","TP1","TP2"])
        self.assertAlmostEqual(result["gross_realized_pnl_per_share"],13.2)
        self.assertAlmostEqual(result["remaining_position"],.34)
    def test_structural_targets_do_not_use_future_bars(self):
        dates=["2026-01-%02d"%i for i in range(1,12)]
        bars=[bar(d,100,110,95,100) for d in dates]
        bars[4]["h"]=145
        bars[8]["h"]=170
        known=structural_targets(bars[:8],[],100)
        later=structural_targets(bars,[],100)
        self.assertTrue(any(x["price"]==145 for x in known))
        self.assertFalse(any(x["price"]==170 for x in known))
        self.assertTrue(any(x["price"]==170 for x in later))
    def test_no_structural_target_does_not_fabricate_one(self):
        bars=[bar("2026-01-%02d"%i,100,105,95,100) for i in range(1,8)]
        self.assertEqual(structural_targets(bars,[],110),[])
    def test_unconfirmed_pivot_is_not_used(self):
        bars=[bar("2026-01-%02d"%i,100,110,95,100) for i in range(1,7)]
        bars[4]["l"]=80
        self.assertIsNone(confirmed_swing_low(bars))
if __name__=="__main__":unittest.main()
