import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ops_render as rd  # noqa: E402
import ops_snapshot as os_  # noqa: E402

PRIVATE = {"api_server": {"username": "freqadmin", "password": "pw-secret-123", "jwt_secret_key": "j" * 40},
           "telegram": {"token": "123456:ABC-token", "chat_id": "987654321"}, "dry_run": True}
SHOW = {"state": "running", "strategy": "NostalgiaForInfinityX7", "strategy_version": "v17.5.178",
        "max_open_trades": 6, "stake_amount": "unlimited", "timeframe": "5m"}
TRADE = {"trade_id": 203, "pair": "BTW/USDT:USDT", "is_short": False, "leverage": 3.0,
         "open_date": "2026-10-20 10:15:00", "profit_pct": -1.5, "profit_abs": -4.2, "stake_amount": 100.0}


def data(**kw):
    d = {"ts": "2026-10-29 12:00", "errors": {}, "show": SHOW, "service": "active",
         "profit": {"closed_trade_count": 50, "winning_trades": 49, "losing_trades": 1, "winrate": 0.98,
                    "profit_closed_coin": 123.4, "profit_all_coin": 119.2},
         "status": [TRADE], "balance": {"total": 1500.5}, "count": {"current": 1, "max": 6},
         "blacklist": {"runtime": ["MITO/USDT:USDT"], "whitelist_n": 40},
         "scout": {"temp": {"ICNT/USDT:USDT": {}}, "perm": {}, "author_info": {"entries": 38, "noperp": 12, "changed": 1793269206.0}},
         "journal": [], "tails": {"scout sync": ["line one"]}}
    d.update(kw)
    return d


def test_redact_cuts_every_credential():
    secrets = rd.secret_values(PRIVATE)
    text = "login pw-secret-123 token 123456:ABC-token chat 987654321 user freqadmin " + "j" * 40
    out = rd.redact(text, secrets)
    for s in ("pw-secret-123", "123456:ABC-token", "987654321", "freqadmin", "j" * 40):
        assert s not in out, s


def test_build_has_sections_and_open_trade():
    text = rd.build(data())
    for part in ("# NFI snapshot 2026-10-29 12:00 UTC", "v17.5.178", "BTW/USDT:USDT", "wallet total: 1500.50",
                 "Open trades (1, unrealized -4.20)", "ICNT/USDT:USDT", "line one", "38 entries", "blacklist entries in the bot"):
        assert part in text, part
    assert "## Errors" not in text


def test_build_surfaces_unreachable_api():
    text = rd.build(data(errors={"api login": "URLError"}, show=None, profit=None, status=None,
                         balance=None, count=None, blacklist=None, scout=None, service="inactive"))
    assert "## Errors" in text and "api login: URLError" in text
    assert "service: inactive" in text and "## Open trades\n\nn/a" in text


def test_collect_records_failed_sources():
    cfg = json.loads((HERE / "ops_snapshot_config.json").read_text(encoding="utf-8"))
    cfg["scout_state_file"] = "no_such_state.json"
    cfg["log_tails"] = {}
    cfg["service_name"] = "no-such-service-xyz"
    private = {"api_server": {"listen_ip_address": "127.0.0.1", "listen_port": 1, "username": "u", "password": "p"}}
    d = os_.collect(cfg, private, 1_700_000_000)
    assert "api login" in d["errors"] and "scout state" in d["errors"]
    assert d["service"] and isinstance(d["journal"], list)


def test_missing_tool_is_reported_not_raised():
    code, out = os_.run_cmd(["no-such-tool-xyz"], 5)
    assert code == 127 and "no-such-tool-xyz" in out


def sh(*a, cwd=None):
    subprocess.run(list(a), cwd=cwd, check=True, capture_output=True, text=True)


def test_publish_commits_only_on_change():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        sh("git", "init", "--bare", "-b", "main", str(tmp / "remote.git"))
        sh("git", "init", "-b", "main", str(tmp / "seed"))
        (tmp / "seed" / "README.md").write_text("seed\n")
        sh("git", "-C", str(tmp / "seed"), "add", ".")
        sh("git", "-C", str(tmp / "seed"), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "seed")
        sh("git", "-C", str(tmp / "seed"), "push", str(tmp / "remote.git"), "main")
        sh("git", "clone", str(tmp / "remote.git"), str(tmp / "work"))
        cfg = json.loads((HERE / "ops_snapshot_config.json").read_text(encoding="utf-8"))
        cfg["ops_repo_dir"] = str(tmp / "work")
        assert os_.publish(cfg, "state A\n", "t1") == "pushed"
        assert os_.publish(cfg, "state A\n", "t2") == "no change"
        assert os_.publish(cfg, "state B\n", "t3") == "pushed"
        log = subprocess.run(["git", "-C", str(tmp / "remote.git"), "log", "--format=%s", "main"],
                             capture_output=True, text=True, check=True).stdout.splitlines()
        assert log == ["snapshot t3 UTC", "snapshot t1 UTC", "seed"], log
        shown = subprocess.run(["git", "-C", str(tmp / "remote.git"), "show", "main:snapshot.md"],
                               capture_output=True, text=True, check=True).stdout
        assert shown == "state B\n"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)
    print("%d tests passed" % len(tests))
