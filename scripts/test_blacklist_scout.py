"""Tests for blacklist_scout.py. Run: python scripts/test_blacklist_scout.py (or pytest)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import blacklist_scout as bs  # noqa: E402

CFG = json.load(open(Path(__file__).parent / "blacklist_scout_config.json", encoding="utf-8"))
H = 3600 * 1000
D = 24 * H
T0 = 1791000000000 - (1791000000000 % D)  # fixed UTC midnight


def k(open_ms, o, h, lo, c, step):
    return [open_ms, str(o), str(h), str(lo), str(c), "0", open_ms + step - 1]


def calm_hours(n, price=1.0, start=T0):
    return [k(start + i * H, price, price * 1.01, price * 0.99, price, H) for i in range(n)]


def calm_days(n, price=1.0, start=T0):
    return [k(start + i * D, price, price * 1.02, price * 0.98, price, D) for i in range(n)]


AUTHOR_TEXT = """{
  "exchange": {
    "pair_blacklist": [
      // Vesting pool drained -- UNCX exploit
      "(IMO)/.*",
      // Caught our own bots -- 63% range
      "(NXPC)/.*",
      "(AAA|BBB)/.*"
    ]
  }
}"""


def test_author_parse_and_match():
    e = bs.parse_author_blacklist(AUTHOR_TEXT)
    assert e == [("(IMO)/.*", "Vesting pool drained -- UNCX exploit"),
                 ("(NXPC)/.*", "Caught our own bots -- 63% range"), ("(AAA|BBB)/.*", "")]
    assert bs.author_reason(e, "IMO/USDT:USDT", 10) == "Vesting po"
    assert bs.author_reason(e, "IMOON/USDT:USDT", 99) is None      # fullmatch, not prefix
    assert bs.author_reason(e, "BBB/USDT:USDT", 99) == "(AAA|BBB)/.*"  # no comment -> pattern


def test_author_format_change_fails_loudly():
    bad = AUTHOR_TEXT.replace('"(AAA|BBB)/.*"', '"(AAA)/.*", "(BBB)/.*"')
    try:
        bs.parse_author_blacklist(bad)
    except ValueError as err:
        assert "format changed" in str(err)
    else:
        raise AssertionError("mismatch was accepted")


def test_asof_drops_unclosed_candles():
    raw = calm_hours(5)
    asof = T0 + 3 * H  # candles 0..2 closed, 3 is still open at asof
    assert len(bs.candles(raw, asof)) == 3
    assert len(bs.candles(raw)) == 5


def test_swing_flat_nxpc_shape():
    h1 = bs.candles(calm_hours(48) + [k(T0 + (48 + i) * H, 1.0, 1.0 + (0.632 if i == 10 else 0.0),
                                        1.0 if i != 10 else 0.95, 1.043 if i == 23 else 1.0, H)
                                      for i in range(24)])
    keys = [x for x, _ in bs.detect_hourly(h1, CFG)]
    assert keys == ["swing_flat"], keys


# Real NXPCUSDT 1h candles 2026-10-14 23:00 .. 2026-10-15 22:00 UTC (server output 2026-10-20).
NXPC_1015 = [
    (0.1994, 0.2003, 0.1992, 0.1998), (0.1999, 0.2007, 0.1966, 0.1970), (0.1972, 0.1982, 0.1968, 0.1968),
    (0.1968, 0.1970, 0.1864, 0.1918), (0.1918, 0.1924, 0.1893, 0.1901), (0.1901, 0.1928, 0.1895, 0.1920),
    (0.1920, 0.1921, 0.1873, 0.1876), (0.1876, 0.1900, 0.1874, 0.1895), (0.1895, 0.1903, 0.1885, 0.1901),
    (0.1902, 0.1912, 0.1892, 0.1911), (0.1912, 0.1912, 0.1891, 0.1892), (0.1891, 0.1896, 0.1881, 0.1890),
    (0.1890, 0.1903, 0.1882, 0.1894), (0.1895, 0.1901, 0.1872, 0.1889), (0.1889, 0.1901, 0.1876, 0.1897),
    (0.1898, 0.1941, 0.1895, 0.1941), (0.1939, 0.1975, 0.1937, 0.1973), (0.1974, 0.3000, 0.1968, 0.2652),
    (0.2653, 0.2763, 0.2393, 0.2539), (0.2539, 0.2540, 0.2348, 0.2366), (0.2366, 0.2432, 0.2314, 0.2339),
    (0.2337, 0.2386, 0.2291, 0.2322), (0.2324, 0.2342, 0.2251, 0.2268), (0.2268, 0.2271, 0.2231, 0.2248),
]


def nxpc_hours(n_real):
    start = T0 + 24 * H  # 24 calm hours before, roughly the real 10-14 level
    pre = calm_hours(24, 0.1995)
    real = [k(start + i * H, o, h, lo, c, H) for i, (o, h, lo, c) in enumerate(NXPC_1015[:n_real])]
    return bs.candles(pre + real)


def test_nxpc_real_caught_before_our_entry():
    # 20 real candles = closed through 18:59 UTC: net +18.6% of a 61% range -> swing_flat
    keys = [x for x, _ in bs.detect_hourly(nxpc_hours(20), CFG)]
    assert keys == ["swing_flat"], keys
    # at 23:00 UTC (our bot entered 23:35) it is still flagged
    assert [x for x, _ in bs.detect_hourly(nxpc_hours(24), CFG)] == ["swing_flat"]
    # at 18:00 UTC price is still near the top (net +27% of 61%): not yet a swing
    assert bs.detect_hourly(nxpc_hours(19), CFG) == []


def test_trend_day_is_not_swing():
    h1 = bs.candles(calm_hours(24) + [k(T0 + (24 + i) * H, 1.0 + 0.025 * i, 1.0 + 0.025 * (i + 1),
                                        1.0 + 0.025 * i, 1.0 + 0.025 * (i + 1), H) for i in range(24)])
    assert bs.detect_hourly(h1, CFG) == []  # +60% straight up: range ~ net


def test_spikes_dos_shape():
    h1 = bs.candles(calm_hours(60) + [k(T0 + 60 * H, 0.3785, 0.8542, 0.1456, 0.2002, H)] +
                    calm_hours(10, 0.2, T0 + 61 * H))
    keys = [x for x, _ in bs.detect_hourly(h1, CFG)]
    assert keys == ["hour_spike", "day_spike"], keys


def test_calm_market_is_silent():
    assert bs.detect_hourly(bs.candles(calm_hours(96)), CFG) == []
    assert bs.detect_bleed(bs.candles(calm_days(120)), CFG) == []


def test_bleed_aeon_shape():
    days = calm_days(100, 1.0)
    p = 0.62
    for i, chg in enumerate([-0.094, -0.018, -0.104, -0.080, -0.095]):
        o, p = p, p * (1 + chg)
        days.append(k(T0 + (100 + i) * D, o, o, p, p, D))
    found = bs.detect_bleed(bs.candles(days), CFG)
    assert [x for x, _ in found] == ["bleed"] and "подряд 5" in found[0][1], found
    mild = calm_days(80, 1.0) + calm_days(20, 0.4, T0 + 80 * D)  # far off high, flat for 20 days
    assert bs.detect_bleed(bs.candles(mild), CFG) == []


def test_exchange_reasons():
    assert bs.exchange_reasons({"deliveryDate": 4133404800000, "status": "TRADING"}, CFG) == []
    r = bs.exchange_reasons({"deliveryDate": 1792000000000, "status": "SETTLING"}, CFG)
    assert [x for x, _ in r] == ["delist", "status"]


def sym(base, onboard=T0 - 200 * D, quote="USDT", ctype="PERPETUAL", status="TRADING"):
    return {"symbol": base + quote, "baseAsset": base, "quoteAsset": quote, "contractType": ctype,
            "status": status, "onboardDate": onboard, "deliveryDate": 4133404800000}


INFO = {"symbols": [sym("NXPC"), sym("DOS"), sym("BTC"), sym("OLD"), sym("ETH", quote="USDC"),
                    sym("BTCQ", ctype="CURRENT_QUARTER"), sym("TINY")]}
TICKERS = [{"symbol": "NXPCUSDT", "quoteVolume": "15.6e6"}, {"symbol": "DOSUSDT", "quoteVolume": "196e6"},
           {"symbol": "BTCUSDT", "quoteVolume": "9e9"}, {"symbol": "OLDUSDT", "quoteVolume": "50e6"},
           {"symbol": "TINYUSDT", "quoteVolume": "1e3"}]


def test_universe_filters_and_priority():
    cfg = dict(CFG, universe_top_n=2)
    rows = bs.build_universe(INFO, TICKERS, cfg, {"OLD/USDT:USDT"}, {"TINY/USDT:USDT": None})
    assert sorted(r["pair"] for r in rows) == ["BTC/USDT:USDT", "DOS/USDT:USDT", "TINY/USDT:USDT"]


def fake_klines(symbol, interval, limit, end_ms=None):
    if interval == "1d":
        return calm_days(120)
    if symbol == "DOSUSDT":
        return calm_hours(60) + [k(T0 + 60 * H, 0.3785, 0.8542, 0.1456, 0.2002, H)] + calm_hours(10, 0.2, T0 + 61 * H)
    return calm_hours(96)


def bot():
    return {"blacklist": ["OLD/USDT:USDT"], "whitelist": ["DOS/USDT:USDT", "NXPC/USDT:USDT"],
            "open": {"NXPC/USDT:USDT": 190}}


def test_scan_end_to_end():
    author = bs.parse_author_blacklist(AUTHOR_TEXT)
    found = bs.scan(CFG, INFO, TICKERS, fake_klines, bot(), author, T0 + 200 * D)
    by = {c["pair"]: c for c in found}
    assert sorted(by) == ["DOS/USDT:USDT", "NXPC/USDT:USDT"]
    assert by["NXPC/USDT:USDT"]["where"] == " [открыта сделка #190]"
    assert by["NXPC/USDT:USDT"]["reasons"][0][0] == "author"
    assert by["DOS/USDT:USDT"]["where"] == " [в вайтлисте]"
    text = bs.format_pair(CFG, by["DOS/USDT:USDT"])
    assert '"(DOS)/.*"' in text and "диапазон 487%" in text and "возраст 400 д" in text


def test_scan_asof_skips_exchange_and_author():
    info = {"symbols": [dict(sym("NXPC"), deliveryDate=1792000000000)]}
    found = bs.scan(CFG, info, TICKERS, fake_klines, {"blacklist": [], "whitelist": [], "open": {}},
                    bs.parse_author_blacklist(AUTHOR_TEXT), T0, T0 + 200 * D, {"NXPC"})
    assert found == []  # calm candles; delist/author are not used in replay


def test_decide_new_repeat_newreason_renotify_drop():
    c = {"pair": "DOS/USDT:USDT", "base": "DOS", "where": "", "price": 0.2, "qvol_m": 196.0,
         "off_high_txt": "-73%", "vs_first_txt": "н/д", "age_txt": "70 д",
         "reasons": [("hour_spike", "час: 486%")]}
    msg, st, rows = bs.decide(CFG, [c], {}, "t1", 1000.0)
    assert msg and "кандидатов в блэклист 1" in msg and '"(DOS)/.*"' in msg and len(rows) == 1
    msg2, st2, _ = bs.decide(CFG, [c], st, "t2", 2000.0)
    assert msg2 is None and st2[c["pair"]]["notified"] == 1000.0
    c3 = dict(c, reasons=c["reasons"] + [("author", "в блэклисте автора")])
    msg3, st3, _ = bs.decide(CFG, [c3], st2, "t3", 3000.0)
    assert msg3 is not None and st3[c["pair"]]["notified"] == 3000.0
    later = 3000.0 + CFG["renotify_hours"] * 3600
    assert bs.decide(CFG, [c3], st3, "t4", later)[0] is not None
    assert bs.decide(CFG, [], st3, "t5", 4000.0) == (None, {}, [])  # gone -> forgotten


def test_message_clipped():
    c = {"pair": "X/USDT:USDT", "base": "X", "where": "", "price": 1.0, "qvol_m": 1.0,
         "off_high_txt": "-1%", "vs_first_txt": "-1%", "age_txt": "1 д", "reasons": [("bleed", "z" * 9000)]}
    assert len(bs.decide(CFG, [c], {}, "t", 1.0)[0]) == CFG["message_max_len"]


def test_fetch_bot_against_mock_api():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen = {"paths": []}

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
            seen["post"] = self.path
            self._send({"access_token": "tok"})

        def do_GET(self):
            seen["paths"].append(self.path)
            data = {"/api/v1/blacklist": {"blacklist_expanded": ["OLD/USDT:USDT"]},
                    "/api/v1/whitelist": {"whitelist": ["DOS/USDT:USDT"]},
                    "/api/v1/status": [{"pair": "NXPC/USDT:USDT", "trade_id": 190}]}
            self._send(data[self.path])

    srv = HTTPServer(("127.0.0.1", 0), Hd)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    api = {"listen_ip_address": "0.0.0.0", "listen_port": srv.server_address[1], "username": "u", "password": "p"}
    b = bs.fetch_bot(api, 5)
    srv.shutdown()
    assert b == {"blacklist": ["OLD/USDT:USDT"], "whitelist": ["DOS/USDT:USDT"],
                 "open": {"NXPC/USDT:USDT": 190}}
    assert seen["post"] == "/api/v1/token/login"  # the only POST is the login
    assert sorted(seen["paths"]) == ["/api/v1/blacklist", "/api/v1/status", "/api/v1/whitelist"]


if __name__ == "__main__":
    tests = [v for name, v in sorted(globals().items()) if name.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)
    print("%d tests passed" % len(tests))
