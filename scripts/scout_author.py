"""
Blacklist scout, author sync part (pure functions, no I/O).

The author's live blacklist is applied to the running bot as soon as an entry
appears, for every Binance USDT perpetual it matches (not only the pairs the
price detectors scan). Rails against a bad or truncated remote file:
  - a list that shrank below author_min_keep_ratio of the last good one is
    rejected (the cached list is used and the error is reported);
  - if one run would cut more than author_max_whitelist_cut whitelist/open
    pairs, nothing is blocked: all of them are held and reported instead.
Entries the author removed are only reported, never released here. Entries
that match no Binance perpetual change nothing and are only reported.
"""

import re

import scout_detect as sd


def perps(info, quote):
    """[(pair, base, symbol_dict)] of all Binance perpetuals in the quote currency."""
    return [("%s/%s:%s" % (s["baseAsset"], quote, quote), s["baseAsset"], s)
            for s in info["symbols"] if s.get("contractType") == "PERPETUAL" and s.get("quoteAsset") == quote]


def candidates(cfg, entries, info, tickers, blocked, whitelist, open_trades, now_ms):
    """Candidate dicts (reason key "author") for author entries not blocked yet."""
    last = {t["symbol"]: float(t.get("lastPrice") or 0.0) for t in tickers}
    out = []
    for pair, base, s in perps(info, cfg["quote"]):
        if pair in blocked:
            continue
        hit = sd.author_reason(entries, pair, cfg["author_reason_max_len"])
        if not hit:
            continue
        where = ""
        if pair in open_trades:
            where = cfg["where_trade"].format(trade_id=open_trades[pair])
        elif pair in whitelist:
            where = cfg["where_whitelist"]
        out.append({"pair": pair, "base": base, "where": where, "price": last.get(s["symbol"], 0.0),
                    "reasons": [("author", cfg["reason_templates"]["author"].format(reason=hit))]})
    return hold_flood(cfg, out)


def hold_flood(cfg, cands):
    """Too many whitelist/open pairs at once: block none, report all as held."""
    cut = sum(1 for c in cands if c["where"])
    if cut <= cfg["author_max_whitelist_cut"]:
        return cands
    text = cfg["reason_templates"]["author_held"].format(n=cut, cap=cfg["author_max_whitelist_cut"])
    return [dict(c, reasons=[("author_held", "%s | %s" % (text, c["reasons"][0][1]))]) for c in cands]


def merge(found, author_cands):
    """Detector candidates + author candidates: one dict per pair, author reason first."""
    by = {c["pair"]: c for c in found}
    for a in author_cands:
        if a["pair"] in by:
            c = by[a["pair"]]
            by[a["pair"]] = dict(c, reasons=a["reasons"] + c["reasons"])
        else:
            by[a["pair"]] = a
    return list(by.values())


def accept(cache, entries, min_ratio):
    """A fetched list is trusted unless it shrank a lot against the cached one."""
    return not cache or len(entries) >= len(cache) * min_ratio


def diff(prev, entries):
    """(added, removed) as [(pattern, reason)]; nothing on the first run."""
    if not prev:
        return [], []
    old, new = {p for p, _ in prev}, {p for p, _ in entries}
    return [e for e in entries if e[0] not in old], [e for e in prev if e[0] not in new]


def matching(pattern, pairs):
    return [p for p in pairs if re.fullmatch(pattern, p)]
