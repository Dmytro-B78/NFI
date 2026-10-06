"""Mark-to-market equity curve for a freqtrade backtest result zip.

Rebuilds every position from the per-fill orders, prices open positions on
5m candles, and reports drawdown that includes unrealized losses.
Read-only analysis; touches no strategy or config files.
"""
import argparse, json, os, sys, zipfile
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
STEP_MS = 5 * 60 * 1000  # backtest timeframe is 5m (taken from result below)

ap = argparse.ArgumentParser()
ap.add_argument("--zip", default=os.path.join(REPO, "user_data", "backtest_results", "backtest-result-2026-09-23_12-16-10.zip"))
ap.add_argument("--data", default=os.path.join(REPO, "user_data", "data", "binance", "futures"))
ap.add_argument("--out", default=HERE)
args = ap.parse_args()


def load_result(path):
    zf = zipfile.ZipFile(path)
    name = [n for n in zf.namelist() if n.endswith(".json") and "config" not in n and "meta" not in n][0]
    d = json.load(zf.open(name))
    strat = list(d["strategy"].keys())[0]
    return d["strategy"][strat]


def load_candles(pair):
    f = os.path.join(args.data, pair.replace("/", "_").replace(":", "_") + "-5m-futures.feather")
    if not os.path.exists(f):
        sys.exit("FAIL: no 5m data for " + pair + " at " + f)
    c = pd.read_feather(f)
    c["ts"] = (c["date"] - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta("1ms")
    return c.set_index("ts")[["low", "high", "close"]]


res = load_result(args.zip)
trades = res["trades"]
assert res["timeframe"] == "5m", "script assumes 5m backtest timeframe"
start_bal = res["starting_balance"]
t0 = min(t["open_timestamp"] for t in trades) // STEP_MS * STEP_MS
t1 = max(t["close_timestamp"] for t in trades) // STEP_MS * STEP_MS
n = (t1 - t0) // STEP_MS + 1
idx = lambda ts: int((ts - t0) // STEP_MS)

realized = np.zeros(n)        # realized pnl net of fees, step increments
unreal_close = np.zeros(n)    # unrealized at bar close
unreal_worst = np.zeros(n)    # unrealized at worst price in bar
margin_open = np.zeros(n)     # margin tied in all open positions
margin_under = np.zeros(n)    # margin tied in positions that are underwater (close)
n_under = np.zeros(n)
rows = []
check_gross = {}

for t in trades:
    d = -1.0 if t["is_short"] else 1.0
    lev = t["leverage"]
    ev = sorted(t["orders"], key=lambda o: o["order_filled_timestamp"])
    qty = avg = pnl = fees = 0.0
    states = []  # (bar index, qty after, avg after)
    for o in ev:
        a, p, j = o["amount"], o["safe_price"], idx(o["order_filled_timestamp"])
        if o["ft_is_entry"]:
            fee = t["fee_open"] * a * p
            avg = (avg * qty + p * a) / (qty + a)
            qty += a
            inc = -fee
        else:
            fee = t["fee_close"] * a * p
            inc = d * (p - avg) * a - fee
            qty -= a
        realized[j] += inc
        pnl += inc
        fees += fee
        states.append((j, qty if qty > 1e-9 else 0.0, avg))
    jc = idx(t["close_timestamp"])
    check_gross[t["pair"] + str(t["open_timestamp"])] = (pnl, t["profit_abs"], t["funding_fees"])
    realized[jc] += 0.0  # funding added later after sign detection
    c = load_candles(t["pair"])
    j0 = states[0][0]
    ser = c.reindex(c.index.union(pd.Index([t0 + k * STEP_MS for k in range(j0, jc + 1)]))).loc[t0 + j0 * STEP_MS: t0 + jc * STEP_MS]
    ser = ser.ffill()
    ser = ser.iloc[:jc - j0 + 1]
    q = np.zeros(jc - j0 + 1); av = np.zeros(jc - j0 + 1)
    for k, (j, qq, aa) in enumerate(states):
        j_end = (states[k + 1][0] if k + 1 < len(states) else jc + 1) - j0
        q[j - j0:j_end] = qq; av[j - j0:j_end] = aa
    worst = ser["low"].values if d > 0 else ser["high"].values
    u_c = d * (ser["close"].values - av) * q
    u_w = d * (worst - av) * q
    sl = slice(j0, jc + 1)
    unreal_close[sl] += u_c
    unreal_worst[sl] += u_w
    mrg = q * av / lev
    margin_open[sl] += mrg
    margin_under[sl] += np.where(u_c < 0, mrg, 0.0)
    n_under[sl] += (u_c < 0)
    first_entry_margin = ev[0]["amount"] * ev[0]["safe_price"] / lev
    rows.append({"pair": t["pair"], "tag": t["enter_tag"], "side": "short" if t["is_short"] else "long",
                 "open": t["open_date"], "close": t["close_date"], "days": round((jc - j0) * STEP_MS / 86400000, 1),
                 "n_orders": len(ev), "profit_abs": round(t["profit_abs"], 3),
                 "max_unreal_loss": round(float(u_w.min()), 2),
                 "max_unreal_loss_pct_first_margin": round(float(u_w.min()) / first_entry_margin * 100, 1),
                 "bars_underwater_pct": round(float((u_c < 0).mean()) * 100, 1),
                 "peak_margin": round(float(mrg.max()), 2)})

# funding sign auto-detect: profit_abs should equal pnl +/- funding
diff = np.array([v[1] - v[0] for v in check_gross.values()])
fund = np.array([v[2] for v in check_gross.values()])
err_minus = np.abs(diff + fund).mean(); err_plus = np.abs(diff - fund).mean()
sgn = -1.0 if err_minus < err_plus else 1.0
err = min(err_minus, err_plus)
print(f"funding sign {sgn:+.0f}, mean abs per-trade reconstruction error {err:.4f} USDT")
if err > 0.05:
    sys.exit("FAIL: per-trade reconstruction does not match profit_abs")
for t in trades:
    realized[idx(t["close_timestamp"])] += sgn * t["funding_fees"]

cum = start_bal + np.cumsum(realized)
eq_close = cum + unreal_close
eq_worst = cum + unreal_worst
print(f"final realized equity {cum[-1]:.3f} vs backtest final_balance {res['final_balance']:.3f}")
assert abs(cum[-1] - res["final_balance"]) < 1.0, "FAIL: final balance mismatch"


def max_dd(eq):
    peak = np.maximum.accumulate(eq)
    dd = eq - peak
    k = int(dd.argmin())
    return dd[k], dd[k] / peak[k] * 100, int(np.argmax(eq[:k + 1])), k


dt = lambda j: str(pd.Timestamp(t0 + j * STEP_MS, unit="ms", tz="UTC"))[:16]
out = {}
for name, eq in (("equity_at_close", eq_close), ("equity_at_worst_price", eq_worst), ("realized_only", cum)):
    a, pct, kp, k = max_dd(eq)
    out[name] = {"max_dd_usdt": round(float(a), 2), "max_dd_pct_of_peak": round(float(pct), 2), "peak_at": dt(kp), "trough_at": dt(k)}
k = int(unreal_worst.argmin())
out["worst_unrealized"] = {"usdt": round(float(unreal_worst[k]), 2), "at": dt(k), "open_margin": round(float(margin_open[k]), 2),
                           "equity_then_worst": round(float(eq_worst[k]), 2), "positions_underwater_at_close": int(n_under[k])}
k2 = int(margin_under.argmax())
out["max_margin_stuck_underwater"] = {"usdt": round(float(margin_under[k2]), 2), "at": dt(k2), "share_of_equity_pct": round(float(margin_under[k2] / eq_close[k2] * 100), 1)}
out["max_simultaneous_underwater"] = int(n_under.max())
out["start_balance"] = start_bal
print(json.dumps(out, indent=2, ensure_ascii=False))

os.makedirs(args.out, exist_ok=True)
with open(os.path.join(args.out, "summary.json"), "w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
h = 12  # 12 x 5m bars = hourly output
cut = n // h * h
pd.DataFrame({"time": [dt(j) for j in range(0, cut, h)], "realized_equity": cum[:cut:h].round(2), "equity_close": eq_close[:cut:h].round(2),
              "equity_worst": eq_worst[:cut:h].round(2), "unreal_close": unreal_close[:cut:h].round(2),
              "margin_open": margin_open[:cut:h].round(2), "margin_underwater": margin_under[:cut:h].round(2),
              "n_underwater": n_under[:cut:h]}).to_csv(os.path.join(args.out, "mtm_hourly.csv"), index=False)
pd.DataFrame(rows).sort_values("max_unreal_loss").to_csv(os.path.join(args.out, "mtm_trades.csv"), index=False)
print("saved to", args.out)
