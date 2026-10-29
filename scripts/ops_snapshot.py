#!/usr/bin/env python3
"""
Ops snapshot: one readable markdown file with the live state of the bot,
committed and pushed to the private NFI-ops repo, so the state can be read
without copy-pasting command output.

Read-only towards the bot (GET requests, journalctl, systemctl). A source that
fails is written into the snapshot as an error line; a snapshot that says
"API unreachable" is the point of the tool. Credentials from the private config
are cut from the text before it is written.

Usage (server, cron, hourly):
    python3 scripts/ops_snapshot.py             # build, commit, push
    python3 scripts/ops_snapshot.py --dry-run   # print only
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import blacklist_scout as bs  # noqa: E402
import ops_render as rd  # noqa: E402
import risk_digest as rdg  # noqa: E402

CONFIG_PATH = HERE / "ops_snapshot_config.json"


def tail(path, n):
    p = Path(path)
    if not p.exists():
        return ["(missing file %s)" % p.name]
    return p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]


def run_cmd(args, timeout):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:  # missing tool or hang: report, do not crash
        return 127, "(%s failed: %r)" % (args[0], e)
    return r.returncode, (r.stdout + r.stderr).strip()


def safe(errors, name, fn):
    try:
        return fn()
    except Exception as e:  # a failed source is data for the snapshot, not a crash
        errors[name] = repr(e)[:300]
        return None


def fetch_trades(bot, page):
    out, offset = [], 0
    while True:
        res = bot.get("/trades?limit=%d&offset=%d" % (page, offset))
        out += res["trades"]
        offset += page
        if len(res["trades"]) < page or offset >= res["total_trades"]:
            return out


def collect(cfg, private, now_s):
    errors = {}
    d = {"ts": datetime.fromtimestamp(now_s, timezone.utc).strftime("%Y-%m-%d %H:%M"), "errors": errors}
    bot = safe(errors, "api login", lambda: bs.Bot(private["api_server"], cfg["request_timeout_sec"]))
    if bot is not None:
        for key, path in (("show", "/show_config"), ("profit", "/profit"), ("status", "/status"),
                          ("balance", "/balance"), ("count", "/count")):
            d[key] = safe(errors, path, lambda p=path: bot.get(p))
        live = safe(errors, "/blacklist", lambda: {"runtime": bot.get("/blacklist")["blacklist"],
                                                   "whitelist_n": len(bot.get("/whitelist")["whitelist"])})
        d["blacklist"] = live
    d["trades"] = safe(errors, "/trades", lambda: fetch_trades(bot, cfg["trades_page"])) if bot else None
    d["scout"] = safe(errors, "scout state", lambda: json.loads((HERE / cfg["scout_state_file"]).read_text(encoding="utf-8")))
    code, out = run_cmd(["systemctl", "is-active", cfg["service_name"]], cfg["command_timeout_sec"])
    d["service"] = out or "n/a"
    code, out = run_cmd(["journalctl", "-u", cfg["service_name"], "--since", cfg["journal_since"],
                         "-p", "warning", "--no-pager", "-o", "cat"], cfg["command_timeout_sec"])
    d["journal"] = out.splitlines()[-cfg["journal_tail_lines"]:]
    d["tails"] = {name: tail(HERE / fname, n) for name, (fname, n) in cfg["log_tails"].items()}
    return d


def git(repo, *args, timeout=120):
    r = subprocess.run(["git", "-C", str(repo)] + list(args), capture_output=True, text=True, timeout=timeout)
    if r.returncode not in (0, 1) or (r.returncode == 1 and args[0] != "diff"):
        raise RuntimeError("git %s failed: %s" % (" ".join(args[:2]), (r.stdout + r.stderr).strip()))
    return r.returncode


def publish(cfg, files, ts):
    """Write files (name -> text) into the ops repo clone; commit and push only when something changed."""
    repo = Path(cfg["ops_repo_dir"])
    git(repo, "pull", "--rebase", "--quiet")
    for name, text in files.items():
        (repo / name).write_text(text, encoding="utf-8", newline="")
    git(repo, "add", *files)
    if git(repo, "diff", "--cached", "--quiet") == 0:
        return "no change"
    git(repo, "-c", "user.name=" + cfg["git_user_name"], "-c", "user.email=" + cfg["git_user_email"],
        "commit", "--quiet", "-m", cfg["commit_message"].format(ts=ts))
    git(repo, "push", "--quiet", "origin", "HEAD")
    return "pushed"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print only: no commit, no push")
    args = ap.parse_args()
    cfg = rdg.load_json(CONFIG_PATH)
    env = dict(rdg.load_env_file(HERE / cfg["env_file"]))
    env.update(os.environ)
    private = rdg.apply_env_overrides(rdg.load_json(HERE / cfg["private_config"]), env)
    d = collect(cfg, private, time.time())
    text = rd.redact(rd.build(d), rd.secret_values(private))
    if args.dry_run:
        print(text)
        return
    files = {cfg["snapshot_file"]: text}
    if d.get("trades") is not None:  # a failed fetch keeps the previous trades file untouched
        files[cfg["trades_file"]] = rd.trades_csv(d["trades"], cfg["trade_fields"])
    print(publish(cfg, files, d["ts"]))


if __name__ == "__main__":
    main()
