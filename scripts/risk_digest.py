#!/usr/bin/env python3
"""
Risk digest: read-only Telegram reports about open positions and portfolio risk.

Two modes (run both from cron, see risk_digest_config.json for all settings):
  --mode digest  full daily summary, always sent
  --mode alert   silent unless a risk flag is NEW since the previous run

Data comes from the bot REST API on this host (GET only): /status, /balance,
/show_config. Nothing is changed, no orders, no config edits. The script only
reports facts (margin shares, break-even distance, liquidation distance); it
never says close or hold.

Every real run appends one row to the CSV log, so episodes accumulate for
later rule validation.

Usage:
    python scripts/risk_digest.py --mode digest [--dry-run]
    API login and Telegram token/chat id come from the private config
    (user_data/config-private.json, blocks api_server and telegram).
"""

import argparse
import base64
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
CONFIG_PATH = HERE / "risk_digest_config.json"
LOG_COLUMNS = ["ts_utc", "mode", "balance", "peak", "drawdown_pct", "n_open",
               "margin_pct", "uw_margin_pct", "open_total_pnl"]


def load_json(path, default=None):
    p = Path(path)
    if not p.exists():
        if default is not None:
            return default
        sys.exit("FAIL: missing file " + str(p))
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def load_env_file(path):
    """KEY=VALUE lines of the systemd EnvironmentFile; anything else is ignored."""
    env = {}
    p = Path(path)
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip().strip("\"'")
    return env


def apply_env_overrides(private, env):
    """Same rule as freqtrade: FREQTRADE__SECTION__KEY overrides the config value."""
    for section in ("api_server", "telegram"):
        for key in list(private.get(section, {})) + ["username", "password"]:
            name = "FREQTRADE__%s__%s" % (section.upper(), key.upper())
            if name in env and (key in private.get(section, {}) or section == "api_server"):
                private.setdefault(section, {})[key] = env[name]
    return private


def pct(part, whole):
    return part / whole * 100.0 if whole else 0.0


def analyze_trade(t, balance, now_ts):
    margin = float(t.get("stake_amount") or 0.0)
    unreal = float(t.get("profit_abs") or 0.0)
    realized = float(t.get("realized_profit") or 0.0)
    rate = float(t.get("current_rate") or 0.0)
    open_rate = float(t.get("open_rate") or 0.0)
    liq = float(t.get("liquidation_price") or 0.0)
    open_ms = t.get("open_timestamp")
    total = realized + unreal
    return {
        "pair": t.get("pair", "?"), "trade_id": t.get("trade_id"),
        "margin": margin, "margin_pct": pct(margin, balance),
        "realized": realized, "unreal": unreal, "total": total,
        "total_pct": pct(total, balance), "rate": rate,
        # signed move needed from current price to the open rate of the remaining position
        "be_move": (open_rate - rate) / rate * 100.0 if rate and open_rate else None,
        "liq_dist": abs(rate - liq) / rate * 100.0 if rate and liq else None,
        "age_days": (now_ts - open_ms / 1000.0) / 86400.0 if open_ms else 0.0,
    }


def analyze(trades_raw, balance, peak, max_open, cfg, now_ts):
    trades = sorted((analyze_trade(t, balance, now_ts) for t in trades_raw), key=lambda x: x["total"])
    margin = sum(t["margin"] for t in trades)
    uw_margin = sum(t["margin"] for t in trades if t["unreal"] < 0)
    rep = {
        "balance": balance, "peak": peak, "drawdown_pct": pct(peak - balance, peak),
        "n_open": len(trades), "max_open": max_open, "trades": trades,
        "margin": margin, "margin_pct": pct(margin, balance),
        "uw_margin": uw_margin, "uw_margin_pct": pct(uw_margin, balance),
        "unreal": sum(t["unreal"] for t in trades), "realized": sum(t["realized"] for t in trades),
    }
    rep["total"] = rep["unreal"] + rep["realized"]
    rep["flags"] = build_flags(rep, cfg)
    return rep


def build_flags(rep, cfg):
    th, ft = cfg["thresholds"], cfg["flag_templates"]
    flags = []
    if rep["uw_margin_pct"] >= th["underwater_margin_pct_of_balance"]:
        flags.append(("underwater_margin", ft["underwater_margin"].format(
            uw_margin_pct=rep["uw_margin_pct"], thr=th["underwater_margin_pct_of_balance"])))
    for t in rep["trades"]:
        if t["total_pct"] <= -th["trade_total_loss_pct_of_balance"]:
            flags.append(("trade_loss:%s" % t["trade_id"], ft["trade_loss"].format(
                pair=t["pair"], trade_id=t["trade_id"], total_pct=-t["total_pct"],
                thr=th["trade_total_loss_pct_of_balance"])))
        if t["liq_dist"] is not None and t["liq_dist"] < th["liquidation_distance_pct"]:
            flags.append(("liquidation:%s" % t["trade_id"], ft["liquidation"].format(
                pair=t["pair"], trade_id=t["trade_id"], liq=t["liq_dist"],
                thr=th["liquidation_distance_pct"])))
    if rep["drawdown_pct"] >= th["balance_drawdown_pct"]:
        flags.append(("drawdown", ft["drawdown"].format(
            drawdown_pct=rep["drawdown_pct"], thr=th["balance_drawdown_pct"])))
    if rep["margin_pct"] >= th["margin_pct_of_balance"]:
        flags.append(("margin", ft["margin"].format(
            margin_pct=rep["margin_pct"], thr=th["margin_pct_of_balance"])))
    return flags


def trade_line(cfg, t):
    na = cfg["na_text"]
    be = "%+.1f%%" % t["be_move"] if t["be_move"] is not None else na
    liq = "%.0f%%" % t["liq_dist"] if t["liq_dist"] is not None else na
    return cfg["trade_template"].format(be_txt=be, liq_txt=liq, **t)


def clip(cfg, text):
    return text[:cfg["message_max_len"]]


def format_digest(cfg, rep, ts):
    parts = [cfg["header_template"].format(ts=ts, **rep), ""]
    if rep["trades"]:
        parts += [trade_line(cfg, t) for t in rep["trades"]]
    else:
        parts.append(cfg["no_trades_text"])
    parts.append("")
    parts += [text for _, text in rep["flags"]] or [cfg["no_flags_text"]]
    return clip(cfg, "\n".join(parts))


def format_alert(cfg, rep, new_flags, ts):
    parts = [cfg["alert_header_template"].format(ts=ts, **rep), ""]
    parts += [text for _, text in new_flags]
    return clip(cfg, "\n".join(parts))


def decide(cfg, mode, data, state, ts, now_ts):
    """Pure core. Returns (message or None, new_state, log_row)."""
    balance = float(data["balance"])
    if balance <= 0:
        raise ValueError("balance from API is %s: refusing to report" % balance)
    peak = max(float(state.get("peak", cfg["peak_seed_usdt"])), balance)
    rep = analyze(data["trades"], balance, peak, data["max_open"], cfg, now_ts)
    keys = [k for k, _ in rep["flags"]]
    new_state = {"peak": peak, "active_flags": keys if mode == "alert" else state.get("active_flags", [])}
    if mode == "digest":
        message = format_digest(cfg, rep, ts)
    else:
        fresh = [(k, x) for k, x in rep["flags"] if k not in state.get("active_flags", [])]
        message = format_alert(cfg, rep, fresh, ts) if fresh else None
    row = [ts, mode, "%.2f" % balance, "%.2f" % peak, "%.2f" % rep["drawdown_pct"], rep["n_open"],
           "%.2f" % rep["margin_pct"], "%.2f" % rep["uw_margin_pct"], "%.2f" % rep["total"]]
    return message, new_state, row


def http_json(url, headers, timeout, data=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_data(api, timeout):
    host = "127.0.0.1" if api["listen_ip_address"] in ("0.0.0.0", "") else api["listen_ip_address"]
    base = "http://%s:%s/api/v1" % (host, api["listen_port"])
    cred = base64.b64encode(("%s:%s" % (api["username"], api["password"])).encode()).decode()
    token = http_json(base + "/token/login", {"Authorization": "Basic " + cred}, timeout,
                      data=b"", method="POST")["access_token"]
    hdr = {"Authorization": "Bearer " + token}
    return {
        "trades": http_json(base + "/status", hdr, timeout),
        "balance": http_json(base + "/balance", hdr, timeout)["total"],
        "max_open": int(http_json(base + "/show_config", hdr, timeout)["max_open_trades"]),
    }


def send_telegram(cfg, tg, text_msg):
    url = "%s/bot%s/sendMessage" % (cfg["telegram_api_base"], tg["token"])
    body = urllib.parse.urlencode({"chat_id": tg["chat_id"], "text": text_msg}).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=cfg["request_timeout_sec"]) as r:
        if r.status != 200:
            raise RuntimeError("telegram HTTP %s" % r.status)


def append_log(path, row):
    new = not Path(path).exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(LOG_COLUMNS)
        w.writerow(row)


def save_state(path, state):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["digest", "alert"], required=True)
    ap.add_argument("--dry-run", action="store_true", help="print only: no send, no state, no log")
    args = ap.parse_args()
    cfg = load_json(CONFIG_PATH)
    env = dict(load_env_file(HERE / cfg["env_file"]))
    env.update(os.environ)
    private = apply_env_overrides(load_json(HERE / cfg["private_config"]), env)
    state_path, log_path = HERE / cfg["state_file"], HERE / cfg["log_file"]
    state = load_json(state_path, default={})
    data = fetch_data(private["api_server"], cfg["request_timeout_sec"])
    now_ts = time.time()
    ts = datetime.fromtimestamp(now_ts, timezone.utc).strftime("%Y-%m-%d %H:%M")
    message, new_state, row = decide(cfg, args.mode, data, state, ts, now_ts)
    print(message if message else "no new flags, nothing to send")
    if args.dry_run:
        return
    if message:
        send_telegram(cfg, private["telegram"], message)
    save_state(state_path, new_state)
    append_log(log_path, row)


if __name__ == "__main__":
    main()
