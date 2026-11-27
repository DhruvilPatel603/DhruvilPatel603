#!/usr/bin/env python3
"""Fetch live PRs and recent public GitHub commits/events for DhruvilPatel603 and generate SVGs."""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

USER = os.environ.get("GITHUB_USER", "DhruvilPatel603")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def trunc(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def fmt_date(iso_str: str) -> str:
    try:
        parsed = dt.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return parsed.strftime("%b %d")
    except Exception:
        return iso_str[:10]


def gh_get(url: str):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{USER}-profile-live-feed",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_prs() -> list[dict]:
    url = f"https://api.github.com/search/issues?q=author:{USER}+type:pr&sort=updated&order=desc&per_page=100"
    data = gh_get(url)
    items = []
    for it in data.get("items", []):
        repo = it["repository_url"].split("/repos/")[-1]
        pr_info = it.get("pull_request", {})
        if pr_info.get("merged_at"):
            state = "merged"
        else:
            state = it.get("state", "open")
        items.append(
            {
                "repo": repo,
                "number": it["number"],
                "title": it.get("title", ""),
                "state": state,
                "updated_at": it.get("updated_at", ""),
                "created_at": it.get("created_at", ""),
                "url": it.get("html_url", ""),
            }
        )
    return items


def fetch_recent_commits(limit: int = 5) -> list[dict]:
    events = gh_get(f"https://api.github.com/users/{USER}/events/public?per_page=40")
    results: list[dict] = []
    seen_keys: set[str] = set()

    for ev in events:
        etype = ev.get("type", "")
        repo = ev.get("repo", {}).get("name", "")
        created_at = ev.get("created_at", "")
        payload = ev.get("payload", {})

        if etype == "PushEvent":
            branch = payload.get("ref", "").replace("refs/heads/", "") or "main"
            commits = payload.get("commits") or []
            head_sha = payload.get("head", "")
            msg = ""
            if commits:
                msg = commits[-1].get("message", "").splitlines()[0]
            elif head_sha:
                key_sha = f"{repo}:{head_sha[:10]}"
                if key_sha in seen_keys:
                    continue
                try:
                    c_data = gh_get(f"https://api.github.com/repos/{repo}/commits/{head_sha}")
                    msg = c_data.get("commit", {}).get("message", "").splitlines()[0]
                except Exception:
                    msg = f"Pushed commits to {branch}"
            else:
                msg = f"Pushed updates to {branch}"

            dedup = f"push:{repo}:{branch}:{msg[:40]}"
            if dedup in seen_keys:
                continue
            seen_keys.add(dedup)
            results.append(
                {
                    "tag": "PUSH",
                    "color": "#3b82f6",
                    "repo": repo,
                    "sub": branch,
                    "msg": msg,
                    "date": fmt_date(created_at),
                }
            )
        elif etype == "CreateEvent" and payload.get("ref_type") in ("repository", "tag"):
            ref_type = payload.get("ref_type")
            ref_name = payload.get("ref") or "main"
            dedup = f"create:{repo}:{ref_type}:{ref_name}"
            if dedup in seen_keys:
                continue
            seen_keys.add(dedup)
            results.append(
                {
                    "tag": "TAG" if ref_type == "tag" else "INIT",
                    "color": "#f43f8e",
                    "repo": repo,
                    "sub": ref_name,
                    "msg": f"Created {ref_type} {ref_name}",
                    "date": fmt_date(created_at),
                }
            )
        elif etype == "ReleaseEvent":
            rel = payload.get("release", {})
            tag_name = rel.get("tag_name", "release")
            dedup = f"rel:{repo}:{tag_name}"
            if dedup in seen_keys:
                continue
            seen_keys.add(dedup)
            results.append(
                {
                    "tag": "REL",
                    "color": "#10b981",
                    "repo": repo,
                    "sub": tag_name,
                    "msg": rel.get("name") or f"Published release {tag_name}",
                    "date": fmt_date(created_at),
                }
            )

        if len(results) >= limit:
            break

    # Fallback to recently pushed non-fork/fork repos if public events < limit
    if len(results) < limit:
        repos = gh_get(f"https://api.github.com/users/{USER}/repos?sort=pushed&per_page=10")
        for r in repos:
            full = r.get("full_name", "")
            dedup = f"repo:{full}"
            if any(x["repo"] == full for x in results) or dedup in seen_keys:
                continue
            seen_keys.add(dedup)
            results.append(
                {
                    "tag": "REPO",
                    "color": "#8b5cf6",
                    "repo": full,
                    "sub": r.get("default_branch", "main"),
                    "msg": r.get("description") or "Updated repository",
                    "date": fmt_date(r.get("pushed_at", "")),
                }
            )
            if len(results) >= limit:
                break

    return results[:limit]


def update_pr_cards(prs: list[dict]) -> None:
    if not prs:
        return
    total = len(prs)
    state_counts = Counter(p["state"] for p in prs)
    merged_total = state_counts.get("merged", 0)
    open_total = state_counts.get("open", 0)
    closed_total = state_counts.get("closed", 0)

    repo_counts = Counter(p["repo"] for p in prs)
    top_repos = repo_counts.most_common(3)
    colors = ["#00f0ff", "#8b5cf6", "#f43f8e"]
    text_colors = ["#00f0ff", "#c4b5fd", "#f9a8d4"]

    # Update pr-overview.svg dynamically
    bar_total_w = 1136
    bar_rects = []
    legend_items = []
    bx = 32
    lx_positions = [40, 395, 775]
    for idx, (r_name, r_cnt) in enumerate(top_repos):
        seg_w = max(24, int(round(bar_total_w * (r_cnt / total))))
        if idx == len(top_repos) - 1:
            seg_w = max(20, (32 + bar_total_w) - bx)
        pct = (r_cnt / total) * 100
        col = colors[idx % len(colors)]
        tcol = text_colors[idx % len(text_colors)]
        rx_val = 7 if idx == 0 or idx == len(top_repos) - 1 else 4
        bar_rects.append(
            f'<rect x="{bx}" y="64" width="{max(8, seg_w - 3)}" height="14" rx="{rx_val}" fill="{col}"/>'
        )
        bx += seg_w
        lx = lx_positions[idx] if idx < len(lx_positions) else 40 + idx * 360
        pr_word = "PR" if r_cnt == 1 else "PRs"
        legend_items.append(
            f'<circle cx="{lx}" cy="102" r="4.5" fill="{col}"/>\n'
            f'  <text class="mono" x="{lx + 12}" y="106" font-size="12" fill="#e2e8f0">{esc(r_name)} '
            f'<tspan fill="{tcol}">({r_cnt} {pr_word} · {pct:.1f}%)</tspan></text>'
        )

    overview_svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 132" width="100%" role="img" aria-label="Pull Request Telemetry Overview">
  <defs>
    <linearGradient id="prBg" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#090d16"/>
      <stop offset="50%" stop-color="#0c1324"/>
      <stop offset="100%" stop-color="#090d16"/>
    </linearGradient>
  </defs>
  <style>
    .mono {{ font-family: 'JetBrains Mono', 'Fira Code', 'SF Mono', ui-monospace, Menlo, Consolas, monospace; }}
    .pulse {{ animation: prPulse 2.4s ease-in-out infinite; }}
    @keyframes prPulse {{ 0%,100% {{ opacity: 0.6; }} 50% {{ opacity: 1; }} }}
  </style>

  <rect x="2" y="2" width="1196" height="128" rx="14" fill="url(#prBg)" stroke="#1e293b" stroke-width="1.5"/>

  <circle class="pulse" cx="34" cy="34" r="4.5" fill="#10b981"/>
  <text class="mono" x="48" y="38" font-size="12" fill="#94a3b8" letter-spacing="1.2">UPSTREAM_PR_DISTRIBUTION // <tspan fill="#e2e8f0">{total} PUBLIC PULL REQUESTS</tspan></text>

  <g transform="translate(650, 18)">
    <rect x="0" y="0" width="124" height="28" rx="7" fill="#0f172a" stroke="#10b981" stroke-opacity="0.55"/>
    <text class="mono" x="62" y="18" text-anchor="middle" font-size="11.5" font-weight="700" fill="#10b981">{merged_total} MERGED</text>

    <rect x="134" y="0" width="110" height="28" rx="7" fill="#0f172a" stroke="#00f0ff" stroke-opacity="0.55"/>
    <text class="mono" x="189" y="18" text-anchor="middle" font-size="11.5" font-weight="700" fill="#00f0ff">{open_total} OPEN</text>

    <rect x="254" y="0" width="118" height="28" rx="7" fill="#0f172a" stroke="#64748b" stroke-opacity="0.55"/>
    <text class="mono" x="313" y="18" text-anchor="middle" font-size="11.5" font-weight="700" fill="#94a3b8">{closed_total} CLOSED</text>

    <rect x="382" y="0" width="136" height="28" rx="7" fill="#0f172a" stroke="#8b5cf6" stroke-opacity="0.55"/>
    <text class="mono" x="450" y="18" text-anchor="middle" font-size="11.5" font-weight="700" fill="#c4b5fd">{len(repo_counts)} UPSTREAM</text>
  </g>

  <rect x="32" y="64" width="1136" height="14" rx="7" fill="#050811" stroke="#1e293b"/>
  {''.join(bar_rects)}

  {chr(10).join('  ' + x for x in legend_items)}
</svg>
'''
    (ASSETS / "pr-overview.svg").write_text(overview_svg, encoding="utf-8")

    # Update header-oss.svg count dynamically
    header_oss = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 58" width="100%" role="img" aria-label="OPEN_SOURCE_IMPACT">
  <defs>
    <linearGradient id="hdrLine" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#10b981" stop-opacity="0.9"/>
      <stop offset="45%" stop-color="#8b5cf6" stop-opacity="0.4"/>
      <stop offset="100%" stop-color="#0f172a" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <style>
    .mono {{ font-family: 'JetBrains Mono', 'Fira Code', 'SF Mono', ui-monospace, Menlo, Consolas, monospace; }}
    .sans {{ font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; }}
    .ping {{ animation: pingAnim 2.2s ease-in-out infinite; }}
    @keyframes pingAnim {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.35; }} }}
  </style>
  <rect x="4" y="6" width="1192" height="46" rx="10" fill="#090d16" stroke="#1e293b" stroke-width="1.2"/>
  <rect x="4" y="6" width="6" height="46" rx="3" fill="#10b981"/>
  <rect x="24" y="17" width="40" height="24" rx="6" fill="#0f172a" stroke="#10b981" stroke-opacity="0.6"/>
  <text class="mono" x="44" y="33" text-anchor="middle" font-size="12.5" font-weight="700" fill="#10b981">04</text>
  <text class="sans" x="80" y="35" font-size="19" font-weight="800" fill="#f8fafc" letter-spacing="1.6">OPEN_SOURCE_IMPACT</text>
  <line x1="390" y1="29" x2="960" y2="29" stroke="url(#hdrLine)" stroke-width="1.2"/>
  <circle class="ping" cx="980" cy="29" r="3.5" fill="#10b981"/>
  <text class="mono" x="994" y="33" font-size="12" fill="#94a3b8" letter-spacing="1">PULL_REQUESTS // {total}</text>
</svg>
'''
    (ASSETS / "header-oss.svg").write_text(header_oss, encoding="utf-8")

    # Update the 3 repo cards with live merged/open/closed counts
    card_specs = [
        (
            "pr-plexo.svg",
            "anmolkapil/plexo",
            "TYPESCRIPT // ELECTRON",
            "i18n, custom Windows titlebar, system tray,",
            "live search/filter, trackers & disk warnings.",
            "#00f0ff",
        ),
        (
            "pr-pragent.svg",
            "The-PR-Agent/pr-agent",
            "PYTHON // AI REVIEWER",
            "Exposed head CI status/staleness & added",
            "deterministic risk checks for sensitive paths.",
            "#8b5cf6",
        ),
        (
            "pr-session.svg",
            "21CE085/GitHub-Session",
            "OPEN_SOURCE // GIT",
            "Merged pull request contribution to",
            "collaborative campus GitHub workshop repo.",
            "#f43f8e",
        ),
    ]
    for fname, repo, lang, s1, s2, accent in card_specs:
        r_prs = [p for p in prs if p["repo"] == repo]
        if not r_prs:
            continue
        t = len(r_prs)
        m = sum(1 for p in r_prs if p["state"] == "merged")
        o = sum(1 for p in r_prs if p["state"] == "open")
        c = sum(1 for p in r_prs if p["state"] == "closed")

        bar_w = 342
        m_w = int(bar_w * (m / t))
        o_w = int(bar_w * (o / t))
        c_w = bar_w - m_w - o_w

        bits = []
        if m:
            bits.append(f"{m} MERGED")
        if o:
            bits.append(f"{o} OPEN")
        if c:
            bits.append(f"{c} CLOSED")

        bars = []
        cx = 24
        if m_w > 0:
            bars.append(f'<rect x="{cx}" y="128" width="{max(6, m_w - 2)}" height="7" rx="3.5" fill="#10b981"/>')
            cx += m_w
        if o_w > 0:
            bars.append(f'<rect x="{cx}" y="128" width="{max(6, o_w - 2)}" height="7" rx="3.5" fill="#00f0ff"/>')
            cx += o_w
        if c_w > 0:
            bars.append(f'<rect x="{cx}" y="128" width="{max(6, c_w)}" height="7" rx="3.5" fill="#64748b"/>')

        pr_label = f"{t} PRs" if t != 1 else "1 PR"
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 390 198" width="100%" role="img" aria-label="{esc(repo)} Pull Requests">
  <style>
    .mono {{ font-family: 'JetBrains Mono', 'Fira Code', 'SF Mono', ui-monospace, Menlo, Consolas, monospace; }}
    .sans {{ font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; }}
  </style>
  <rect x="2" y="2" width="386" height="194" rx="14" fill="#090d16" stroke="#1e293b" stroke-width="1.5"/>
  <rect x="22" y="2" width="96" height="3.5" rx="1.5" fill="{accent}"/>

  <text class="mono" x="24" y="30" font-size="10.5" fill="#64748b" letter-spacing="1">{esc(lang)}</text>
  <rect x="288" y="16" width="78" height="24" rx="12" fill="#0f172a" stroke="{accent}" stroke-opacity="0.6"/>
  <text class="mono" x="327" y="32" text-anchor="middle" font-size="11.5" font-weight="700" fill="{accent}">{esc(pr_label)}</text>

  <text class="sans" x="24" y="58" font-size="17" font-weight="800" fill="#f8fafc">{esc(repo)}</text>

  <text class="sans" x="24" y="86" font-size="12.5" fill="#cbd5e1">{esc(s1)}</text>
  <text class="sans" x="24" y="106" font-size="12.5" fill="#94a3b8">{esc(s2)}</text>

  <rect x="24" y="128" width="342" height="7" rx="3.5" fill="#050811"/>
  {''.join(bars)}

  <text class="mono" x="24" y="154" font-size="10.5" fill="#94a3b8">{esc(" · ".join(bits))}</text>

  <line x1="24" y1="166" x2="366" y2="166" stroke="#1e293b" stroke-width="1"/>
  <text class="mono" x="24" y="184" font-size="10.5" fill="#64748b">PR_LOG // LIVE_SYNC</text>
  <text class="mono" x="366" y="184" text-anchor="end" font-size="10.5" font-weight="700" fill="{accent}">INSPECT PRs ▸</text>
</svg>
'''
        (ASSETS / fname).write_text(svg, encoding="utf-8")


def build_live_feed_svg(prs: list[dict], commits: list[dict]) -> str:
    latest_ts = ""
    if prs:
        latest_ts = fmt_date(prs[0].get("updated_at") or prs[0].get("created_at") or "")
    if not latest_ts and commits:
        latest_ts = commits[0].get("date", "LIVE")

    pr_rows = []
    for idx, pr in enumerate(prs[:5]):
        y = 78 + idx * 54
        st = pr["state"].upper()
        if st == "MERGED":
            st_col = "#10b981"
        elif st == "OPEN":
            st_col = "#00f0ff"
        else:
            st_col = "#64748b"

        repo_short = trunc(f"{pr['repo']} #{pr['number']}", 42)
        title_short = trunc(pr["title"], 58)
        d_str = fmt_date(pr["updated_at"] or pr["created_at"])

        pr_rows.append(
            f'<rect x="24" y="{y}" width="556" height="46" rx="9" fill="#0d1424" stroke="#1e293b"/>\n'
            f'  <rect x="34" y="{y + 12}" width="64" height="22" rx="6" fill="#050811" stroke="{st_col}" stroke-opacity="0.65"/>\n'
            f'  <text class="mono" x="66" y="{y + 27}" text-anchor="middle" font-size="10" font-weight="700" fill="{st_col}">{st}</text>\n'
            f'  <text class="mono" x="110" y="{y + 19}" font-size="11.5" font-weight="700" fill="#e2e8f0">{esc(repo_short)}</text>\n'
            f'  <text class="sans" x="110" y="{y + 37}" font-size="11.5" fill="#94a3b8">{esc(title_short)}</text>\n'
            f'  <text class="mono" x="566" y="{y + 19}" text-anchor="end" font-size="10.5" fill="#64748b">{esc(d_str)}</text>'
        )

    commit_rows = []
    for idx, cm in enumerate(commits[:5]):
        y = 78 + idx * 54
        tag = cm["tag"]
        col = cm["color"]
        repo_sub = trunc(f"{cm['repo']} · {cm['sub']}", 44)
        msg_short = trunc(cm["msg"], 58)

        commit_rows.append(
            f'<rect x="620" y="{y}" width="556" height="46" rx="9" fill="#0d1424" stroke="#1e293b"/>\n'
            f'  <rect x="630" y="{y + 12}" width="56" height="22" rx="6" fill="#050811" stroke="{col}" stroke-opacity="0.65"/>\n'
            f'  <text class="mono" x="658" y="{y + 27}" text-anchor="middle" font-size="10" font-weight="700" fill="{col}">{esc(tag)}</text>\n'
            f'  <text class="mono" x="698" y="{y + 19}" font-size="11.5" font-weight="700" fill="#e2e8f0">{esc(repo_sub)}</text>\n'
            f'  <text class="sans" x="698" y="{y + 37}" font-size="11.5" fill="#94a3b8">{esc(msg_short)}</text>\n'
            f'  <text class="mono" x="1162" y="{y + 19}" text-anchor="end" font-size="10.5" fill="#64748b">{esc(cm["date"])}</text>'
        )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 392" width="100%" role="img" aria-label="Live GitHub Activity and Recent PRs Feed">
  <defs>
    <linearGradient id="feedHdr" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#00f0ff"/>
      <stop offset="50%" stop-color="#8b5cf6"/>
      <stop offset="100%" stop-color="#10b981"/>
    </linearGradient>
  </defs>
  <style>
    .mono {{ font-family: 'JetBrains Mono', 'Fira Code', 'SF Mono', ui-monospace, Menlo, Consolas, monospace; }}
    .sans {{ font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; }}
    .live-dot {{ animation: livePulse 1.8s ease-in-out infinite; }}
    @keyframes livePulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.3; }} }}
  </style>

  <rect x="2" y="2" width="1196" height="388" rx="14" fill="#090d16" stroke="#1e293b" stroke-width="1.5"/>
  <rect x="2" y="2" width="1196" height="3" rx="1.5" fill="url(#feedHdr)" opacity="0.85"/>

  <!-- Top Bar -->
  <circle class="live-dot" cx="28" cy="28" r="4.5" fill="#10b981"/>
  <text class="mono" x="42" y="32" font-size="12" fill="#e2e8f0" letter-spacing="1.2">LIVE_ACTIVITY_STREAM</text>
  <text class="mono" x="1174" y="32" text-anchor="end" font-size="11" fill="#64748b">LATEST_EVENT: <tspan fill="#94a3b8">{esc(latest_ts)}</tspan></text>

  <!-- Column Headers -->
  <text class="mono" x="26" y="64" font-size="11.5" font-weight="700" fill="#00f0ff" letter-spacing="1">▸ LATEST_PULL_REQUESTS</text>
  <line x1="600" y1="52" x2="600" y2="346" stroke="#1e293b" stroke-width="1.2" stroke-dasharray="4 4"/>
  <text class="mono" x="622" y="64" font-size="11.5" font-weight="700" fill="#8b5cf6" letter-spacing="1">▸ RECENT_COMMITS_&amp;_PUSHES</text>

  <!-- Left Column: Recent PRs -->
  {chr(10).join('  ' + r for r in pr_rows)}

  <!-- Right Column: Recent Commits -->
  {chr(10).join('  ' + r for r in commit_rows)}

  <!-- Footer Status Bar -->
  <line x1="24" y1="358" x2="1176" y2="358" stroke="#1e293b" stroke-width="1"/>
  <text class="mono" x="26" y="376" font-size="10.5" fill="#64748b">FEED // api.github.com/users/{esc(USER)} · updated via GitHub Actions</text>
  <text class="mono" x="1174" y="376" text-anchor="end" font-size="10.5" fill="#10b981">[ TELEMETRY_ACTIVE ]</text>
</svg>
'''


def main() -> None:
    prs = fetch_prs()
    commits = fetch_recent_commits(limit=5)
    update_pr_cards(prs)
    (ASSETS / "live-feed.svg").write_text(build_live_feed_svg(prs, commits), encoding="utf-8")
    print(f"Updated PR cards ({len(prs)} PRs) and live-feed.svg ({len(commits)} commits/events).")


if __name__ == "__main__":
    main()
