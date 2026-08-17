#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any


USERNAME = os.environ.get("GITHUB_USERNAME", "vincentperezzz")
OUT_PATH = Path(__file__).resolve().parents[1] / "assets" / "github-stats.svg"
API = "https://api.github.com"
EXCLUDE_LANGS = {
    "CMake",
    "Objective-C",
    "PowerShell",
    "Batchfile",
    "Dockerfile",
    "RouterOS Script",
    "PLpgSQL",
    "Ruby",
    "Makefile",
    "C",
    "Swift",
    "Kotlin",
    "Lua",
    "Shell",
    "Tcl",
    "Mustache",
    "Hack",
    "HTML",
    "CSS",
}
BAR_COLORS = ["#00f5ff", "#ff3dd1", "#7c4dff", "#ffe87a", "#44ff88", "#ffcc00"]


def github_token() -> str:
    for key in ("GH_STATS_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(key)
        if value:
            return value
    try:
        return subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit("No GitHub token found") from exc


def api_request(url: str, token: str, payload: dict[str, Any] | None = None) -> Any:
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{USERNAME}-stats-card",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"GitHub API {exc.code} for {url}: {body[:400]}") from exc


def graphql(token: str, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables
    result = api_request(f"{API}/graphql", token, payload)
    if result.get("errors"):
        raise RuntimeError(result["errors"])
    return result["data"]


def rest(token: str, path: str) -> Any:
    return api_request(f"{API}{path}", token)


def fmt_int(value: int) -> str:
    return f"{value:,}"


def account_years(created_at: str, today: date) -> list[int]:
    start = datetime.fromisoformat(created_at.replace("Z", "+00:00")).year
    return list(range(start, today.year + 1))


def current_streak(day_counts: dict[str, int], today: date) -> int:
    cursor = today
    if day_counts.get(cursor.isoformat(), 0) == 0:
        cursor -= timedelta(days=1)
    streak = 0
    while day_counts.get(cursor.isoformat(), 0) > 0:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def best_streak(day_counts: dict[str, int]) -> int:
    best = run = 0
    for key in sorted(day_counts):
        if day_counts[key] > 0:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def heatmap_weeks(day_counts: dict[str, int], today: date) -> list[list[tuple[str, int]]]:
    days_since_sunday = (today.weekday() + 1) % 7
    this_sunday = today - timedelta(days=days_since_sunday)
    start = this_sunday - timedelta(weeks=52)
    weeks: list[list[tuple[str, int]]] = []
    cursor = start
    for _ in range(53):
        week = []
        for _day in range(7):
            key = cursor.isoformat()
            week.append((key, day_counts.get(key, 0)))
            cursor += timedelta(days=1)
        weeks.append(week)
    return weeks


def heatmap_fill(count: int, max_count: int) -> str:
    if count <= 0:
        return "#1a0036"
    if max_count <= 1:
        return "#00f5ff"
    ratio = count / max_count
    if ratio > 0.8:
        return "#00f5ff"
    if ratio > 0.55:
        return "#ff3dd1"
    if ratio > 0.3:
        return "#7c4dff"
    if ratio > 0.12:
        return "#4a1d9c"
    return "#2a1060"


def month_labels(weeks: list[list[tuple[str, int]]]) -> list[tuple[int, str]]:
    labels: list[tuple[int, str]] = []
    last = ""
    for index, week in enumerate(weeks):
        month = datetime.fromisoformat(week[0][0]).strftime("%b")
        if month != last:
            labels.append((index, month))
            last = month
    return labels


def fetch_stats(token: str, today: date) -> dict[str, Any]:
    user = rest(token, f"/users/{USERNAME}")
    years = account_years(user["created_at"], today)
    query = """
    query ($login: String!, $from: DateTime, $to: DateTime) {
      user(login: $login) {
        followers { totalCount }
        following { totalCount }
        pullRequests { totalCount }
        issues { totalCount }
        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          totalPullRequestContributions
          totalIssueContributions
          restrictedContributionsCount
          contributionCalendar {
            totalContributions
            weeks { contributionDays { contributionCount date } }
          }
        }
      }
    }
    """
    commits = 0
    contrib_prs = 0
    contrib_issues = 0
    restricted = 0
    calendar_total = 0
    day_counts: dict[str, int] = defaultdict(int)
    meta: dict[str, Any] = {}
    for year in years:
        data = graphql(
            token,
            query,
            {
                "login": USERNAME,
                "from": f"{year}-01-01T00:00:00Z",
                "to": f"{year}-12-31T23:59:59Z",
            },
        )["user"]
        block = data["contributionsCollection"]
        commits += block["totalCommitContributions"]
        contrib_prs += block["totalPullRequestContributions"]
        contrib_issues += block["totalIssueContributions"]
        restricted += block["restrictedContributionsCount"]
        calendar_total += block["contributionCalendar"]["totalContributions"]
        for week in block["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                day_counts[day["date"]] = day["contributionCount"]
        meta = data

    repos = rest(token, f"/users/{USERNAME}/repos?per_page=100&type=owner")
    owned = [repo for repo in repos if not repo.get("fork")]
    lang_bytes: dict[str, int] = defaultdict(int)
    stars = 0
    for repo in owned:
        stars += int(repo.get("stargazers_count") or 0)
        langs = rest(token, f"/repos/{USERNAME}/{repo['name']}/languages")
        for name, size in langs.items():
            if name in EXCLUDE_LANGS:
                continue
            lang_bytes[name] += int(size)

    ranked = sorted(lang_bytes.items(), key=lambda item: item[1], reverse=True)[:6]
    languages = [
        {
            "name": name,
            "bytes": size,
            "color": BAR_COLORS[index % len(BAR_COLORS)],
        }
        for index, (name, size) in enumerate(ranked)
    ]

    this_year = sum(
        count for day, count in day_counts.items() if day.startswith(str(today.year))
    )
    active_days = sum(1 for count in day_counts.values() if count > 0)

    return {
        "name": user.get("name") or USERNAME,
        "login": USERNAME,
        "followers": meta.get("followers", {}).get("totalCount", user.get("followers", 0)),
        "following": meta.get("following", {}).get("totalCount", user.get("following", 0)),
        "pull_requests": meta.get("pullRequests", {}).get("totalCount", contrib_prs),
        "issues": meta.get("issues", {}).get("totalCount", contrib_issues),
        "repos": int(user.get("public_repos") or len(owned)),
        "owned": len(owned),
        "stars": stars,
        "commits": commits,
        "contributions": calendar_total,
        "restricted": restricted,
        "this_year": this_year,
        "active_days": active_days,
        "current_streak": current_streak(day_counts, today),
        "best_streak": best_streak(day_counts),
        "since": datetime.fromisoformat(user["created_at"].replace("Z", "+00:00")).year,
        "languages": languages,
        "weeks": heatmap_weeks(day_counts, today),
        "updated": today.isoformat(),
    }


def render_svg(stats: dict[str, Any]) -> str:
    languages = stats["languages"]
    max_bytes = max((item["bytes"] for item in languages), default=1) or 1
    weeks = stats["weeks"]
    max_day = max((count for week in weeks for _, count in week), default=1) or 1
    labels = month_labels(weeks)
    lang_rows = []
    for index, item in enumerate(languages):
        y = 254 + index * 22
        width = max(8, round(item["bytes"] / max_bytes * 340))
        lang_rows.append(
            f'<text x="48" y="{y}" font-family="\'Courier New\',Courier,monospace" font-size="12" font-weight="700" fill="#c8b8ff">{escape(item["name"].upper())}</text>'
            f'<rect x="168" y="{y - 11}" width="340" height="10" rx="2" fill="#1a0036"/>'
            f'<rect x="168" y="{y - 11}" width="{width}" height="10" rx="2" fill="{item["color"]}" filter="url(#glow)"/>'
        )
    cells = []
    for week_index, week in enumerate(weeks):
        x = 566 + week_index * 12
        for day_index, (day, count) in enumerate(week):
            y = 256 + day_index * 12
            fill = heatmap_fill(count, max_day)
            cells.append(
                f'<rect x="{x}" y="{y}" width="10" height="10" rx="2" fill="{fill}"><title>{day}: {count}</title></rect>'
            )
    month_text = []
    for index, name in labels:
        month_text.append(
            f'<text x="{566 + index * 12}" y="244" font-family="\'Courier New\',Courier,monospace" font-size="10" fill="#8a7ab8">{name}</text>'
        )
    private_note = "PRIVATE SIGNAL INCLUDED" if stats["restricted"] else "PUBLIC SIGNAL"
    tiles = [
        ("CONTRIBUTIONS", fmt_int(stats["contributions"]), f"{fmt_int(stats['this_year'])} THIS YEAR"),
        ("COMMITS", fmt_int(stats["commits"]), f"{fmt_int(stats['active_days'])} ACTIVE DAYS"),
        ("PULL REQUESTS", fmt_int(stats["pull_requests"]), f"{fmt_int(stats['issues'])} ISSUES"),
        ("REPOS", fmt_int(stats["repos"]), f"{fmt_int(stats['stars'])} STAR{'S' if stats['stars'] != 1 else ''}"),
        ("STREAK", f"{stats['current_streak']}D", f"BEST {stats['best_streak']}D"),
    ]
    tile_svg = []
    for index, (label, value, sub) in enumerate(tiles):
        x = 24 + index * 247
        tile_svg.append(
            f"""
  <g>
    <rect x="{x}" y="78" width="235" height="108" rx="6" fill="#110025" stroke="#7c4dff" stroke-opacity=".45"/>
    <rect x="{x}" y="78" width="235" height="3" fill="#00f5ff" opacity=".85"/>
    <text x="{x + 18}" y="108" font-family="'Courier New',Courier,monospace" font-size="12" font-weight="700" fill="#ff3dd1">{label}</text>
    <text x="{x + 18}" y="148" font-family="'Courier New',Courier,monospace" font-size="32" font-weight="900" fill="#00f5ff" filter="url(#glow)">{value}</text>
    <text x="{x + 18}" y="170" font-family="'Courier New',Courier,monospace" font-size="11" fill="#8a7ab8">{sub}</text>
  </g>"""
        )
    return f"""<svg width="1280" height="430" viewBox="0 0 1280 430" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="GitHub stats for {escape(stats['login'])}">
  <defs>
    <linearGradient id="skyBg" x1="0" y1="0" x2="0" y2="430" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#06001a"/>
      <stop offset="55%" stop-color="#140030"/>
      <stop offset="100%" stop-color="#280055"/>
    </linearGradient>
    <linearGradient id="neonAccent" x1="0" y1="0" x2="1280" y2="0" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#00f5ff" stop-opacity="0"/>
      <stop offset="20%" stop-color="#00f5ff" stop-opacity="0.85"/>
      <stop offset="50%" stop-color="#ff3dd1" stop-opacity="0.9"/>
      <stop offset="80%" stop-color="#7c4dff" stop-opacity="0.85"/>
      <stop offset="100%" stop-color="#7c4dff" stop-opacity="0"/>
    </linearGradient>
    <pattern id="gridPat" width="40" height="40" patternUnits="userSpaceOnUse">
      <path d="M40 0L0 0L0 40" stroke="#6633cc" stroke-opacity="0.09" stroke-width="0.5" fill="none"/>
    </pattern>
    <filter id="glow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="3.2" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
    <clipPath id="mainClip"><rect width="1280" height="430" rx="0"/></clipPath>
  </defs>

  <rect width="1280" height="430" fill="url(#skyBg)"/>
  <rect width="1280" height="430" fill="url(#gridPat)"/>

  <text x="28" y="42" font-family="'Courier New',Courier,monospace" font-size="28" font-weight="900" fill="#7c4dff" filter="url(#glow)">[</text>
  <text x="52" y="42" font-family="'Courier New',Courier,monospace" font-size="22" font-weight="900" fill="#00f5ff" filter="url(#glow)">GITHUB // STATS</text>
  <text x="292" y="42" font-family="'Courier New',Courier,monospace" font-size="28" font-weight="900" fill="#7c4dff" filter="url(#glow)">]</text>
  <text x="640" y="40" font-family="'Courier New',Courier,monospace" font-size="14" font-weight="700" fill="#ff3dd1" text-anchor="middle" filter="url(#glow)">&#9670;  {escape(stats['login'].upper())}  &#9670;</text>
  <circle cx="1218" cy="34" r="6" fill="#00f5ff" filter="url(#glow)">
    <animate attributeName="opacity" values="1;0.2;1" dur="1.8s" repeatCount="indefinite"/>
  </circle>
  <text x="1206" y="40" font-family="'Courier New',Courier,monospace" font-size="12" font-weight="700" fill="#8a7ab8" text-anchor="end">LIVE</text>

  <line x1="0" y1="58" x2="1280" y2="58" stroke="url(#neonAccent)" stroke-width="1.5" opacity=".7"/>
  <g fill="#7c4dff" opacity=".7">
    <rect x="330" y="64" width="6" height="6"/>
    <rect x="336" y="58" width="6" height="6"/>
    <rect x="944" y="64" width="6" height="6"/>
    <rect x="938" y="58" width="6" height="6"/>
  </g>
  <g fill="#00f5ff" opacity=".5">
    <rect x="342" y="58" width="4" height="4"/>
    <rect x="934" y="58" width="4" height="4"/>
  </g>

  {''.join(tile_svg)}

  <rect x="24" y="202" width="512" height="186" rx="6" fill="#110025" stroke="#7c4dff" stroke-opacity=".45"/>
  <rect x="24" y="202" width="512" height="3" fill="#ff3dd1" opacity=".8"/>
  <text x="42" y="226" font-family="'Courier New',Courier,monospace" font-size="13" font-weight="700" fill="#00f5ff">TOP LANGUAGES</text>
  {''.join(lang_rows)}

  <rect x="548" y="202" width="708" height="186" rx="6" fill="#110025" stroke="#7c4dff" stroke-opacity=".45"/>
  <rect x="548" y="202" width="708" height="3" fill="#7c4dff" opacity=".9"/>
  <text x="566" y="226" font-family="'Courier New',Courier,monospace" font-size="13" font-weight="700" fill="#00f5ff">SIGNAL HEAT</text>
  <text x="1236" y="226" font-family="'Courier New',Courier,monospace" font-size="11" fill="#8a7ab8" text-anchor="end">LAST 12 MONTHS</text>
  {''.join(month_text)}
  {''.join(cells)}
  <g font-family="'Courier New',Courier,monospace" font-size="10" fill="#8a7ab8">
    <text x="1088" y="378">LESS</text>
    <rect x="1124" y="368" width="10" height="10" rx="2" fill="#1a0036"/>
    <rect x="1138" y="368" width="10" height="10" rx="2" fill="#2a1060"/>
    <rect x="1152" y="368" width="10" height="10" rx="2" fill="#7c4dff"/>
    <rect x="1166" y="368" width="10" height="10" rx="2" fill="#ff3dd1"/>
    <rect x="1180" y="368" width="10" height="10" rx="2" fill="#00f5ff"/>
    <text x="1196" y="378">MORE</text>
  </g>

  <line x1="0" y1="404" x2="1280" y2="404" stroke="#00f5ff" stroke-width="1" stroke-opacity=".28"/>
  <line x1="0" y1="407" x2="1280" y2="407" stroke="#ff3dd1" stroke-width=".75" stroke-opacity=".18"/>
  <rect x="0" y="410" width="1280" height="20" fill="#1c003e"/>
  <text x="28" y="424" font-family="'Courier New',Courier,monospace" font-size="11" fill="#8a7ab8">FOLLOWERS {fmt_int(stats['followers'])}   FOLLOWING {fmt_int(stats['following'])}   SINCE {stats['since']}   {private_note}   UPDATED {stats['updated']}</text>

  <rect x="0" y="0" width="1280" height="2" fill="#ffffff" opacity=".07" clip-path="url(#mainClip)">
    <animateTransform attributeName="transform" type="translate" values="0,-2;0,432" dur="8s" repeatCount="indefinite" calcMode="linear"/>
  </rect>
</svg>
"""


def main() -> int:
    token = github_token()
    today = datetime.now(timezone.utc).date()
    stats = fetch_stats(token, today)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(render_svg(stats), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")
    print(json.dumps({k: stats[k] for k in ("contributions", "commits", "pull_requests", "repos", "current_streak", "best_streak")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
