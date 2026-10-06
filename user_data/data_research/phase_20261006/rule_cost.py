"""Price/benefit of a 'careful mode' rule on the test half. Rule cutoffs come from TRAIN only."""
import os
import numpy as np
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
MTM = os.path.join(HERE, "..", "mtm_20261006")
f = pd.read_csv(os.path.join(HERE, "entry_features.csv"), parse_dates=["open"])
srcs = {"anchor": "long_anchor", "apr": "apr_slots8", "jul": "slots_8"}
mt = []
for k, d in srcs.items():
    t = pd.read_csv(os.path.join(MTM, d, "mtm_trades.csv"), parse_dates=["open"])
    t["src"] = k
    mt.append(t)
mt = pd.concat(mt)
m = f.merge(mt[["pair", "open", "src", "profit_abs", "max_unreal_loss", "peak_margin"]], on=["pair", "open", "src"], how="left")
L = m[m.side == "long"].dropna(subset=["profit_abs", "btc_pos7d", "rng72"]).sort_values("open").reset_index(drop=True)
k = len(L) // 2
tr, te = L.iloc[:k], L.iloc[k:]
print("long trades", len(L), "train", len(tr), "test", len(te))

def cost(name, flag_fn, d, label):
    flag = flag_fn(d)
    stress = -d.max_unreal_loss.sum()                 # positive USDT of worst unrealized loss
    profit = d.profit_abs.sum()
    s_rem = 0.5 * -d.loc[flag, "max_unreal_loss"].sum() / stress * 100 if stress else 0
    p_lost = 0.5 * d.loc[flag, "profit_abs"].sum() / profit * 100 if profit else 0
    print("%-34s %-6s flagged %3d (%2.0f%%) | stress removed %5.1f%% | profit given up %5.1f%%" % (
        name, label, flag.sum(), flag.mean() * 100, s_rem, p_lost))

q = {c: tr[c].quantile(0.67) for c in ("btc_pos7d", "rng72", "btc_ret72", "up_from_low72")}
rules = {
    "btc_pos7d >= train p67": lambda d: d.btc_pos7d >= q["btc_pos7d"],
    "rng72 >= train p67": lambda d: d.rng72 >= q["rng72"],
    "btc_ret72 >= train p67": lambda d: d.btc_ret72 >= q["btc_ret72"],
    "either btc_pos7d or rng72": lambda d: (d.btc_pos7d >= q["btc_pos7d"]) | (d.rng72 >= q["rng72"]),
    "both btc_pos7d and rng72": lambda d: (d.btc_pos7d >= q["btc_pos7d"]) & (d.rng72 >= q["rng72"]),
}
print("cutoffs:", {a: round(b, 3) for a, b in q.items()})
for n, fn in rules.items():
    cost(n, fn, tr, "TRAIN"); cost(n, fn, te, "TEST")
te2 = te[~te.pair.str.startswith("US/")]
print("--- TEST without US (single worst trade removed) ---")
for n, fn in rules.items():
    cost(n, fn, te2, "TEST-noUS")
