#!/usr/bin/env python3
"""Plain-assert tests for loss_watch core logic. Run: python scripts/test_loss_watch.py"""
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from loss_watch import crossed_level, realized_and_margin

TH = [0.5, 1.0, 1.5]


def approx(a, b, tol=1e-6):
    assert abs(a - b) <= tol, "%r != %r" % (a, b)


# long: buy 100 @ 10 with 3x -> first margin 1000/3; sell 50 @ 8 -> realized -100
fm, rl = realized_and_margin([{"side": "buy", "px": 10.0, "filled": 100}, {"side": "sell", "px": 8.0, "filled": 50}], False, 3.0)
approx(fm, 1000 / 3)
approx(rl, -100.0)
assert crossed_level(fm, rl, TH) is None  # 30% of first margin

# short mirror: sell 100 @ 10, buy back 50 @ 12 -> realized -100
fm, rl = realized_and_margin([{"side": "sell", "px": 10.0, "filled": 100}, {"side": "buy", "px": 12.0, "filled": 50}], True, 3.0)
approx(rl, -100.0)

# averaging: buy 100 @ 10, buy 100 @ 8 (avg 9), sell 100 @ 6 -> -300 (90% of 333.3)
fm, rl = realized_and_margin([{"side": "buy", "px": 10.0, "filled": 100}, {"side": "buy", "px": 8.0, "filled": 100}, {"side": "sell", "px": 6.0, "filled": 100}], False, 3.0)
approx(rl, -300.0)
assert crossed_level(fm, rl, TH) == 0.5

assert crossed_level(100.0, -100.0, TH) == 1.0
assert crossed_level(100.0, -149.0, TH) == 1.0
assert crossed_level(100.0, -150.0, TH) == 1.5
assert crossed_level(100.0, 20.0, TH) is None
assert crossed_level(None, 0.0, TH) is None
print("synthetic tests OK")

# regression on the 30.09.2026 analysis data (local, untracked); skipped if absent
data = Path(__file__).parent.parent / "user_data" / "data_research" / "analysis_20260930"
if (data / "derisk_orders.csv").exists():
    short_ids = {49, 99}
    by_id = {}
    for r in csv.DictReader(open(data / "derisk_orders.csv")):
        by_id.setdefault(int(r["tid"]), []).append({"side": r["side"], "px": float(r["px"]), "filled": float(r["filled"])})
    expect_over_100 = {24, 25, 27, 109, 144, 13}
    expect_none = {74, 67, 37}  # below 50% of first margin
    for tid, orders in by_id.items():
        # worst point of the path: the live script runs periodically, so it sees the prefix states
        lvl = None
        for k in range(1, len(orders) + 1):
            fm, rl = realized_and_margin(orders[:k], tid in short_ids, 3.0)
            hit = crossed_level(fm, rl, TH)
            if hit is not None and (lvl is None or hit > lvl):
                lvl = hit
        if tid in expect_over_100:
            assert lvl is not None and lvl >= 1.0, (tid, lvl)
        if tid in expect_none:
            assert lvl is None, (tid, lvl)
    print("regression on 14 live derisk trades OK")
else:
    print("regression data absent - skipped")
