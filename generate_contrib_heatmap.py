#!/usr/bin/env python3
"""
Generate a terminal-style GitHub contribution heatmap SVG.

Required environment variables:
  GITHUB_TOKEN      GitHub token available in Actions.
  GITHUB_USERNAME   GitHub username whose contributions should be rendered.

Optional:
  OUTPUT_PATH       Output SVG path. Defaults to contrib-heatmap.svg.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape


GRAPHQL_URL = "https://api.github.com/graphql"


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def fetch_contributions(username: str, token: str) -> dict:
    query = """
    query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                contributionCount
                contributionLevel
                date
                weekday
              }
            }
          }
        }
      }
    }
    """

    payload = json.dumps(
        {"query": query, "variables": {"login": username}}
    ).encode("utf-8")

    request = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "github-profile-contribution-generator",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub GraphQL request failed with HTTP {exc.code}: {body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach GitHub GraphQL API: {exc}") from exc

    if result.get("errors"):
        raise RuntimeError(
            "GitHub GraphQL returned errors: "
            + json.dumps(result["errors"], indent=2)
        )

    user = result.get("data", {}).get("user")
    if not user:
        raise RuntimeError(f"GitHub user not found: {username}")

    return user["contributionsCollection"]["contributionCalendar"]


def month_labels(weeks: list[dict]) -> list[tuple[int, str]]:
    labels: list[tuple[int, str]] = []
    previous_month = None

    for week_index, week in enumerate(weeks):
        days = week.get("contributionDays", [])
        if not days:
            continue

        first_date = datetime.strptime(days[0]["date"], "%Y-%m-%d")
        month = first_date.month

        if month != previous_month:
            labels.append((week_index, first_date.strftime("%b")))
            previous_month = month

    return labels


def render_svg(username: str, calendar: dict) -> str:
    weeks = calendar["weeks"]
    total = calendar["totalContributions"]

    width = 900
    height = 250
    left = 72
    top = 104
    cell = 11
    gap = 3
    step = cell + gap

    level_colors = {
        "NONE": "#21262d",
        "FIRST_QUARTILE": "#0e4429",
        "SECOND_QUARTILE": "#006d32",
        "THIRD_QUARTILE": "#26a641",
        "FOURTH_QUARTILE": "#39d353",
    }

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{escape(username)} GitHub contribution heatmap</title>',
        f'<desc id="desc">{total} contributions in the last year.</desc>',
        """
<style>
  .bg { fill: #0d1117; stroke: #30363d; stroke-width: 2; }
  .titlebar { fill: #161b22; }
  .divider { stroke: #30363d; stroke-width: 1; }
  text {
    font-family: Consolas, Monaco, "Liberation Mono", "Courier New", monospace;
  }
  .window-title { fill: #f0f6fc; font-size: 15px; font-weight: 700; }
  .prompt { fill: #39d353; font-size: 15px; font-weight: 700; }
  .month { fill: #8b949e; font-size: 11px; }
  .day { fill: #8b949e; font-size: 10px; }
  .footer { fill: #8b949e; font-size: 12px; }
  .cell {
    opacity: 0;
    animation: reveal 0.25s ease-out forwards;
  }
  .cursor {
    fill: #39d353;
    animation: blink 1s steps(1, end) infinite;
  }
  @keyframes reveal {
    from { opacity: 0; transform: translateY(3px); }
    to { opacity: 1; transform: translateY(0); }
  }
  @keyframes blink {
    0%, 45% { opacity: 1; }
    46%, 100% { opacity: 0; }
  }
  @media (prefers-reduced-motion: reduce) {
    .cell { opacity: 1; animation: none; }
    .cursor { animation: none; }
  }
</style>
""",
        f'<rect class="bg" x="1" y="1" width="{width - 2}" height="{height - 2}" rx="14"/>',
        f'<path class="titlebar" d="M15 1 H{width - 15} Q{width - 1} 1 {width - 1} 15 '
        f'V52 H1 V15 Q1 1 15 1 Z"/>',
        '<circle cx="24" cy="26" r="6" fill="#ff5f56"/>',
        '<circle cx="46" cy="26" r="6" fill="#ffbd2e"/>',
        '<circle cx="68" cy="26" r="6" fill="#27c93f"/>',
        f'<text class="window-title" x="{width / 2}" y="31" text-anchor="middle">'
        f'{escape(username)}@github: ~/activity</text>',
        f'<line class="divider" x1="1" y1="52" x2="{width - 1}" y2="52"/>',
        f'<text class="prompt" x="24" y="82">{escape(username)}@github:~$ git log --graph</text>',
    ]

    for week_index, label in month_labels(weeks):
        x = left + week_index * step
        parts.append(f'<text class="month" x="{x}" y="98">{label}</text>')

    day_labels = [(1, "Mon"), (3, "Wed"), (5, "Fri")]
    for weekday, label in day_labels:
        y = top + weekday * step + 9
        parts.append(f'<text class="day" x="24" y="{y}">{label}</text>')

    animation_index = 0
    for week_index, week in enumerate(weeks):
        for day in week.get("contributionDays", []):
            weekday = int(day["weekday"])
            x = left + week_index * step
            y = top + weekday * step
            color = level_colors.get(day["contributionLevel"], level_colors["NONE"])
            delay = min(animation_index * 0.004, 1.8)
            count = int(day["contributionCount"])
            date = day["date"]
            parts.append(
                f'<rect class="cell" x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" '
                f'fill="{color}" style="animation-delay:{delay:.3f}s">'
                f'<title>{count} contribution{"s" if count != 1 else ""} on {date}</title>'
                f'</rect>'
            )
            animation_index += 1

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts.extend(
        [
            f'<text class="footer" x="24" y="228">{total} contributions in the last year</text>',
            f'<text class="footer" x="{width - 24}" y="228" text-anchor="end">Updated {generated}</text>',
            '</svg>',
        ]
    )

    return "\n".join(parts)


def main() -> int:
    try:
        username = require_env("GITHUB_USERNAME")
        token = require_env("GITHUB_TOKEN")
        output_path = Path(os.getenv("OUTPUT_PATH", "contrib-heatmap.svg"))

        calendar = fetch_contributions(username, token)
        svg = render_svg(username, calendar)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(svg, encoding="utf-8")

        print(
            f"Generated {output_path} with "
            f"{calendar['totalContributions']} contributions."
        )
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
