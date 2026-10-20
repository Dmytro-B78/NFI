"""
Blacklist scout, detection part (pure functions, no I/O).

Detectors (thresholds in blacklist_scout_config.json):
  delist      contract has a delivery/settlement date or is not TRADING
  author      optional cross-check with the author's live blacklist
  hour_spike  one 1h candle with a huge range (DOS 2026-10-12: 486%)
  day_spike   rolling 24h range above the spike level (TAC: 215% day)
  swing_flat  big rolling 24h range, most of it given back: |net| is at most
              swing_net_to_range of the range (NXPC 2026-10-15: 52% wick at
              16:00 UTC, by 19:00 net +19% of a 61% range; a 3-day
              RangeStabilityFilter on closes misses it)
  bleed       far below the recent high and still falling (AEON-type)
"""

import json
import re
from datetime import datetime, timezone

PATTERN_LINE = re.compile(r'^"((?:[^"\\]|\\.)*)",?$')


def utc_text(ms, fmt="%m-%d %H:%M"):
    return datetime.fromtimestamp(ms / 1000.0, timezone.utc).strftime(fmt)


# ---------------------------------------------------------------- author list

def parse_author_blacklist(text):
    """[(pattern, reason)] from the commented upstream file; fails loudly if
    the line-based read and a real JSON parse disagree."""
    entries, comment = [], []
    plain = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("//"):
            comment.append(s[2:].strip())
            continue
        plain.append(line)
        m = PATTERN_LINE.match(s)
        if m:
            entries.append((json.loads('"%s"' % m.group(1)), " ".join(comment)))
            comment = []
    parsed = json.loads("\n".join(plain))["exchange"]["pair_blacklist"]
    if [p for p, _ in entries] != parsed:
        raise ValueError("author blacklist format changed: line parse != JSON parse")
    return entries


def author_reason(entries, pair, max_len):
    for pattern, reason in entries:
        if re.fullmatch(pattern, pair):
            return (reason or pattern)[:max_len]
    return None


# ---------------------------------------------------------------- detectors

def candles(raw, asof_ms=None):
    """Binance klines -> [(open_ms, o, h, l, c, close_ms)]; with asof only
    candles fully closed before it (no look-ahead)."""
    out = [(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), int(k[6])) for k in raw]
    if asof_ms is not None:
        out = [k for k in out if k[5] <= asof_ms]
    return out


def detect_hourly(h1, cfg):
    th, tpl, win = cfg["thresholds"], cfg["reason_templates"], cfg["window_hours"]
    found = []
    if h1:
        k = max(h1, key=lambda x: (x[2] - x[3]) / x[3])
        rng = (k[2] - k[3]) / k[3] * 100.0
        if rng >= th["hour_range_pct"]:
            found.append(("hour_spike", tpl["hour_spike"].format(time=utc_text(k[0]), range=rng)))
    spike, swing = None, None
    for i in range(win, len(h1) + 1):
        w = h1[i - win:i]
        hi, lo = max(x[2] for x in w), min(x[3] for x in w)
        rng = (hi - lo) / lo * 100.0
        chg = (w[-1][4] - w[0][1]) / w[0][1] * 100.0
        end = utc_text(w[-1][5] + 1)
        if rng >= th["day_range_pct"]:
            if spike is None or rng >= spike[0]:  # ties: keep the latest window
                spike = (rng, end)
        elif rng >= th["swing_range_pct"] and abs(chg) <= rng * th["swing_net_to_range"]:
            if swing is None or rng >= swing[0]:
                swing = (rng, chg, end)
    if spike:
        found.append(("day_spike", tpl["day_spike"].format(time=spike[1], range=spike[0])))
    if swing:
        found.append(("swing_flat", tpl["swing_flat"].format(time=swing[2], range=swing[0], change=swing[1])))
    return found


def detect_bleed(d1, cfg):
    th = cfg["thresholds"]
    days = th["bleed_high_days"]
    if len(d1) < 8:
        return []
    last = d1[-1][4]
    off_high = (last / max(k[2] for k in d1[-days:]) - 1.0) * 100.0
    chg7 = (last / d1[-8][4] - 1.0) * 100.0
    if off_high > -th["bleed_off_high_pct"] or chg7 > -th["bleed_7d_pct"]:
        return []
    streak = 0
    for k in reversed(d1):
        if k[4] >= k[1]:
            break
        streak += 1
    return [("bleed", cfg["reason_templates"]["bleed"].format(
        off_high=off_high, days=days, change_7d=chg7, streak=streak))]


def context(d1, h1, onboard_ms, now_ms, qvol, cfg):
    na = cfg["na_text"]
    price = h1[-1][4] if h1 else (d1[-1][4] if d1 else 0.0)
    off_high = "%+.0f%%" % ((price / max(k[2] for k in d1) - 1.0) * 100.0) if d1 and price else na
    listed_in_window = d1 and onboard_ms and d1[0][0] <= onboard_ms + 86400000
    vs_first = "%+.0f%%" % ((price / d1[0][1] - 1.0) * 100.0) if listed_in_window and price else na
    age = cfg["age_template"].format(days=int((now_ms - onboard_ms) / 86400000)) if onboard_ms else na
    return {"price": price, "qvol_m": qvol / 1e6, "off_high_txt": off_high, "vs_first_txt": vs_first, "age_txt": age}


def exchange_reasons(sym, cfg):
    tpl, found = cfg["reason_templates"], []
    delivery = int(sym.get("deliveryDate") or 0)
    if delivery and delivery < cfg["delivery_far_future_ms"]:
        found.append(("delist", tpl["delist"].format(date=utc_text(delivery, "%Y-%m-%d %H:%M"))))
    if sym.get("status") != "TRADING":
        found.append(("status", tpl["status"].format(status=sym.get("status"))))
    return found


# ---------------------------------------------------------------- universe

def build_universe(info, tickers, cfg, blocked, priority, only_bases=None):
    q = cfg["quote"]
    qvol = {t["symbol"]: float(t.get("quoteVolume") or 0.0) for t in tickers}
    rows = []
    for s in info["symbols"]:
        if s.get("contractType") != "PERPETUAL" or s.get("quoteAsset") != q:
            continue
        pair = "%s/%s:%s" % (s["baseAsset"], q, q)
        if pair in blocked or (only_bases is not None and s["baseAsset"] not in only_bases):
            continue
        rows.append({"pair": pair, "base": s["baseAsset"], "sym": s, "qvol": qvol.get(s["symbol"], 0.0)})
    if only_bases is not None:
        return rows
    trading = sorted((r for r in rows if r["sym"].get("status") == "TRADING"), key=lambda r: -r["qvol"])
    keep = {r["pair"] for r in trading[:cfg["universe_top_n"]]} | set(priority)
    return [r for r in rows if r["pair"] in keep]


def scan(cfg, info, tickers, fetch_klines, bot, author, now_ms, asof_ms=None, only_bases=None):
    """Pure core over injected data. Returns candidate dicts."""
    priority = dict(bot["open"])
    priority.update({p: None for p in bot["whitelist"] if p not in priority})
    out = []
    for r in build_universe(info, tickers, cfg, set(bot["blacklist"]), priority, only_bases):
        sym = r["sym"]
        h1 = candles(fetch_klines(sym["symbol"], "1h", cfg["hourly_candles"], asof_ms), asof_ms)
        d1 = candles(fetch_klines(sym["symbol"], "1d", cfg["daily_candles"], asof_ms), asof_ms)
        reasons = detect_hourly(h1, cfg) + detect_bleed(d1, cfg)
        if asof_ms is None:
            reasons = exchange_reasons(sym, cfg) + reasons
            hit = author_reason(author, r["pair"], cfg["author_reason_max_len"])
            if hit:
                reasons.insert(0, ("author", cfg["reason_templates"]["author"].format(reason=hit)))
        if not reasons:
            continue
        where = ""
        if r["pair"] in bot["open"]:
            where = cfg["where_trade"].format(trade_id=bot["open"][r["pair"]])
        elif r["pair"] in bot["whitelist"]:
            where = cfg["where_whitelist"]
        out.append({"pair": r["pair"], "base": r["base"], "where": where, "reasons": reasons,
                    **context(d1, h1, int(sym.get("onboardDate") or 0), now_ms, r["qvol"], cfg)})
    return out


def format_pair(cfg, c):
    return cfg["pair_template"].format(**dict(c, reasons="; ".join(t for _, t in c["reasons"])))
