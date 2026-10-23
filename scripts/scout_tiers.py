"""
Blacklist scout, decision part (pure functions, no I/O).

Tiers (reason keys -> tier in config "tiers"):
  perm    block now in the running bot and ask to persist it in
          blacklist-binance.json (persist_blacklist.ps1); kept blocked until
          the file has it
  temp    block now in the running bot for temp_block_days; extended while
          the reason repeats, released when it expires; escalation_count
          temp blocks inside escalation_days turn into perm
  notify  message only
Bases in never_block are never blocked (message only). At most
max_new_blocks_per_run new blocks per run; the rest is reported as skipped.
Only pairs the scout itself added are ever removed from the bot, and a pair
that reached the file is never removed (the file pattern is loaded only on
the next bot restart). In shadow mode the caller does not apply the actions;
messages are marked and the digest shows how much of the whitelist the
blocks would cut.
"""

from datetime import datetime, timezone

EVENT_KEYS = ("new_perm", "new_temp", "skipped", "notify", "released", "persisted", "restored",
              "author_noop", "author_removed")
LIST_EVENTS = ("released", "persisted", "restored", "author_noop", "author_removed")


def stamp(ts_s, fmt="%m-%d %H:%M"):
    return datetime.fromtimestamp(ts_s, timezone.utc).strftime(fmt)


def classify(cfg, c):
    keys = {k for k, _ in c["reasons"]}
    for tier in ("perm", "temp", "notify"):
        if keys & set(cfg["tiers"][tier]):
            if tier != "notify" and c["base"] in cfg["never_block"]:
                return "notify"
            return tier
    return None


def reason_text(c):
    return "; ".join(t for _, t in c["reasons"])


def plan(cfg, found, state, file_blocked, runtime, now_s):
    """Returns (new_state, actions {"add": [...], "remove": [...]}, events)."""
    ev = {k: [] for k in EVENT_KEYS}
    temp = dict(state.get("temp", {}))
    perm = dict(state.get("perm", {}))
    hist_from = now_s - cfg["escalation_days"] * 86400
    history = {p: [t for t in v if t >= hist_from] for p, v in state.get("history", {}).items()}
    notify_old, notify_new = state.get("notify", {}), {}

    for book in (temp, perm):
        for p in [p for p in book if file_blocked(p)]:
            ev["persisted"].append(p)
            del book[p]

    ttl = cfg["temp_block_days"] * 86400
    new_blocks, author_new, seen = 0, 0, set()
    for c in found:
        p, tier = c["pair"], classify(cfg, c)
        rec = {"base": c["base"], "where": c["where"], "text": reason_text(c), "price": c.get("price", 0.0),
               "keys": sorted({k for k, _ in c["reasons"]})}
        if tier == "temp" and p not in perm and p not in temp:
            n_prev = len(history.get(p, []))
            if n_prev + 1 >= cfg["escalation_count"]:
                tier, rec["text"] = "perm", cfg["escalation_text"].format(n=n_prev + 1) + "; " + rec["text"]
        if tier in ("perm", "temp") and p not in perm and p not in temp:
            is_author = "author" in rec["keys"]
            used, cap = ((author_new, cfg["author_max_new_per_run"]) if is_author
                         else (new_blocks, cfg["max_new_blocks_per_run"]))
            if used >= cap:
                ev["skipped"].append(dict(rec, pair=p))
                continue
            author_new, new_blocks = author_new + is_author, new_blocks + (not is_author)
        if tier == "perm":
            if p not in perm:
                perm[p] = dict(rec, since=now_s)
                ev["new_perm"].append(dict(rec, pair=p))
                temp.pop(p, None)
        elif tier == "temp":
            if p in perm:
                continue
            seen.add(p)
            if p not in temp:
                history.setdefault(p, []).append(now_s)
                ev["new_temp"].append(dict(rec, pair=p, until=now_s + ttl))
            temp[p] = dict(rec, since=temp.get(p, {}).get("since", now_s), until=now_s + ttl)
        elif tier == "notify":
            old = notify_old.get(p)
            due = (old is None or set(rec["keys"]) - set(old["keys"])
                   or now_s - old["notified"] >= cfg["renotify_hours"] * 3600)
            notify_new[p] = {"keys": rec["keys"], "notified": now_s if due else old["notified"]}
            if due:
                ev["notify"].append(dict(rec, pair=p))

    released = [p for p, r in temp.items() if p not in seen and r["until"] <= now_s]
    for p in released:
        del temp[p]
    ev["released"] = released
    new_now = {e["pair"] for e in ev["new_perm"] + ev["new_temp"]}
    add = sorted(p for p in set(temp) | set(perm) if p not in runtime)
    ev["restored"] = [p for p in add if p not in new_now]
    actions = {"add": add, "remove": sorted(p for p in released if p in runtime)}
    new_state = {"temp": temp, "perm": perm, "notify": notify_new,
                 "history": {p: v for p, v in history.items() if v},
                 "digest": state.get("digest", 0)}
    return new_state, actions, ev


def is_live(cfg, keys, shadow):
    """Author blocks follow author_sync_live, everything else follows shadow_mode."""
    return cfg["author_sync_live"] if "author" in keys else not shadow


def live_filter(cfg, new_state, actions, ev, shadow):
    """Keep only the planned adds that really go to the bot; shadow ones stay in state only."""
    def live(p):
        rec = new_state["perm"].get(p) or new_state["temp"].get(p) or {}
        return is_live(cfg, rec.get("keys", []), shadow)
    add = [p for p in actions["add"] if live(p)]
    ev["restored"] = [p for p in ev["restored"] if p in add]
    return {"add": add, "remove": actions["remove"]}


def persist_line(cfg, perm):
    bases = " ".join(sorted({r["base"] for r in perm.values()}))
    return cfg["msg"]["persist"].format(cmd=cfg["persist_command_template"].format(bases=bases)) if bases else ""


def totals_line(cfg, st):
    return cfg["msg"]["totals"].format(temp=len(st["temp"]), perm=len(st["perm"]))


def format_events(cfg, ev, st, ts, shadow=False, live=None):
    """live(keys) -> bool tags non-live items; without it shadow marks the whole message."""
    m, out = cfg["msg"], []
    tag = (lambda e: "" if live is None or live(e["keys"]) else m["shadow_item"])
    sections = [("new_temp", "h_new_temp"), ("new_perm", "h_new_perm"), ("skipped", "h_skipped"),
                ("notify", "h_notify")]
    for key, head in sections:
        if ev[key]:
            out.append(m[head].format(n=cfg["max_new_blocks_per_run"]))
            for e in ev[key]:
                tpl = m["item_temp"] if "until" in e else m["item"]
                out.append(tpl.format(pair=e["pair"], where=e["where"] + tag(e), text=e["text"],
                                      until=stamp(e.get("until", 0))))
            if key == "new_perm":
                out.append(persist_line(cfg, st["perm"]))
    for key in LIST_EVENTS:
        if ev[key]:
            out.append(m["h_" + key].format(pairs=", ".join(ev[key])))
    if not out:
        return None
    head = m["header"].format(ts=ts) + (m["shadow_mark"] if shadow and live is None else "")
    if live is not None and any(not live(e["keys"]) for key, _ in sections for e in ev[key]):
        head += m["shadow_mark_part"]
    text = "\n".join([head] + out + ["", totals_line(cfg, st)])
    return text[:cfg["message_max_len"]]


def digest_due(cfg, st, now_s):
    hour = datetime.fromtimestamp(now_s, timezone.utc).hour
    return hour == cfg["digest_hour_utc"] and now_s - st.get("digest", 0) >= 20 * 3600


def format_digest(cfg, st, file_entries, ts, whitelist, shadow=False, live=None):
    m = cfg["msg"]
    tag = (lambda r: "" if live is None or live(r["keys"]) else m["shadow_item"])
    head = m["digest_header"].format(ts=ts) + (m["shadow_mark"] if shadow and live is None else "")
    cut = len((set(st["temp"]) | set(st["perm"])) & set(whitelist))
    out = [head, m["d_cut"].format(m=cut, w=len(whitelist)), m["d_temp"].format(n=len(st["temp"]))]
    for p, r in sorted(st["temp"].items(), key=lambda x: x[1]["until"]):
        out.append(m["d_temp_item"].format(pair=p + tag(r), until=stamp(r["until"]), text=r["text"]))
    out.append(m["d_perm"].format(n=len(st["perm"])))
    for p, r in sorted(st["perm"].items()):
        out.append(m["d_perm_item"].format(pair=p + tag(r), since=stamp(r["since"], "%m-%d"), text=r["text"]))
    if st["perm"]:
        out.append(persist_line(cfg, st["perm"]))
    info = st.get("author_info")
    if info:
        out.append(m["d_author"].format(n=info["entries"], noperp=info["noperp"],
                                        changed=stamp(info["changed"], "%m-%d %H:%M") if info["changed"] else m["d_never"]))
    out.append(m["d_file"].format(n=file_entries))
    return "\n".join(out)[:cfg["message_max_len"]]


def log_rows(ev, ts):
    rows = []
    for key in ("new_temp", "new_perm", "skipped", "notify"):
        rows += [[ts, e["pair"], key, "%.8g" % e["price"], " ".join(e["keys"]), e["text"]] for e in ev[key]]
    for key in LIST_EVENTS:
        rows += [[ts, p, key, "", "", ""] for p in ev[key]]
    return rows
