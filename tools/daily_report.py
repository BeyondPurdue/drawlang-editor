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

import html as _html
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


# ---------------------------------------------------------------------------
# HTML composer
# ---------------------------------------------------------------------------
#
# Design goals:
#   * Gmail-safe: table-based single-column layout, inline styles only, no
#     external CSS, no <style> tag with pseudo-classes, no web fonts.
#   * Skimmable: KPI hero row at the top so the four numbers that matter
#     (users, canvases touched, commits, deploy status) are visible without
#     scrolling on both desktop and mobile.
#   * Nexus palette (warm off-white surface, ink text, Hydra Teal accent).
#
# Anything that renders differently between clients (Gmail, Outlook, Apple
# Mail, Superhuman) is a bug — keep the HTML boring.

_C = {
    "bg":       "#F7F6F2",
    "surface":  "#FFFFFF",
    "border":   "#D4D1CA",
    "ink":      "#28251D",
    "muted":    "#7A7974",
    "faint":    "#BAB9B4",
    "accent":   "#01696F",
    "good":     "#437A22",
    "warn":     "#964219",
    "error":    "#A12C7B",
}


def _esc(s) -> str:
    return _html.escape(str(s), quote=True)


def _kpi(label: str, value, hint: str = "", color: str = None) -> str:
    color = color or _C["ink"]
    return (
        f'<td align="center" valign="top" width="25%" '
        f'style="padding:14px 8px;border:1px solid {_C["border"]};'
        f'border-radius:8px;background:{_C["surface"]};">'
        f'<div style="font:600 26px/1.1 -apple-system,BlinkMacSystemFont,'
        f'Segoe UI,Arial,sans-serif;color:{color};'
        f'font-variant-numeric:tabular-nums;">{_esc(value)}</div>'
        f'<div style="font:500 11px/1.4 -apple-system,BlinkMacSystemFont,'
        f'Segoe UI,Arial,sans-serif;color:{_C["muted"]};'
        f'text-transform:uppercase;letter-spacing:.06em;margin-top:6px;">'
        f'{_esc(label)}</div>'
        + (f'<div style="font:400 11px/1.4 -apple-system,BlinkMacSystemFont,'
           f'Segoe UI,Arial,sans-serif;color:{_C["faint"]};margin-top:2px;">'
           f'{_esc(hint)}</div>' if hint else '')
        + '</td>'
    )


def _section_open(title: str) -> str:
    return (
        f'<tr><td style="padding:20px 0 10px 0;">'
        f'<div style="font:600 11px/1 -apple-system,BlinkMacSystemFont,'
        f'Segoe UI,Arial,sans-serif;color:{_C["accent"]};'
        f'text-transform:uppercase;letter-spacing:.08em;">{_esc(title)}</div>'
        f'</td></tr>'
        f'<tr><td style="padding:0;">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
        f'style="background:{_C["surface"]};border:1px solid {_C["border"]};border-radius:8px;">'
    )


def _section_close() -> str:
    return "</table></td></tr>"


def _row_kv(label: str, value_html: str) -> str:
    return (
        f'<tr><td style="padding:8px 14px;border-bottom:1px solid {_C["border"]};'
        f'font:400 13px/1.5 -apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;'
        f'color:{_C["muted"]};width:38%;">{_esc(label)}</td>'
        f'<td style="padding:8px 14px;border-bottom:1px solid {_C["border"]};'
        f'font:500 13px/1.5 -apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;'
        f'color:{_C["ink"]};font-variant-numeric:tabular-nums;">{value_html}</td></tr>'
    )


def _row_list(items_html: list[str]) -> str:
    if not items_html:
        return ""
    body = "".join(
        f'<tr><td style="padding:6px 14px;'
        f'border-bottom:1px solid {_C["border"]};'
        f'font:400 13px/1.5 -apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;'
        f'color:{_C["ink"]};">{it}</td></tr>' for it in items_html
    )
    return body


def _pill(text: str, color: str) -> str:
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
        f'background:{color}1A;color:{color};'
        f'font:600 11px/1.4 -apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;'
        f'text-transform:uppercase;letter-spacing:.04em;">{_esc(text)}</span>'
    )


def compose_html(data: dict) -> str:
    site = data["site"]
    repo = data["repo"]
    base = data["base"]
    repo_url = f"https://github.com/{repo['name']}"

    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    weekday = datetime.now().astimezone().strftime("%A")

    u, c, t = site["users"], site["content"], site["traffic"]
    dr = site.get("demo_reset") or {}

    deploy_ok = not repo["deploy_lag"]
    deploy_pill = _pill(
        "in sync" if deploy_ok else "deploy lag",
        _C["good"] if deploy_ok else _C["warn"],
    )

    # KPI hero row — the four numbers that matter.
    kpi_row = (
        '<tr>' +
        _kpi("New users (24h)", len(u["new_24h"]), f"total {u['total']}") +
        '<td width="8">&nbsp;</td>' +
        _kpi("New canvases", c["canvases_new_24h"],
             f"{c['canvases_updated_24h']} touched") +
        '<td width="8">&nbsp;</td>' +
        _kpi("Commits (24h)", len(repo["commits_24h"]),
             f"{repo['live_sha']} live") +
        '<td width="8">&nbsp;</td>' +
        _kpi(
            "Traffic (24h)",
            t["views_24h"],
            f"{t['sessions_24h']} sessions",
            color=_C["accent"],
        ) +
        '</tr>'
    )

    # Users section.
    users_rows = [
        _row_kv("Total accounts", _esc(u["total"])),
        _row_kv("Active", _esc(u["active"])),
        _row_kv("Pending", _esc(u["pending"])),
    ]
    if u["new_24h"]:
        users_rows.append(_row_kv(
            "New in last 24h", f'<strong>{len(u["new_24h"])}</strong>'))
        for r in u["new_24h"]:
            item = (
                f'<strong>{_esc(r["email"])}</strong>'
                f'<span style="color:{_C["muted"]};"> — '
                f'{_esc(r["display_name"] or "—")} · role {_esc(r["role"])} · '
                f'{_esc(r["status"])} · '
                f'{_esc(_fmt_ts(r["created_at"]))}</span>'
            )
            users_rows.append(
                f'<tr><td colspan="2" style="padding:8px 14px;'
                f'border-bottom:1px solid {_C["border"]};'
                f'font:400 13px/1.5 -apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;'
                f'color:{_C["ink"]};">{item}</td></tr>'
            )
    else:
        users_rows.append(_row_kv(
            "New in last 24h",
            f'<span style="color:{_C["muted"]};">No new signups.</span>'))

    users_html = _section_open("Users") + "".join(users_rows) + _section_close()

    # Content + traffic + demo reset — combined "Content & traffic" card.
    content_rows = [
        _row_kv("Canvases",
                f'{_esc(c["canvases_total"])} '
                f'<span style="color:{_C["muted"]};">'
                f'(+{_esc(c["canvases_new_24h"])} new · '
                f'{_esc(c["canvases_updated_24h"])} touched)</span>'),
        _row_kv("Frames", _esc(c["frames_total"])),
        _row_kv("Library templates", _esc(c["library_total"])),
        _row_kv("Traffic — last 24h",
                f'{_esc(t["views_24h"])} views '
                f'<span style="color:{_C["muted"]};">· '
                f'{_esc(t["sessions_24h"])} sessions</span>'),
        _row_kv("Traffic — last 7 days",
                f'{_esc(t["views_7d"])} views '
                f'<span style="color:{_C["muted"]};">· '
                f'{_esc(t["sessions_7d"])} sessions</span>'),
    ]
    if dr.get("at"):
        seeded = dr.get("seeded") or {}
        wiped = dr.get("wiped") or {}
        content_rows.append(_row_kv(
            "Demo reset — last",
            f'{_esc(_fmt_ts(dr["at"]))} '
            f'<span style="color:{_C["muted"]};">— wiped '
            f'{_esc(wiped.get("canvases"))} canvases · '
            f'{_esc(wiped.get("frames"))} frames · '
            f'{_esc(wiped.get("library"))} lib, seeded '
            f'{_esc(seeded.get("canvases_copied"))} · '
            f'{_esc(seeded.get("frames_copied"))} · '
            f'{_esc(seeded.get("library_copied"))}</span>'))
    else:
        content_rows.append(_row_kv(
            "Demo reset",
            f'<span style="color:{_C["muted"]};">no reset since server start</span>'))

    content_html = _section_open("Content & traffic") + "".join(content_rows) + _section_close()

    # Repo section.
    repo_rows = [
        _row_kv(
            "Deployment",
            f'latest <code style="background:{_C["bg"]};padding:1px 5px;'
            f'border-radius:3px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;'
            f'font-size:12px;">{_esc(repo["latest_sha"])}</code> · '
            f'live <code style="background:{_C["bg"]};padding:1px 5px;'
            f'border-radius:3px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;'
            f'font-size:12px;">{_esc(repo["live_sha"])}</code> &nbsp;{deploy_pill}'),
        _row_kv(
            "Repo stats",
            f'{_esc(repo["stars"])} <span style="color:{_C["muted"]};">stars</span> · '
            f'{_esc(repo["forks"])} <span style="color:{_C["muted"]};">forks</span> · '
            f'{len(repo["open_prs"])} <span style="color:{_C["muted"]};">open PRs</span> · '
            f'{len(repo["open_issues"])} <span style="color:{_C["muted"]};">open issues</span>'),
    ]

    if repo["commits_24h"]:
        repo_rows.append(
            f'<tr><td colspan="2" style="padding:10px 14px 4px 14px;'
            f'border-bottom:1px solid {_C["border"]};'
            f'font:600 11px/1 -apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;'
            f'color:{_C["muted"]};text-transform:uppercase;letter-spacing:.06em;">'
            f'Commits in last 24h ({len(repo["commits_24h"])})</td></tr>')
        for cm in repo["commits_24h"]:
            sha_link = f'{repo_url}/commit/{_esc(cm["sha"])}'
            repo_rows.append(
                f'<tr><td colspan="2" style="padding:6px 14px;'
                f'border-bottom:1px solid {_C["border"]};'
                f'font:400 13px/1.5 -apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;'
                f'color:{_C["ink"]};">'
                f'<a href="{sha_link}" style="color:{_C["accent"]};text-decoration:none;'
                f'font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;">'
                f'{_esc(cm["sha"])}</a>'
                f' <span style="color:{_C["muted"]};">{_esc(cm["author"])}:</span> '
                f'{_esc(cm["msg"])}</td></tr>')
    else:
        repo_rows.append(_row_kv(
            "Commits in last 24h",
            f'<span style="color:{_C["muted"]};">None.</span>'))

    if repo["open_prs"]:
        repo_rows.append(
            f'<tr><td colspan="2" style="padding:10px 14px 4px 14px;'
            f'border-bottom:1px solid {_C["border"]};'
            f'font:600 11px/1 -apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;'
            f'color:{_C["muted"]};text-transform:uppercase;letter-spacing:.06em;">'
            f'Open PRs ({len(repo["open_prs"])})</td></tr>')
        for pr in repo["open_prs"]:
            pr_link = f'{repo_url}/pull/{pr["n"]}'
            repo_rows.append(
                f'<tr><td colspan="2" style="padding:6px 14px;'
                f'border-bottom:1px solid {_C["border"]};'
                f'font:400 13px/1.5 -apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;'
                f'color:{_C["ink"]};">'
                f'<a href="{pr_link}" style="color:{_C["accent"]};text-decoration:none;">'
                f'#{_esc(pr["n"])}</a> {_esc(pr["title"])} '
                f'<span style="color:{_C["muted"]};">by {_esc(pr["user"])}</span></td></tr>')

    if repo["open_issues"]:
        repo_rows.append(
            f'<tr><td colspan="2" style="padding:10px 14px 4px 14px;'
            f'border-bottom:1px solid {_C["border"]};'
            f'font:600 11px/1 -apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;'
            f'color:{_C["muted"]};text-transform:uppercase;letter-spacing:.06em;">'
            f'Open issues ({len(repo["open_issues"])})</td></tr>')
        for iss in repo["open_issues"]:
            iss_link = f'{repo_url}/issues/{iss["n"]}'
            repo_rows.append(
                f'<tr><td colspan="2" style="padding:6px 14px;'
                f'border-bottom:1px solid {_C["border"]};'
                f'font:400 13px/1.5 -apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;'
                f'color:{_C["ink"]};">'
                f'<a href="{iss_link}" style="color:{_C["accent"]};text-decoration:none;">'
                f'#{_esc(iss["n"])}</a> {_esc(iss["title"])} '
                f'<span style="color:{_C["muted"]};">by {_esc(iss["user"])}</span></td></tr>')

    repo_html = _section_open(f"Repository — {repo['name']}") + "".join(repo_rows) + _section_close()

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DrawLang daily summary — {_esc(today)}</title>
</head>
<body style="margin:0;padding:0;background:{_C['bg']};">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:{_C['bg']};">
  <tr><td align="center" style="padding:24px 12px;">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600" style="max-width:600px;width:100%;">

      <tr><td style="padding:0 0 6px 0;">
        <div style="font:600 11px/1 -apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;color:{_C['muted']};text-transform:uppercase;letter-spacing:.1em;">DrawLang editor · daily summary</div>
      </td></tr>
      <tr><td style="padding:0 0 4px 0;">
        <div style="font:600 22px/1.25 -apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;color:{_C['ink']};">{_esc(weekday)}, {_esc(today)}</div>
      </td></tr>
      <tr><td style="padding:0 0 18px 0;">
        <a href="{_esc(base)}" style="color:{_C['accent']};text-decoration:none;font:500 13px/1.5 -apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;">{_esc(base)}</a>
      </td></tr>

      <tr><td>
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
          {kpi_row}
        </table>
      </td></tr>

      {users_html}

      {content_html}

      {repo_html}

      <tr><td style="padding:24px 0 8px 0;">
        <div style="font:400 12px/1.5 -apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;color:{_C['faint']};text-align:center;">— sent automatically by Perplexity Computer</div>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""
    return doc


if __name__ == "__main__":
    data = collect()
    subject, body = compose(data)
    html_body = compose_html(data)
    print(json.dumps(
        {"subject": subject, "body": body, "html_body": html_body},
        indent=2,
    ))
