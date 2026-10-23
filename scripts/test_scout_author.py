"""Tests for scout_author.py and the author sync in blacklist_scout.py. Run: python scripts/test_scout_author.py (or pytest)."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import blacklist_scout as bs  # noqa: E402
import scout_author as sa  # noqa: E402
import scout_detect as sd  # noqa: E402
import scout_tiers as st  # noqa: E402
import test_blacklist_scout as td  # noqa: E402
from test_scout_tiers import CFG, NOW, cand, none_blocked, run_once  # noqa: E402

AUTHOR = """{ "exchange": { "pair_blacklist": [
  // exploit
  "(NXPC)/.*",
  // no perp anywhere
  "(IMO)/.*",
  "(OLD)/.*"
] } }"""


def entries(text=AUTHOR):
    return sd.parse_author_blacklist(text)


def make(n):
    syms = [td.sym("A%d" % i) for i in range(n)]
    tickers = [{"symbol": s["symbol"], "lastPrice": "2.5"} for s in syms]
    return {"symbols": syms}, tickers, [("(A%d)/.*" % i, "") for i in range(n)]


def test_candidates_cover_pairs_outside_universe():
    info = {"symbols": td.INFO["symbols"]}
    tickers = [{"symbol": "TINYUSDT", "quoteVolume": "1", "lastPrice": "0.5"}]
    e = [("(TINY)/.*", "pump"), ("(IMO)/.*", "gone")]
    out = sa.candidates(CFG, e, info, tickers, set(), [], {"TINY/USDT:USDT": 7}, NOW)
    assert [c["pair"] for c in out] == ["TINY/USDT:USDT"] and out[0]["price"] == 0.5
    assert out[0]["where"] == " [открыта сделка #7]" and out[0]["reasons"][0][0] == "author"
    # already blocked by the bot / file: not a candidate
    assert sa.candidates(CFG, e, info, tickers, {"TINY/USDT:USDT"}, [], {}, NOW) == []


def test_flood_is_held_not_blocked():
    info, tickers, e = make(20)
    wl = ["A%d/USDT:USDT" % i for i in range(20)]
    out = sa.candidates(CFG, e, info, tickers, set(), wl, {}, NOW)
    assert len(out) == 20 and {c["reasons"][0][0] for c in out} == {"author_held"}
    assert st.classify(CFG, out[0]) == "notify"          # reported, never blocked
    ok = sa.candidates(CFG, e, info, tickers, set(), wl[:CFG["author_max_whitelist_cut"]], {}, NOW)
    assert {c["reasons"][0][0] for c in ok} == {"author"}  # at the cap: still fine


def test_merge_diff_accept_matching():
    found = [cand("DOS", ["hour_spike"])]
    merged = sa.merge(found, [cand("DOS", ["author"]), cand("NXPC", ["author"])])
    by = {c["pair"]: c for c in merged}
    assert [k for k, _ in by["DOS/USDT:USDT"]["reasons"]] == ["author", "hour_spike"] and len(merged) == 2
    prev = [("(A)/.*", ""), ("(B)/.*", "")]
    assert sa.diff(None, prev) == ([], [])                # first run: no news
    assert sa.diff(prev, [("(B)/.*", ""), ("(C)/.*", "x")]) == ([("(C)/.*", "x")], [("(A)/.*", "")])
    assert sa.accept([], [("a", "")], 0.5) and sa.accept(prev, prev[:1], 0.5) and not sa.accept(prev * 3, prev[:2], 0.5)
    assert sa.matching("(NXPC)/.*", ["NXPC/USDT:USDT", "NXPCX/USDT:USDT"]) == ["NXPC/USDT:USDT"]


def test_author_own_limit_and_live_filter():
    found = [cand("P%d" % i, ["author"]) for i in range(17)] + [cand("D%d" % i, ["hour_spike"]) for i in range(7)]
    s, a, e = st.plan(CFG, found, {}, none_blocked, set(), NOW)
    assert len(e["new_perm"]) == 15 and len(e["new_temp"]) == 5 and len(e["skipped"]) == 2 + 2  # author 17-15, detectors 7-5
    shadow_add = st.live_filter(CFG, s, a, e, shadow=True)["add"]
    assert len(shadow_add) == 15 and all(p.startswith("P") for p in shadow_add)  # detectors stay in the shadow
    assert len(st.live_filter(CFG, s, a, e, shadow=False)["add"]) == 20
    assert st.is_live(dict(CFG, author_sync_live=False), ["author"], False) is False


def test_run_author_live_detectors_shadow():
    with tempfile.TemporaryDirectory() as tmp:
        calls, cfg = run_once(tmp, dry=False, shadow=True, author=AUTHOR)
        adds = [c for c in calls if c[0] == "add"]
        assert adds == [("add", ["NXPC/USDT:USDT"])]               # DOS (detector) stays shadow; OLD is in the file
        text = calls[1][1]
        assert "NXPC/USDT:USDT" in text and "DOS/USDT:USDT [в вайтлисте] [тень]" in text and "[пометка [тень]" in text
        assert "(IMO)/.*" not in text                              # first run: the list is the baseline, no news
        state = json.loads(Path(cfg["state_file"]).read_text(encoding="utf-8"))
        assert state["author_info"]["entries"] == 3 and state["author_info"]["noperp"] == 1
        assert len(state["author_cache"]) == 3 and "NXPC/USDT:USDT" in state["perm"]
        # restart of the bot (runtime empty): light run puts NXPC back, reports it, never reads candles
        calls, _ = run_once(tmp, dry=False, state=state, shadow=True, sync=True, author=AUTHOR)
        assert [c for c in calls if c[0] == "add"] == [("add", ["NXPC/USDT:USDT"])]
        assert "Блоки восстановлены после рестарта бота: NXPC/USDT:USDT" in [c for c in calls if c[0] == "telegram"][0][1]


def test_author_list_changes_are_reported_not_applied():
    with tempfile.TemporaryDirectory() as tmp:
        _, cfg = run_once(tmp, dry=False, shadow=True, author=AUTHOR)
        state = json.loads(Path(cfg["state_file"]).read_text(encoding="utf-8"))
        new = AUTHOR.replace('"(OLD)/.*"', '"(NEWNOPERP)/.*"')
        calls, cfg = run_once(tmp, dry=False, state=state, shadow=True, author=new, runtime={"NXPC/USDT:USDT"})
        text = [c for c in calls if c[0] == "telegram"][0][1]
        assert "перпа на Binance нет (ничего не меняет): (NEWNOPERP)/.*" in text
        assert "Автор УБРАЛ" in text and "(OLD)/.*" in text        # OLD is blocked by our file -> worth a word
        assert [c for c in calls if c[0] == "remove"] == []        # never released here
        st2 = json.loads(Path(cfg["state_file"]).read_text(encoding="utf-8"))
        assert st2["author_changed"] > 0


def test_author_failure_uses_cache_and_alerts_once():
    with tempfile.TemporaryDirectory() as tmp:
        _, cfg = run_once(tmp, dry=False, shadow=True, author=AUTHOR)
        state = json.loads(Path(cfg["state_file"]).read_text(encoding="utf-8"))
        calls, cfg = run_once(tmp, dry=False, state=state, shadow=True, author=OSError("down"), runtime={"NXPC/USDT:USDT"})
        errs = [c[1] for c in calls if c[0] == "telegram" and "не получен" in c[1]]
        assert len(errs) == 1 and "down" in errs[0]
        state2 = json.loads(Path(cfg["state_file"]).read_text(encoding="utf-8"))
        assert len(state2["author_cache"]) == 3 and "NXPC/USDT:USDT" in state2["perm"]  # last good copy kept
        calls, _ = run_once(tmp, dry=False, state=state2, shadow=True, author=OSError("down"), runtime={"NXPC/USDT:USDT"})
        assert [c for c in calls if c[0] == "telegram" and "не получен" in c[1]] == []   # not again within 6 h
        # a list that lost most of its entries is not trusted either
        tiny = '{\n"exchange": {\n"pair_blacklist": [\n"(NXPC)/.*"\n]\n}\n}'
        calls, _ = run_once(tmp, dry=False, state=state, shadow=True, author=tiny, runtime={"NXPC/USDT:USDT"})
        assert any("shrank" in c[1] for c in calls if c[0] == "telegram")


def test_persisted_pair_is_forgotten_not_reblocked():
    """Regression (server dry-run 23.10): a pair now in the file must not come back as a new block each run."""
    with tempfile.TemporaryDirectory() as tmp:
        _, cfg = run_once(tmp, dry=False, shadow=True, author=AUTHOR)
        state = json.loads(Path(cfg["state_file"]).read_text(encoding="utf-8"))
        assert "NXPC/USDT:USDT" in state["perm"]
        for sync in (False, True):  # the file now holds NXPC; the bot loaded it, so it is in "expanded"
            calls, _ = run_once(tmp, dry=False, state=state, shadow=True, sync=sync, author=AUTHOR,
                                files=("(OLD)/.*", "(NXPC)/.*"), expanded={"NXPC/USDT:USDT"})
            assert [c for c in calls if c[0] in ("add", "remove")] == []
            text = [c[1] for c in calls if c[0] == "telegram"][0]
            assert "Закреплено в файле, скрипт больше не ведёт: NXPC/USDT:USDT" in text
            assert "Постоянный блок" not in text
        calls, _ = run_once(tmp, dry=False, shadow=True, author=AUTHOR,   # state saved by the last run: quiet now
                            state=json.loads(Path(cfg["state_file"]).read_text(encoding="utf-8")),
                            files=("(OLD)/.*", "(NXPC)/.*"), expanded={"NXPC/USDT:USDT"})
        assert [c for c in calls if "Закреплено" in c[1] or "Постоянный" in c[1]] == []


def test_lock():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "x.lock")
        assert bs.acquire_lock(path, 600, 0)
        assert not bs.acquire_lock(path, 600, 0)           # held
        os.utime(path, (1, 1))
        assert bs.acquire_lock(path, 600, 0)               # stale one is taken over
        os.remove(path)


if __name__ == "__main__":
    tests = [v for name, v in sorted(globals().items()) if name.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)
    print("%d tests passed" % len(tests))
