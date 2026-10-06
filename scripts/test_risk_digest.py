"""Tests for risk_digest.py. Run: python scripts/test_risk_digest.py (or pytest)."""
import copy
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import risk_digest as rd  # noqa: E402

CFG = json.load(open(Path(__file__).parent / "risk_digest_config.json", encoding="utf-8"))
NOW = 1791250000.0  # fixed clock
BALANCE = 2189.391


def trade(tid, pair, margin, unreal, realized, rate, open_rate, liq, days=3.0, short=False):
    return {"trade_id": tid, "pair": pair, "stake_amount": margin, "profit_abs": unreal,
            "realized_profit": realized, "current_rate": rate, "open_rate": open_rate,
            "liquidation_price": liq, "is_short": short, "open_timestamp": (NOW - days * 86400) * 1000}


def book():
    return [
        trade(144, "US/USDT:USDT", 56.697, -13.482, -753.358, 0.010697, 0.011607, 0.0081, 7.0),
        trade(149, "ALICE/USDT:USDT", 435.231, -55.134, -45.4, 0.1825, 0.1903, 0.13, 4.0),
        trade(158, "MAGMA/USDT:USDT", 93.854, -9.707, 0.0, 0.205, 0.21218, 0.15, 1.0),
        trade(154, "MANA/USDT:USDT", 106.731, -2.423, 0.0, 0.10556, 0.10705, 0.07, 3.0),
    ]


def approx(a, b, tol=0.01):
    assert abs(a - b) <= tol, "%s != %s" % (a, b)


def test_portfolio_totals():
    rep = rd.analyze(book(), BALANCE, 2800.0, 8, CFG, NOW)
    approx(rep["margin"], 56.697 + 435.231 + 93.854 + 106.731)
    approx(rep["margin_pct"], 692.513 / BALANCE * 100)
    approx(rep["uw_margin"], rep["margin"])  # all four are below entry
    approx(rep["unreal"], -13.482 - 55.134 - 9.707 - 2.423)
    approx(rep["realized"], -753.358 - 45.4)
    approx(rep["drawdown_pct"], (2800.0 - BALANCE) / 2800.0 * 100)


def test_trade_metrics_us():
    rep = rd.analyze(book(), BALANCE, 2800.0, 8, CFG, NOW)
    us = [t for t in rep["trades"] if t["trade_id"] == 144][0]
    approx(us["total"], -766.84)
    approx(us["total_pct"], -766.84 / BALANCE * 100)
    approx(us["be_move"], (0.011607 - 0.010697) / 0.010697 * 100)
    approx(us["liq_dist"], (0.010697 - 0.0081) / 0.010697 * 100)
    approx(us["age_days"], 7.0)
    assert rep["trades"][0]["trade_id"] == 144  # worst total first


def test_flags_thresholds():
    rep = rd.analyze(book(), BALANCE, 2800.0, 8, CFG, NOW)
    keys = [k for k, _ in rep["flags"]]
    assert "trade_loss:144" in keys               # -35% of balance, threshold 5
    assert "trade_loss:149" not in keys           # ALICE -4.6%, below 5
    assert "underwater_margin" not in keys        # 31.6% < 50
    assert "drawdown" in keys                     # 21.8% >= 10
    assert not any(k.startswith("liquidation") for k in keys)  # US 24% > 15


def test_flag_liquidation_and_underwater():
    b = book()
    b[0]["liquidation_price"] = 0.0100  # 6.5% away
    cfg = copy.deepcopy(CFG)
    cfg["thresholds"]["underwater_margin_pct_of_balance"] = 25.0
    rep = rd.analyze(b, BALANCE, 2800.0, 8, cfg, NOW)
    keys = [k for k, _ in rep["flags"]]
    assert "liquidation:144" in keys and "underwater_margin" in keys


def test_missing_liquidation_and_short_sign():
    t = trade(1, "X/USDT:USDT", 100.0, -5.0, 0.0, 1.10, 1.00, 0.0, short=True)
    a = rd.analyze_trade(t, 1000.0, NOW)
    assert a["liq_dist"] is None
    assert a["be_move"] < 0  # short in loss: price must FALL to break even
    assert "н/д" in rd.trade_line(CFG, a)


def test_empty_book_no_crash():
    rep = rd.analyze([], BALANCE, 2800.0, 8, CFG, NOW)
    msg = rd.format_digest(CFG, rep, "2026-10-06 06:00")
    assert CFG["no_trades_text"] in msg and rep["margin_pct"] == 0
    rep0 = rd.analyze([], 0.0, 0.0, 8, CFG, NOW)  # zero balance must not divide by zero
    assert rep0["margin_pct"] == 0


def test_digest_message_content():
    msg, st, row = rd.decide(CFG, "digest", {"trades": book(), "balance": BALANCE, "max_open": 8}, {}, "2026-10-06 06:00", NOW)
    assert "US/USDT:USDT #144" in msg and "ALICE/USDT:USDT #149" in msg
    assert "4/8" in msg and len(msg) <= CFG["message_max_len"]
    assert st["peak"] == 2800.0 and row[1] == "digest"


def test_peak_moves_up_only():
    d = {"trades": [], "balance": 3000.0, "max_open": 8}
    _, st, _ = rd.decide(CFG, "digest", d, {"peak": 2800.0}, "t", NOW)
    assert st["peak"] == 3000.0
    d["balance"] = 2500.0
    _, st2, _ = rd.decide(CFG, "digest", d, st, "t", NOW)
    assert st2["peak"] == 3000.0


def test_alert_only_on_new_flags():
    d = {"trades": book(), "balance": BALANCE, "max_open": 8}
    msg1, st1, _ = rd.decide(CFG, "alert", d, {}, "t", NOW)
    assert msg1 and "#144" in msg1
    msg2, st2, _ = rd.decide(CFG, "alert", d, st1, "t", NOW)
    assert msg2 is None                       # same flags again: silent
    d2 = {"trades": [], "balance": BALANCE, "max_open": 8}
    _, st3, _ = rd.decide(CFG, "alert", d2, st2, "t", NOW)
    assert "trade_loss:144" not in st3["active_flags"]   # cleared flag is forgotten
    msg4, _, _ = rd.decide(CFG, "alert", d, st3, "t", NOW)
    assert msg4                               # flag came back: announced again


def test_digest_does_not_touch_alert_state():
    d = {"trades": book(), "balance": BALANCE, "max_open": 8}
    _, st, _ = rd.decide(CFG, "digest", d, {"active_flags": ["drawdown"]}, "t", NOW)
    assert st["active_flags"] == ["drawdown"]


def test_message_clipped():
    cfg = copy.deepcopy(CFG)
    cfg["message_max_len"] = 50
    rep = rd.analyze(book(), BALANCE, 2800.0, 8, cfg, NOW)
    assert len(rd.format_digest(cfg, rep, "t")) == 50


def test_log_and_state_files():
    with tempfile.TemporaryDirectory() as d:
        lp, sp = Path(d) / "log.csv", Path(d) / "state.json"
        rd.append_log(lp, ["a"] * len(rd.LOG_COLUMNS))
        rd.append_log(lp, ["b"] * len(rd.LOG_COLUMNS))
        lines = lp.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3 and lines[0].startswith("ts_utc")
        rd.save_state(sp, {"peak": 1.0})
        assert json.loads(sp.read_text()) == {"peak": 1.0}


def test_fetch_data_against_mock_api():
    import base64
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            seen["login_auth"] = self.headers.get("Authorization")
            self._send({"access_token": "tok123"})

        def do_GET(self):
            seen.setdefault("get_auth", set()).add(self.headers.get("Authorization"))
            seen.setdefault("paths", []).append(self.path)
            if self.path == "/api/v1/status":
                self._send(book())
            elif self.path == "/api/v1/balance":
                self._send({"total": BALANCE})
            elif self.path == "/api/v1/show_config":
                self._send({"max_open_trades": 8})
            else:
                self.send_response(404)
                self.end_headers()

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    api = {"listen_ip_address": "0.0.0.0", "listen_port": srv.server_address[1],
           "username": "u", "password": "p"}
    data = rd.fetch_data(api, 5)
    srv.shutdown()
    assert data["balance"] == BALANCE and data["max_open"] == 8 and len(data["trades"]) == 4
    assert seen["login_auth"] == "Basic " + base64.b64encode(b"u:p").decode()
    assert seen["get_auth"] == {"Bearer tok123"}
    assert sorted(seen["paths"]) == ["/api/v1/balance", "/api/v1/show_config", "/api/v1/status"]  # GET only


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)
    print("%d tests passed" % len(tests))
