"""Entry-phase study: does the market phase at entry predict how bad a trade gets?
Read-only research. Pools backtest trades from three windows (no overlap), builds
entry-time features from 1h candles, compares train (first half by time) vs test.
"""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA = os.path.join(ROOT, "data", "binance", "futures")
MTM = os.path.join(ROOT, "data_research", "mtm_20261006")
BAD = -20.0          # bad trade: worst unrealized loss <= -20% of first margin
SPLIT_Q = 0.5        # train/test split by time
N_PERM = 3000
rng = np.random.default_rng(7)

def load():
    a = pd.read_csv(os.path.join(MTM, "long_anchor", "mtm_trades.csv"), parse_dates=["open", "close"])
    b = pd.read_csv(os.path.join(MTM, "apr_slots8", "mtm_trades.csv"), parse_dates=["open", "close"])
    c = pd.read_csv(os.path.join(MTM, "slots_8", "mtm_trades.csv"), parse_dates=["open", "close"])
    cut = pd.Timestamp("2026-04-03", tz="UTC")
    a = a[a.open < cut].assign(src="anchor")
    return pd.concat([a, b.assign(src="apr"), c.assign(src="jul")], ignore_index=True)

_cache = {}
def candles(pair):
    if pair not in _cache:
        f = os.path.join(DATA, pair.replace("/", "_").replace(":", "_") + "-1h-futures.feather")
        _cache[pair] = pd.read_feather(f).set_index("date") if os.path.exists(f) else None
    return _cache[pair]

def feats(h, ts):
    h = h[h.index < ts.floor("h")]          # only fully closed candles before entry
    if len(h) < 170:
        return None
    w7, w3 = h.iloc[-168:], h.iloc[-72:]
    c = h["close"].iloc[-1]
    lo7, hi7 = w7["low"].min(), w7["high"].max()
    return {
        "ret24": c / h["close"].iloc[-25] - 1, "ret72": c / h["close"].iloc[-73] - 1,
        "pos7d": (c - lo7) / (hi7 - lo7) if hi7 > lo7 else np.nan,
        "dd_high7d": c / hi7 - 1, "up_from_low72": c / w3["low"].min() - 1,
        "rng72": w3["high"].max() / w3["low"].min() - 1,
    }

def build():
    d = load()
    btc = candles("BTC/USDT:USDT")
    rows = []
    for r in d.itertuples():
        h = candles(r.pair)
        if h is None:
            continue
        f = feats(h, r.open)
        fb = feats(btc, r.open)
        if f is None or fb is None:
            continue
        f.update({("btc_" + k): v for k, v in fb.items() if k in ("ret24", "ret72", "pos7d")})
        f.update(open=r.open, pair=r.pair, side=r.side, worst=r.max_unreal_loss_pct_first_margin, src=r.src)
        rows.append(f)
    return pd.DataFrame(rows).sort_values("open").reset_index(drop=True)

def spearman(x, y):
    rx = pd.Series(np.asarray(x)).rank().values
    ry = pd.Series(np.asarray(y)).rank().values
    return float(np.corrcoef(rx, ry)[0, 1])

def perm_p(x, y, rho):
    rx = pd.Series(np.asarray(x)).rank().values
    ry = pd.Series(np.asarray(y)).rank().values
    cnt = 0
    for _ in range(N_PERM):
        if abs(np.corrcoef(rx, rng.permutation(ry))[0, 1]) >= abs(rho):
            cnt += 1
    return (cnt + 1) / (N_PERM + 1)

def report(df, side):
    df = df[df.side == side].dropna()
    k = int(len(df) * SPLIT_Q)
    tr, te = df.iloc[:k], df.iloc[k:]
    print("\n=== %s: n=%d (train %d to %s | test %d to %s), bad share train %.0f%% test %.0f%%" % (
        side, len(df), len(tr), str(tr.open.max())[:10], len(te), str(te.open.max())[:10],
        (tr.worst <= BAD).mean() * 100, (te.worst <= BAD).mean() * 100))
    cols = ["ret24", "ret72", "pos7d", "dd_high7d", "up_from_low72", "rng72", "btc_ret24", "btc_ret72", "btc_pos7d"]
    print("%-14s %9s %9s %9s  note" % ("feature", "rho_train", "rho_test", "perm_p_te"))
    for c in cols:
        r1 = spearman(tr[c], tr.worst)
        r2 = spearman(te[c], te.worst)
        p = perm_p(te[c].values, te.worst.values, r2)
        note = "SAME SIGN, p<0.05" if (np.sign(r1) == np.sign(r2) and p < 0.05) else ""
        print("%-14s %9.3f %9.3f %9.3f  %s" % (c, r1, r2, p, note))
    return df

if __name__ == "__main__":
    df = build()
    df.to_csv(os.path.join(os.path.dirname(__file__), "entry_features.csv"), index=False)
    print("trades with features:", len(df), "by src", df.src.value_counts().to_dict(), "by side", df.side.value_counts().to_dict())
    for s in ("long", "short"):
        report(df, s)
