"""Pure rendering for the ops snapshot: no I/O, no network."""

SECRET_WORDS = ("pass", "secret", "token", "key", "chat", "user")
MIN_SECRET_LEN = 6


def secret_values(private):
    """Every credential-like string in the private config, to be cut from any output."""
    out = []
    for section in private.values():
        if not isinstance(section, dict):
            continue
        for key, val in section.items():
            if isinstance(val, bool) or not isinstance(val, (str, int)):
                continue
            if any(w in key.lower() for w in SECRET_WORDS):
                out.append(str(val))
    return out


def redact(text, secrets):
    for s in sorted({x for x in secrets if len(x) >= MIN_SECRET_LEN}, key=len, reverse=True):
        text = text.replace(s, "[redacted]")
    return text


def fmt(v, nd=2):
    if v is None:
        return "n/a"
    return "%.*f" % (nd, v) if isinstance(v, float) else str(v)


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def code(lines):
    return ["```"] + (lines or ["(none)"]) + ["```", ""]


def bot_section(d):
    sc = d.get("show") or {}
    return ["## Bot", "",
            "- service: %s" % d.get("service", "n/a"),
            "- state: %s, strategy: %s %s" % (sc.get("state", "n/a"), sc.get("strategy", "n/a"),
                                             sc.get("strategy_version", "")),
            "- max_open_trades: %s, stake_amount: %s, timeframe: %s" % (
                sc.get("max_open_trades", "n/a"), sc.get("stake_amount", "n/a"), sc.get("timeframe", "n/a")),
            ""]


def money_section(d):
    p, b, c = d.get("profit") or {}, d.get("balance") or {}, d.get("count") or {}
    return ["## Money", "",
            "- wallet total: %s" % fmt(b.get("total")),
            "- closed trades: %s (won %s, lost %s, winrate %s)" % (
                fmt(p.get("closed_trade_count")), fmt(p.get("winning_trades")),
                fmt(p.get("losing_trades")), fmt(p.get("winrate"), 3)),
            "- profit closed: %s, profit all: %s" % (fmt(p.get("profit_closed_coin")), fmt(p.get("profit_all_coin"))),
            "- max drawdown: %s, first trade: %s, latest trade: %s" % (
                fmt(p.get("max_drawdown"), 4), str(p.get("first_trade_date", "n/a")),
                str(p.get("latest_trade_date", "n/a"))),
            "- slots: %s of %s used" % (fmt(c.get("current")), fmt(c.get("max"))),
            ""]


def open_section(d):
    status = d.get("status")
    if status is None:
        return ["## Open trades", "", "n/a", ""]
    rows = [[t.get("trade_id"), t.get("pair"), "short" if t.get("is_short") else "long", t.get("leverage"),
             str(t.get("open_date", ""))[:16], fmt(t.get("profit_pct")), fmt(t.get("profit_abs")),
             fmt(t.get("stake_amount"))] for t in status]
    total = sum(t.get("profit_abs") or 0 for t in status)
    out = ["## Open trades (%d, unrealized %s)" % (len(status), fmt(float(total))), ""]
    if rows:
        out += table(["id", "pair", "side", "lev", "opened", "profit %", "profit abs", "stake"], rows) + [""]
    return out


def scout_section(d):
    bl, sc = d.get("blacklist") or {}, d.get("scout")
    out = ["## Blacklist", "",
           "- whitelist size: %s" % bl.get("whitelist_n", "n/a"),
           "- runtime blacklist (%d): %s" % (len(bl.get("runtime", [])), ", ".join(sorted(bl.get("runtime", [])))) ]
    if sc is None:
        return out + ["- scout state: n/a", ""]
    out += ["- scout temp (%d): %s" % (len(sc.get("temp", {})), ", ".join(sorted(sc.get("temp", {})))),
            "- scout perm (%d): %s" % (len(sc.get("perm", {})), ", ".join(sorted(sc.get("perm", {})))),
            "- author sync: %s" % sc.get("author_info", "n/a"), ""]
    return out


def build(d):
    lines = ["# NFI snapshot %s UTC" % d["ts"], ""]
    if d.get("errors"):
        lines += ["## Errors", ""] + ["- %s: %s" % (k, v) for k, v in sorted(d["errors"].items())] + [""]
    for sec in (bot_section, money_section, open_section, scout_section):
        lines += sec(d)
    lines += ["## Warnings and errors in the bot journal", ""] + code(d.get("journal"))
    for name, rows in (d.get("tails") or {}).items():
        lines += ["## Log tail: %s" % name, ""] + code(rows)
    return "\n".join(lines) + "\n"
