#!/usr/bin/env python3
"""Compose the DrawLang daily summary email.

Reads:
  - https://editor.drawlang.com/api/admin/daily-summary  (with admin creds)
  - GitHub REST for BeyondPurdue/drawlang-editor via `gh api`

Prints the composed message (subject + plain-text body) to stdout as JSON.
The caller (a scheduled task) is responsible for actually sending via the
Gmail connector. Kept side-effect free so it can be dry-run safely.

Env:
  DRAWLANG_ADMIN_EMAIL      admin login (default: petr@bohemiamarket.com)
  DRAWLANG_ADMIN_PASSWORD   admin password (required)
  DRAWLANG_SITE_URL         base URL (default: https://editor.drawlang.com)
  DRAWLANG_REPO             owner/name (default: BeyondPurdue/drawlang-editor)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone


def _login(session_file: str, base: str, email: str, password: str) -> None:
    r = subprocess.run(
        [
            "curl", "-fsS", "-c", session_file,
            "-X", "POST", f"{base}/api/auth/login",
            "-H", "content-type: application/json",
            "-d", json.dumps({"email": email, "password": password}),
        ],
        check=True, capture_output=True,
    )
    body = json.loads(r.stdout or "{}")
    if not body.get("ok"):
        raise SystemExit(f"login failed: {body}")


def _get(session_file: str, url: str) -> dict:
    r = subprocess.run(
        ["curl", "-fsS", "-b", session_file, url],
        check=True, capture_output=True,
    )
    return json.loads(r.stdout)


def _gh(*args: str) -> str:
    return subprocess.run(
        ["gh", "api", *args], check=True, capture_output=True, text=True
    ).stdout


def _fmt_ts(ts: float | None) -> str:
    if not ts:
        return "never"
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
    return dt.strftime("%Y-%m-%d %H:%M %Z")


def collect() -> dict:
    base = os.environ.get("DRAWLANG_SITE_URL", "https://editor.drawlang.com")
    email = os.environ.get("DRAWLANG_ADMIN_EMAIL", "petr@bohemiamarket.com")
    password = os.environ["DRAWLANG_ADMIN_PASSWORD"]
    repo = os.environ.get("DRAWLANG_REPO", "BeyondPurdue/drawlang-editor")

    session = "/tmp/drawlang-daily.txt"
    try:
        os.remove(session)
    except FileNotFoundError:
        pass
    _login(session, base, email, password)
    site = _get(session, f"{base}/api/admin/daily-summary")

    # Repo meta.
    since = datetime.fromtimestamp(
        time.time() - 86400, tz=timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    commits = json.loads(_gh(f"repos/{repo}/commits?since={since}"))
    open_prs = json.loads(_gh(f"repos/{repo}/pulls?state=open"))
    open_issues = [
        i for i in json.loads(_gh(f"repos/{repo}/issues?state=open"))
        if i.get("pull_request") is None
    ]
    meta = json.loads(_gh(f"repos/{repo}"))
    latest_sha = commits[0]["sha"][:7] if commits else meta["default_branch"]

    # Live sha on prod.
    live_sha = _get(session, f"{base}/health").get("git_sha", "?")[:7]

    return {
        "base": base,
        "site": site,
        "repo": {
            "name": repo,
            "stars": meta["stargazers_count"],
            "forks": meta["forks_count"],
            "open_issues_count": meta["open_issues_count"],
            "commits_24h": [
                {
                    "sha": c["sha"][:7],
                    "author": c["commit"]["author"]["name"],
                    "date": c["commit"]["author"]["date"],
                    "msg": c["commit"]["message"].splitlines()[0],
                }
                for c in commits
            ],
            "open_prs": [
                {"n": p["number"], "title": p["title"], "user": p["user"]["login"]}
                for p in open_prs
            ],
            "open_issues": [
                {"n": i["number"], "title": i["title"], "user": i["user"]["login"]}
                for i in open_issues
            ],
            "latest_sha": latest_sha,
            "live_sha": live_sha,
            "deploy_lag": latest_sha != live_sha,
        },
    }


def compose(data: dict) -> tuple[str, str]:
    site = data["site"]
    repo = data["repo"]

    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    subject = (
        f"DrawLang daily · {today} · "
        f"{len(site['users']['new_24h'])} new user(s), "
        f"{site['content']['canvases_new_24h']} new canvas(es), "
        f"{len(repo['commits_24h'])} commit(s)"
    )

    lines: list[str] = []
    lines.append(f"DrawLang editor — daily summary ({today})")
    lines.append(f"Site: {data['base']}")
    lines.append("")

    # Users.
    u = site["users"]
    lines.append(
        f"USERS  total={u['total']}  active={u['active']}  pending={u['pending']}"
    )
    if u["new_24h"]:
        lines.append(f"  New in last 24h ({len(u['new_24h'])}):")
        for row in u["new_24h"]:
            lines.append(
                f"    - {row['email']}  ({row['display_name']}, "
                f"role={row['role']}, status={row['status']}, "
                f"created {_fmt_ts(row['created_at'])})"
            )
    else:
        lines.append("  No new signups.")
    lines.append("")

    # Content.
    c = site["content"]
    lines.append(
        f"CONTENT  canvases={c['canvases_total']} "
        f"(+{c['canvases_new_24h']} new, {c['canvases_updated_24h']} touched)  "
        f"frames={c['frames_total']}  library={c['library_total']}"
    )

    # Traffic.
    t = site["traffic"]
    lines.append(
        f"TRAFFIC 24h  views={t['views_24h']}  sessions={t['sessions_24h']}  "
        f"|  7d  views={t['views_7d']}  sessions={t['sessions_7d']}"
    )

    # Demo reset.
    dr = site.get("demo_reset") or {}
    if dr.get("at"):
        seeded = dr.get("seeded") or {}
        wiped = dr.get("wiped") or {}
        lines.append(
            f"DEMO RESET  last {_fmt_ts(dr['at'])} — "
            f"wiped canvases={wiped.get('canvases')} frames={wiped.get('frames')} "
            f"library={wiped.get('library')}, seeded canvases={seeded.get('canvases_copied')} "
            f"frames={seeded.get('frames_copied')} library={seeded.get('library_copied')}"
        )
    else:
        lines.append("DEMO RESET  no reset since server start")
    lines.append("")

    # Repo.
    lines.append(f"REPO {repo['name']}")
    lines.append(
        f"  latest commit={repo['latest_sha']}  live sha={repo['live_sha']}  "
        f"{'DEPLOY LAG' if repo['deploy_lag'] else 'in sync'}"
    )
    lines.append(
        f"  stars={repo['stars']}  forks={repo['forks']}  "
        f"open PRs={len(repo['open_prs'])}  open issues={len(repo['open_issues'])}"
    )
    if repo["commits_24h"]:
        lines.append(f"  Commits in last 24h ({len(repo['commits_24h'])}):")
        for c in repo["commits_24h"]:
            lines.append(f"    - {c['sha']}  {c['author']}: {c['msg']}")
    else:
        lines.append("  No commits in last 24h.")
    if repo["open_prs"]:
        lines.append(f"  Open PRs ({len(repo['open_prs'])}):")
        for p in repo["open_prs"]:
            lines.append(f"    - #{p['n']} {p['title']} (by {p['user']})")
    if repo["open_issues"]:
        lines.append(f"  Open issues ({len(repo['open_issues'])}):")
        for i in repo["open_issues"]:
            lines.append(f"    - #{i['n']} {i['title']} (by {i['user']})")
    lines.append("")
    lines.append("— sent automatically by Perplexity Computer")

    return subject, "\n".join(lines)


if __name__ == "__main__":
    data = collect()
    subject, body = compose(data)
    print(json.dumps({"subject": subject, "body": body}, indent=2))
