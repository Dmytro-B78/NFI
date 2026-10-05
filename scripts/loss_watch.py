#!/usr/bin/env python3
"""
Loss watch: send a Telegram message when the realized loss of an OPEN trade
crosses a multiple of that trade's first-entry margin.

Why: derisk sells + re-grinds can realize more loss than the first stake
(US #144: -112% of first margin, NIGHT -106%), and the dashboard shows only
the loss of the remaining position. This script surfaces the realized part.

Read-only on the freqtrade DB. One-shot: run it from cron. It remembers the
highest threshold already announced per trade in a small JSON state file, so
each threshold is announced once per trade.

Realized loss is computed from the orders table with the weighted-average
cost method (fees and funding ignored, ~1% effect).

Usage:
    python scripts/loss_watch.py [--dry-run]
    DB url is taken from (first found): --db-url, env FREQTRADE__DB_URL,
    "db_url" in the private config (user_data/config-private.json).
    Telegram token/chat id come from the "telegram" block of the same file.
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
CONFIG_PATH = HERE / "loss_watch_config.json"


def realized_and_margin(orders, is_short, leverage):
    """orders: chronological dicts {side, px, filled}. Returns (first_margin, realized_pnl)."""
    entry_side = "sell" if is_short else "buy"
    direction = -1.0 if is_short else 1.0
    qty = avg = realized = 0.0
    first_margin = None
    for o in orders:
        if o["filled"] <= 0:
            continue
        if o["side"] == entry_side:
            if first_margin is None:
                first_margin = o["px"] * o["filled"] / leverage
            avg = (avg * qty + o["px"] * o["filled"]) / (qty + o["filled"])
            qty += o["filled"]
        else:
            realized += direction * (o["px"] - avg) * o["filled"]
            qty -= o["filled"]
    return first_margin, realized


def crossed_level(first_margin, realized, thresholds):
    """Highest threshold (multiple of first margin) the realized loss has reached, else None."""
    if not first_margin or realized >= 0:
        return None
    ratio = -realized / first_margin
    hit = [t for t in sorted(thresholds) if ratio >= t]
    return hit[-1] if hit else None


def load_json(path, default=None):
    if not Path(path).exists():
        if default is not None:
            return default
        sys.exit("FAIL: missing file " + str(path))
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fetch_open_trades(db_url):
    from sqlalchemy import create_engine, text

    engine = create_engine(db_url)
    out = []
    with engine.connect() as conn:
        trades = conn.execute(text(
            "SELECT id, pair, is_short, leverage, enter_tag, open_date FROM trades WHERE is_open"
        )).mappings().all()
        for t in trades:
            rows = conn.execute(text(
                "SELECT ft_order_side AS side, COALESCE(average, price) AS px, filled "
                "FROM orders WHERE ft_trade_id = :tid AND ft_is_open = false AND filled > 0 "
                "ORDER BY COALESCE(order_filled_date, order_date), id"
            ), {"tid": t["id"]}).mappings().all()
            out.append((dict(t), [dict(r) for r in rows]))
    return out


def send_telegram(cfg, tg, text_msg):
    url = "%s/bot%s/sendMessage" % (cfg["telegram_api_base"], tg["token"])
    data = urllib.parse.urlencode({"chat_id": tg["chat_id"], "text": text_msg}).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=cfg["request_timeout_sec"]) as r:
        if r.status != 200:
            raise RuntimeError("telegram HTTP %s" % r.status)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-url", default=os.environ.get("FREQTRADE__DB_URL"))
    ap.add_argument("--dry-run", action="store_true", help="print messages, do not send or save state")
    args = ap.parse_args()
    cfg = load_json(CONFIG_PATH)
    private_path = HERE / cfg["private_config"]
    db_url = args.db_url or (load_json(private_path).get("db_url") if private_path.exists() else None)
    if not db_url:
        sys.exit("FAIL: no db url (use --db-url, env FREQTRADE__DB_URL or db_url in " + str(private_path) + ")")
    state_path = HERE / cfg["state_file"]
    state = load_json(state_path, default={})
    tg = None if args.dry_run else load_json(private_path)["telegram"]

    open_ids = set()
    for trade, orders in fetch_open_trades(db_url):
        tid = str(trade["id"])
        open_ids.add(tid)
        first_margin, realized = realized_and_margin(orders, bool(trade["is_short"]), float(trade["leverage"] or 1.0))
        level = crossed_level(first_margin, realized, cfg["thresholds"])
        if level is None or level <= state.get(tid, 0):
            continue
        msg = cfg["message_template"].format(
            pair=trade["pair"], trade_id=trade["id"], tag=(trade["enter_tag"] or "").strip(),
            loss=-realized, ratio_pct=-realized / first_margin * 100, first_margin=first_margin,
            level_pct=level * 100, open_date=str(trade["open_date"])[:16])
        print(msg)
        if not args.dry_run:
            send_telegram(cfg, tg, msg)
            state[tid] = level

    if not args.dry_run:
        state = {k: v for k, v in state.items() if k in open_ids}
        tmp = str(state_path) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, state_path)


if __name__ == "__main__":
    main()
