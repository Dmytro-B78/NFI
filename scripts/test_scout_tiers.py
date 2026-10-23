"""Tests for scout_tiers.py and the I/O of blacklist_scout.py. Run: python scripts/test_scout_tiers.py (or pytest)."""
import json
import sys
import tempfile
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import blacklist_scout as bs  # noqa: E402
import scout_tiers as st  # noqa: E402

CFG = json.load(open(Path(__file__).parent / "blacklist_scout_config.json", encoding="utf-8"))
DAY = 86400.0
NOW = 1791000000.0


def cand(base, keys, where=""):
    return {"pair": "%s/USDT:USDT" % base, "base": base, "where": where,
            "reasons": [(k, "%s text" % k) for k in keys]}


def none_blocked(pair):
    return False


def test_classify_and_never_block():
    assert st.classify(CFG, cand("X", ["swing_flat"])) == "temp"
    assert st.classify(CFG, cand("X", ["bleed", "delist"])) == "perm"     # strongest tier wins
    assert st.classify(CFG, cand("X", ["bleed"])) == "notify"
    assert st.classify(CFG, cand("BTC", ["hour_spike"])) == "notify"      # never_block
    assert st.classify(CFG, cand("X", ["unknown"])) is None


def test_temp_block_extend_restore_release():
    c = cand("BR", ["swing_flat"], " [в вайтлисте]")
    s1, a1, e1 = st.plan(CFG, [c], {}, none_blocked, set(), NOW)
    assert a1 == {"add": ["BR/USDT:USDT"], "remove": []} and e1["restored"] == []
    assert s1["temp"]["BR/USDT:USDT"]["until"] == NOW + 7 * DAY
    msg = st.format_events(CFG, e1, s1, "t")
    assert "Временный блок" in msg and "BR/USDT:USDT [в вайтлисте] до" in msg and "ТЕНЕВОЙ" not in msg
    assert "ТЕНЕВОЙ РЕЖИМ" in st.format_events(CFG, e1, s1, "t", shadow=True)
    # an hour later, still found and still in the bot: extended silently
    s2, a2, e2 = st.plan(CFG, [c], s1, none_blocked, {"BR/USDT:USDT"}, NOW + 3600)
    assert a2 == {"add": [], "remove": []} and st.format_events(CFG, e2, s2, "t") is None
    assert s2["temp"]["BR/USDT:USDT"]["until"] == NOW + 3600 + 7 * DAY
    # bot restarted (runtime list empty): put back, reported as restored
    s3, a3, e3 = st.plan(CFG, [], s2, none_blocked, set(), NOW + 7200)
    assert a3["add"] == ["BR/USDT:USDT"] and e3["restored"] == ["BR/USDT:USDT"]
    # expired and not seen any more: released
    later = NOW + 3600 + 7 * DAY
    s4, a4, e4 = st.plan(CFG, [], s3, none_blocked, {"BR/USDT:USDT"}, later)
    assert a4 == {"add": [], "remove": ["BR/USDT:USDT"]} and e4["released"] == ["BR/USDT:USDT"]
    assert s4["temp"] == {} and "Снят временный блок" in st.format_events(CFG, e4, s4, "t")


def test_notify_only_pair_does_not_keep_temp_alive():
    s1, _, _ = st.plan(CFG, [cand("Q", ["swing_flat"])], {}, none_blocked, set(), NOW)
    later = NOW + 8 * DAY
    s2, a2, e2 = st.plan(CFG, [cand("Q", ["bleed"])], s1, none_blocked, {"Q/USDT:USDT"}, later)
    assert e2["released"] == ["Q/USDT:USDT"] and a2["remove"] == ["Q/USDT:USDT"]
    assert [e["pair"] for e in e2["notify"]] == ["Q/USDT:USDT"]


def test_perm_upgrade_persist_and_no_delete():
    s1, _, _ = st.plan(CFG, [cand("CYS", ["swing_flat"])], {}, none_blocked, set(), NOW)
    s2, a2, e2 = st.plan(CFG, [cand("CYS", ["delist", "swing_flat"])], s1, none_blocked, {"CYS/USDT:USDT"}, NOW + 3600)
    assert "CYS/USDT:USDT" in s2["perm"] and s2["temp"] == {} and a2 == {"add": [], "remove": []}
    msg = st.format_events(CFG, e2, s2, "t")
    assert "закрепить навсегда" in msg and ".\\scripts\\persist_blacklist.ps1 CYS" in msg
    # after persist_blacklist.ps1 + git pull the file blocks it: forget it, do NOT delete from the bot
    s3, a3, e3 = st.plan(CFG, [], s2, lambda p: p == "CYS/USDT:USDT", {"CYS/USDT:USDT"}, NOW + 7200)
    assert s3["perm"] == {} and e3["persisted"] == ["CYS/USDT:USDT"] and a3 == {"add": [], "remove": []}


def test_escalation_to_perm():
    state = {"history": {"BR/USDT:USDT": [NOW - 20 * DAY, NOW - 10 * DAY], "OLD/USDT:USDT": [NOW - 40 * DAY]}}
    s, a, e = st.plan(CFG, [cand("BR", ["swing_flat"])], state, none_blocked, set(), NOW)
    assert "BR/USDT:USDT" in s["perm"] and "3-й раз" in e["new_perm"][0]["text"]
    assert "OLD/USDT:USDT" not in s["history"]  # older than escalation_days is dropped


def test_limit_per_run():
    found = [cand("P%d" % i, ["hour_spike"]) for i in range(7)]
    s, a, e = st.plan(CFG, found, {}, none_blocked, set(), NOW)
    assert len(e["new_temp"]) == 5 and len(e["skipped"]) == 2 and len(a["add"]) == 5
    assert "лимит 5" in st.format_events(CFG, e, s, "t")


def test_notify_dedupe_and_renotify():
    c = cand("STRK", ["bleed"])
    s1, a1, e1 = st.plan(CFG, [c], {}, none_blocked, set(), NOW)
    assert len(e1["notify"]) == 1 and a1["add"] == []
    s2, _, e2 = st.plan(CFG, [c], s1, none_blocked, set(), NOW + 3600)
    assert e2["notify"] == []
    s3, _, e3 = st.plan(CFG, [c], s2, none_blocked, set(), NOW + 73 * 3600)
    assert len(e3["notify"]) == 1


def test_digest():
    s, _, _ = st.plan(CFG, [cand("BR", ["swing_flat"]), cand("CYS", ["delist"])], {}, none_blocked, set(), NOW)
    at = 1791001200.0 - (1791001200.0 % DAY) + CFG["digest_hour_utc"] * 3600
    assert st.digest_due(CFG, s, at) and not st.digest_due(CFG, s, at + 3600)
    assert not st.digest_due(CFG, dict(s, digest=at - 3600), at)
    text = st.format_digest(CFG, s, 51, "t", ["BR/USDT:USDT", "DOS/USDT:USDT"], shadow=True)
    assert "вайтлиста (2 пар) под блоком: 1" in text and "ТЕНЕВОЙ РЕЖИМ" in text
    assert "Временные блоки (1)" in text and "Ждут закрепления в файле (1)" in text
    assert "persist_blacklist.ps1 CYS" in text and "записей: 51" in text
    empty = st.format_digest(CFG, {"temp": {}, "perm": {}}, 51, "t", [])
    assert "(0)" in empty and "persist" not in empty


def test_bot_api_against_mock():
    seen = []

    class Hd(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n).decode()
            seen.append(("POST", self.path, body, self.headers.get("Content-Type")))
            if self.path.endswith("/token/login"):
                return self._send({"access_token": "tok"})
            self._send({"blacklist": ["(OLD)/.*"] + json.loads(body)["blacklist"], "errors": {}})

        def do_DELETE(self):
            seen.append(("DELETE", self.path, "", None))
            self._send({"blacklist": ["(OLD)/.*"], "errors": {}})

        def do_GET(self):
            seen.append(("GET", self.path, "", self.headers.get("Authorization")))
            data = {"/api/v1/blacklist": {"blacklist": ["(OLD)/.*", "BR/USDT:USDT"],
                                          "blacklist_expanded": ["OLD/USDT:USDT", "BR/USDT:USDT"]},
                    "/api/v1/whitelist": {"whitelist": ["DOS/USDT:USDT"]},
                    "/api/v1/status": [{"pair": "NXPC/USDT:USDT", "trade_id": 190}]}
            self._send(data[self.path])

    srv = HTTPServer(("127.0.0.1", 0), Hd)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    api = {"listen_ip_address": "0.0.0.0", "listen_port": srv.server_address[1], "username": "u", "password": "p"}
    bot = bs.Bot(api, 5)
    live = bot.state()
    bot.add(["BR/USDT:USDT", "Q/USDT:USDT"])
    bot.remove(["BR/USDT:USDT"])
    srv.shutdown()
    assert live["runtime"] == {"(OLD)/.*", "BR/USDT:USDT"} and live["open"] == {"NXPC/USDT:USDT": 190}
    post = [x for x in seen if x[0] == "POST" and x[1].endswith("/blacklist")][0]
    assert json.loads(post[2]) == {"blacklist": ["BR/USDT:USDT", "Q/USDT:USDT"]} and post[3] == "application/json"
    delete = [x for x in seen if x[0] == "DELETE"][0]
    assert delete[1] == "/api/v1/blacklist?pairs_to_delete=BR%2FUSDT%3AUSDT"
    assert {x[3] for x in seen if x[0] == "GET"} == {"Bearer tok"}


def run_once(tmp, dry, state=None, runtime=frozenset(), shadow=False, sync=False, author=None, files=("(OLD)/.*",),
             expanded=frozenset()):
    """run() with Binance, GitHub, the bot and Telegram replaced by fakes. author: list text, or an exception to raise."""
    calls = []
    sys.path.insert(0, str(Path(__file__).parent))
    import test_blacklist_scout as td

    class FakeBot:
        def __init__(self, api, timeout):
            pass

        def state(self):
            return {"runtime": set(runtime), "expanded": {"OLD/USDT:USDT"} | set(runtime) | set(expanded),
                    "whitelist": ["DOS/USDT:USDT"], "open": {}}

        def add(self, pairs):
            calls.append(("add", pairs))

        def remove(self, pairs):
            calls.append(("remove", pairs))

    def fake_get_json(cfg, url):
        if url.endswith("/exchangeInfo"):
            return td.INFO
        if url.endswith("/ticker/24hr"):
            return td.TICKERS
        assert not sync, "light run must not fetch candles"
        q = dict(p.split("=") for p in url.split("?", 1)[1].split("&"))
        return td.fake_klines(q["symbol"], q["interval"], int(q["limit"]))

    bl = Path(tmp) / "bl.json"
    bl.write_text(json.dumps({"exchange": {"pair_blacklist": list(files)}}), encoding="utf-8")
    cfg = dict(CFG, request_pause_sec=0, author_blacklist_url="http://author" if author else "", blacklist_file=str(bl),
               shadow_mode=shadow, retry_pause_sec=0,
               state_file=str(Path(tmp) / "state.json"), log_file=str(Path(tmp) / "log.csv"))
    if state is not None:
        Path(cfg["state_file"]).write_text(json.dumps(state), encoding="utf-8")
    def fake_get_text(cfg, url):
        if isinstance(author, Exception):
            raise author
        return author

    orig = (bs.Bot, bs.get_json, bs.send_telegram, bs.get_text)
    bs.Bot, bs.get_json, bs.get_text = FakeBot, fake_get_json, fake_get_text
    bs.send_telegram = lambda c, tg, text: calls.append(("telegram", text))
    try:
        bs.run(types.SimpleNamespace(dry_run=dry, asof=None, pairs="", sync=sync), cfg, {"api_server": {}, "telegram": {}})
    finally:
        bs.Bot, bs.get_json, bs.send_telegram, bs.get_text = orig
    return calls, cfg


def test_run_dry_and_real():
    with tempfile.TemporaryDirectory() as tmp:
        calls, cfg = run_once(tmp, dry=True)
        assert calls == [] and not Path(cfg["state_file"]).exists()  # dry-run changes nothing
        calls, cfg = run_once(tmp, dry=False)
        assert calls[0] == ("add", ["DOS/USDT:USDT"])  # DOS fake candles: 486% hour -> temp
        assert calls[1][0] == "telegram" and "DOS/USDT:USDT [в вайтлисте] до" in calls[1][1]
        state = json.loads(Path(cfg["state_file"]).read_text(encoding="utf-8"))
        assert list(state["temp"]) == ["DOS/USDT:USDT"]
        assert "new_temp" in Path(cfg["log_file"]).read_text(encoding="utf-8")
        # next run, DOS now blocked in the bot: it is still scanned (ours), extended, nothing to send
        calls, _ = run_once(tmp, dry=False, state=state, runtime={"DOS/USDT:USDT"})
        assert [c for c in calls if c[0] != "telegram" or "сводка" not in c[1]] == []


def test_run_shadow_never_touches_bot():
    with tempfile.TemporaryDirectory() as tmp:
        calls, cfg = run_once(tmp, dry=False, shadow=True)
        assert [c[0] for c in calls if c[0] != "telegram"] == []  # no add/remove
        assert "[тень]" in calls[0][1] and "DOS/USDT:USDT [в вайтлисте] [тень]" in calls[0][1]
        state = json.loads(Path(cfg["state_file"]).read_text(encoding="utf-8"))
        assert list(state["temp"]) == ["DOS/USDT:USDT"]
        log = Path(cfg["log_file"]).read_text(encoding="utf-8")
        assert log.splitlines()[0] == "ts_utc,pair,event,price,keys,text" and ",new_temp,0.2," in log
        # next hour: DOS is not in the bot (shadow), but this must not be reported as "restored"
        calls, _ = run_once(tmp, dry=False, state=state, shadow=True)
        assert [c for c in calls if "сводка" not in c[1]] == []


if __name__ == "__main__":
    tests = [v for name, v in sorted(globals().items()) if name.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)
    print("%d tests passed" % len(tests))
