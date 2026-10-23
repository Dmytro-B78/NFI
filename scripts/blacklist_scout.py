#!/usr/bin/env python3
"""
Blacklist scout: finds blacklist candidates on our own Binance data and keeps
them out of the running bot.

Every run (cron, hourly):
  1. scans Binance USDT-M perpetuals that can reach the whitelist (top N by
     24h volume + current whitelist + open trades), see scout_detect.py;
  2. decides per pair: temporary block, permanent block, or message only,
     see scout_tiers.py;
  3. applies blocks to the RUNNING bot via POST /api/v1/blacklist and
     releases expired temporary blocks via DELETE (only pairs it added
     itself). The bot drops these runtime entries on restart; the next run
     puts them back. Files are never edited here: permanent entries go into
     user_data/blacklist-binance.json locally with scripts/persist_blacklist.ps1;
  4. sends Telegram only when something changed, plus a daily summary of all
     temporary and permanent blocks. Any error is sent to Telegram too.
With "shadow_mode": true in the config the DETECTOR blocks are not sent to
the bot: the scout keeps the same state, log and messages as if it had
blocked (such items are tagged in the messages), so its accuracy can be checked before it is
allowed to act. The author's blacklist is governed separately by
"author_sync_live": new author entries are blocked in the bot as soon as they
appear, until they are persisted into the file (see scout_author.py).

Usage:
    python scripts/blacklist_scout.py [--dry-run]
    python scripts/blacklist_scout.py --sync
      light run (cron, every few minutes): author list + put blocks back
      after a bot restart; no candles, no detectors, no daily summary.
    python scripts/blacklist_scout.py --asof 2026-10-15T23:00 --pairs NXPC,DOS
      replay as of a past UTC time: only candles closed before it, price
      detectors only, no bot API, no state, no Telegram (print only).
"""

import argparse
import base64
import csv
import json
import os
import re
import sys
import time
import traceback
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from risk_digest import (apply_env_overrides, http_json, load_env_file,  # noqa: E402
                         load_json, save_state, send_telegram)
import scout_author as sa  # noqa: E402
import scout_detect as sd  # noqa: E402
import scout_tiers as st  # noqa: E402

CONFIG_PATH = HERE / "blacklist_scout_config.json"
LOG_COLUMNS = ["ts_utc", "pair", "event", "price", "keys", "text"]


def with_retry(cfg, fn, *args):
    for attempt in range(cfg["retry_attempts"]):
        try:
            return fn(*args)
        except OSError:  # URLError, resets, timeouts
            if attempt + 1 == cfg["retry_attempts"]:
                raise
            time.sleep(cfg["retry_pause_sec"])


def get_json(cfg, url):
    return with_retry(cfg, http_json, url, {}, cfg["request_timeout_sec"])


def get_text(cfg, url):
    def fetch():
        with urllib.request.urlopen(url, timeout=cfg["request_timeout_sec"]) as r:
            return r.read().decode("utf-8")
    return with_retry(cfg, fetch)


def binance_klines(cfg):
    def fetch(symbol, interval, limit, end_ms=None):
        time.sleep(cfg["request_pause_sec"])
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if end_ms is not None:
            params["endTime"] = end_ms
        return get_json(cfg, cfg["binance_base"] + "/fapi/v1/klines?" + urllib.parse.urlencode(params))
    return fetch


class Bot:
    """Freqtrade REST API on this host: GET state, POST/DELETE runtime blacklist."""

    def __init__(self, api, timeout):
        host = "127.0.0.1" if api["listen_ip_address"] in ("0.0.0.0", "") else api["listen_ip_address"]
        self.base, self.timeout = "http://%s:%s/api/v1" % (host, api["listen_port"]), timeout
        cred = base64.b64encode(("%s:%s" % (api["username"], api["password"])).encode()).decode()
        token = http_json(self.base + "/token/login", {"Authorization": "Basic " + cred}, timeout,
                          data=b"", method="POST")["access_token"]
        self.hdr = {"Authorization": "Bearer " + token}

    def get(self, path):
        return http_json(self.base + path, self.hdr, self.timeout)

    def state(self):
        bl = self.get("/blacklist")
        return {"runtime": set(bl["blacklist"]), "expanded": set(bl["blacklist_expanded"]),
                "whitelist": self.get("/whitelist")["whitelist"],
                "open": {t["pair"]: t["trade_id"] for t in self.get("/status")}}

    def add(self, pairs):
        hdr = dict(self.hdr, **{"Content-Type": "application/json"})
        body = json.dumps({"blacklist": pairs}).encode()
        res = http_json(self.base + "/blacklist", hdr, self.timeout, data=body, method="POST")
        bad = {p: e for p, e in res.get("errors", {}).items() if "already" not in str(e)}
        if bad or not set(pairs) <= set(res["blacklist"]):
            raise RuntimeError("blacklist POST failed: %s" % bad)

    def remove(self, pairs):
        qs = urllib.parse.urlencode([("pairs_to_delete", p) for p in pairs])
        res = http_json(self.base + "/blacklist?" + qs, self.hdr, self.timeout, method="DELETE")
        if set(pairs) & set(res["blacklist"]):
            raise RuntimeError("blacklist DELETE failed: %s" % res.get("errors"))


def file_patterns(cfg):
    with open(HERE / cfg["blacklist_file"], encoding="utf-8") as f:
        return json.load(f)["exchange"]["pair_blacklist"]


def append_log(path, rows):
    new = not Path(path).exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(LOG_COLUMNS)
        w.writerows(rows)


def acquire_lock(path, stale_s, wait_s):
    """Portable lock file: full and light runs must not write the state at once."""
    deadline = time.time() + wait_s
    while True:
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except FileExistsError:
            if time.time() - os.path.getmtime(path) > stale_s:
                os.remove(path)  # left by a crashed run
                continue
            if time.time() >= deadline:
                return False
            time.sleep(2)


def load_author(cfg, state):
    """(entries, error): the live list, or the last good copy if it can't be fetched/parsed/trusted."""
    cache = [tuple(x) for x in state.get("author_cache", [])]
    try:
        entries = sd.parse_author_blacklist(get_text(cfg, cfg["author_blacklist_url"]))
        if not sa.accept(cache, entries, cfg["author_min_keep_ratio"]):
            raise ValueError("list shrank: %d -> %d entries" % (len(cache), len(entries)))
        return entries, None
    except (OSError, ValueError, KeyError, TypeError) as e:
        return cache, repr(e)


def replay(cfg, args, info, tickers):
    asof = datetime.strptime(args.asof, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    asof_ms = int(asof.timestamp() * 1000)
    bases = {b.strip().upper() for b in args.pairs.split(",") if b.strip()}
    found = sd.scan(cfg, info, tickers, binance_klines(cfg), {"blacklist": [], "whitelist": [], "open": {}},
                    [], asof_ms, asof_ms, bases)
    print("asof %s UTC, pairs %s" % (args.asof, ",".join(sorted(bases))))
    print("\n".join(sd.format_pair(cfg, c) for c in found) or "no candidates")


def run(args, cfg, private):
    info = get_json(cfg, cfg["binance_base"] + "/fapi/v1/exchangeInfo")
    tickers = get_json(cfg, cfg["binance_base"] + "/fapi/v1/ticker/24hr")
    if args.asof:
        return replay(cfg, args, info, tickers)
    bot = Bot(private["api_server"], cfg["request_timeout_sec"])
    live = bot.state()
    state_path = HERE / cfg["state_file"]
    state = load_json(state_path, default={})
    ours = set(state.get("temp", {})) | set(state.get("perm", {}))
    patterns = file_patterns(cfg)

    def file_blocked(pair):
        return any(re.fullmatch(p, pair) for p in patterns)

    now_s = time.time()
    ts = st.stamp(now_s, "%Y-%m-%d %H:%M")
    shadow, texts, extra = cfg["shadow_mode"], [], {}
    author, author_err = [], None
    if cfg["author_blacklist_url"]:  # optional; empty string disables the author sync
        author, author_err = load_author(cfg, state)
        due = now_s - state.get("author_err", 0) >= cfg["author_error_renotify_hours"] * 3600
        extra["author_err"] = 0 if not author_err else (now_s if due else state["author_err"])
        if author_err and due:
            texts.append(cfg["author_error_template"].format(ts=ts, error=author_err)[:500])
    pairs = [p for p, _, _ in sa.perps(info, cfg["quote"])]
    a_cands = sa.candidates(cfg, author, info, tickers, live["expanded"] - ours, live["whitelist"],
                            live["open"], int(now_s * 1000)) if author else []
    if args.sync:
        found = a_cands
    else:
        scan_bot = {"blacklist": live["expanded"] - ours, "whitelist": live["whitelist"], "open": live["open"]}
        found = sa.merge(sd.scan(cfg, info, tickers, binance_klines(cfg), scan_bot, [], int(now_s * 1000)), a_cands)
    new_state, actions, ev = st.plan(cfg, found, state, file_blocked, live["runtime"], now_s)
    actions = st.live_filter(cfg, new_state, actions, ev, shadow)
    if args.sync:  # no detector pass: keep what the full run knows about notified pairs
        new_state["notify"] = dict(state.get("notify", {}), **new_state["notify"])
    if author and not author_err:
        added, removed = sa.diff([tuple(x) for x in state.get("author_cache", [])], author)
        ev["author_noop"] = [p for p, _ in added if not sa.matching(p, pairs)]
        ev["author_removed"] = [p for p, _ in removed if any(file_blocked(x) for x in sa.matching(p, pairs))]
        extra["author_cache"] = [list(x) for x in author]
        extra["author_changed"] = now_s if added or removed else state.get("author_changed", 0)
        extra["author_info"] = {"entries": len(author), "changed": extra["author_changed"],
                                "noperp": sum(1 for p, _ in author if not sa.matching(p, pairs))}
    else:
        for k in ("author_cache", "author_changed", "author_info"):
            if k in state:
                extra[k] = state[k]
    new_state.update(extra)
    live_fn = lambda keys: st.is_live(cfg, keys, shadow)  # noqa: E731
    message = st.format_events(cfg, ev, new_state, ts, live=live_fn)
    if message:
        texts.insert(0, message)
    if not args.sync and st.digest_due(cfg, new_state, now_s):
        texts.append(st.format_digest(cfg, new_state, len(patterns), ts, live["whitelist"], live=live_fn))
        new_state["digest"] = now_s
    print("\n".join(texts) or "no changes (%d candidates seen)" % len(found))
    print("API: add %s, remove %s" % (actions["add"] or "-", actions["remove"] or "-"))
    if args.dry_run:
        return
    if actions["add"]:
        bot.add(actions["add"])
    if actions["remove"]:
        bot.remove(actions["remove"])
    for text in texts:  # before saving state: a failed send repeats next run
        send_telegram(cfg, private["telegram"], text)
    save_state(state_path, new_state)
    rows = st.log_rows(ev, ts)
    if rows:
        append_log(HERE / cfg["log_file"], rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print only: no API changes, no send, no state, no log")
    ap.add_argument("--sync", action="store_true", help="light run: author list and restore blocks, no detectors")
    ap.add_argument("--asof", help="replay as of UTC time YYYY-MM-DDTHH:MM (print only)")
    ap.add_argument("--pairs", default="", help="with --asof: base assets, e.g. NXPC,DOS")
    args = ap.parse_args()
    if args.asof and not args.pairs:
        ap.error("--asof needs --pairs")
    cfg = load_json(CONFIG_PATH)
    env = dict(load_env_file(HERE / cfg["env_file"]))
    env.update(os.environ)
    private = apply_env_overrides(load_json(HERE / cfg["private_config"]), env)
    locked = not (args.dry_run or args.asof)
    if locked and not acquire_lock(HERE / cfg["lock_file"], cfg["lock_stale_sec"], 0 if args.sync else cfg["lock_wait_sec"]):
        print("another scout run holds the lock: skipped" if args.sync else "lock busy: run skipped")
        sys.exit(0 if args.sync else 1)
    try:
        run(args, cfg, private)
    except Exception as e:  # fail loudly: print and tell Telegram
        traceback.print_exc()
        if not args.dry_run and not args.asof:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            send_telegram(cfg, private["telegram"], cfg["error_template"].format(ts=ts, error=repr(e))[:500])
        sys.exit(1)
    finally:
        if locked:
            os.remove(HERE / cfg["lock_file"])


if __name__ == "__main__":
    main()
