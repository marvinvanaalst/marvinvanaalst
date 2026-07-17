#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Fetch lifetime GitHub contribution stats and regenerate the stat card SVGs.

Data sources (public contributions only):
  - commits: GraphQL contributionsCollection.totalCommitContributions, summed
    year-by-year since account creation. This is what GitHub's own profile
    contribution graph uses, and unlike the REST commit-search endpoint it
    isn't skewed by commit objects shared across forked repositories.
  - PRs opened / PRs reviewed: REST search API total_count, which counts
    distinct PRs (not distinct review submissions).
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

GITHUB_LOGIN = "marvinvanaalst"
ACCOUNT_CREATED_YEAR = 2017
API_ROOT = "https://api.github.com"

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "data" / "stats_cache.json"
SVG_LIGHT_PATH = ROOT / "assets" / "stats-light.svg"
SVG_DARK_PATH = ROOT / "assets" / "stats-dark.svg"

COMMITS_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
    }
  }
}
"""


@dataclasses.dataclass
class Stats:
    commits: int
    prs: int
    prs_reviewed: int
    last_updated: str


def _token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def _request(url: str, *, method: str = "GET", body: dict | None = None) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"{GITHUB_LOGIN}-stats-script",
    }
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def _graphql(query: str, variables: dict) -> dict:
    result = _request(
        f"{API_ROOT}/graphql",
        method="POST",
        body={"query": query, "variables": variables},
    )
    if "errors" in result:
        raise RuntimeError(str(result["errors"]))
    return result["data"]


def fetch_total_commits() -> int:
    current_year = datetime.now(UTC).year
    total = 0
    for year in range(ACCOUNT_CREATED_YEAR, current_year + 1):
        data = _graphql(
            COMMITS_QUERY,
            {
                "login": GITHUB_LOGIN,
                "from": f"{year}-01-01T00:00:00Z",
                "to": f"{year + 1}-01-01T00:00:00Z",
            },
        )
        total += data["user"]["contributionsCollection"]["totalCommitContributions"]
    return total


def _fetch_search_count(query: str) -> int:
    url = f"{API_ROOT}/search/issues?q={quote(query)}"
    return _request(url)["total_count"]


def fetch_total_prs() -> int:
    return _fetch_search_count(f"author:{GITHUB_LOGIN} type:pr")


def fetch_total_prs_reviewed() -> int:
    return _fetch_search_count(f"reviewed-by:{GITHUB_LOGIN} type:pr")


def load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text())
    return {}


def fetch_with_fallback(name: str, fetcher: Callable[[], int], cache: dict) -> int:
    try:
        return fetcher()
    except (urllib.error.URLError, RuntimeError, KeyError) as exc:
        if name in cache:
            print(
                f"warning: failed to fetch {name} ({exc}); using cached value {cache[name]}",
                file=sys.stderr,
            )
            return cache[name]
        raise


def gather_stats() -> Stats:
    cache = load_cache()
    commits = fetch_with_fallback("commits", fetch_total_commits, cache)
    prs = fetch_with_fallback("prs", fetch_total_prs, cache)
    prs_reviewed = fetch_with_fallback("prs_reviewed", fetch_total_prs_reviewed, cache)
    return Stats(
        commits=commits,
        prs=prs,
        prs_reviewed=prs_reviewed,
        last_updated=datetime.now(UTC).strftime("%Y-%m-%d"),
    )


def save_cache(stats: Stats) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(dataclasses.asdict(stats), indent=2) + "\n")


THEMES = {
    "light": {
        "bg": "#ffffff",
        "border": "#d0d7de",
        "text": "#24292f",
        "muted": "#57606a",
        "accent": "#0969da",
        "accent2": "#8250df",
        "accent3": "#1a7f37",
    },
    "dark": {
        "bg": "#0d1117",
        "border": "#30363d",
        "text": "#c9d1d9",
        "muted": "#8b949e",
        "accent": "#58a6ff",
        "accent2": "#bc8cff",
        "accent3": "#3fb950",
    },
}

COLUMNS = [
    {"key": "commits", "label": "COMMITS"},
    {"key": "prs", "label": "PULL REQUESTS"},
    {"key": "prs_reviewed", "label": "PRs REVIEWED"},
]
COLUMN_CENTERS = [133, 350, 567]


def _icon(kind: str, cx: float, color: str) -> str:
    g = f'<g transform="translate({cx - 12}, 58)">'
    if kind == "commits":
        g += (
            f'<line x1="0" y1="12" x2="7" y2="12" stroke="{color}" stroke-width="2" stroke-linecap="round"/>'
            f'<circle cx="12" cy="12" r="5" fill="none" stroke="{color}" stroke-width="2"/>'
            f'<line x1="17" y1="12" x2="24" y2="12" stroke="{color}" stroke-width="2" stroke-linecap="round"/>'
        )
    elif kind == "prs":
        g += (
            f'<circle cx="6" cy="4" r="3" fill="none" stroke="{color}" stroke-width="2"/>'
            f'<circle cx="6" cy="20" r="3" fill="none" stroke="{color}" stroke-width="2"/>'
            f'<line x1="6" y1="7" x2="6" y2="17" stroke="{color}" stroke-width="2"/>'
            f'<circle cx="18" cy="15" r="3" fill="none" stroke="{color}" stroke-width="2"/>'
            f'<path d="M18 4 v6 a3 3 0 0 1 -3 3 h-3" fill="none" stroke="{color}" stroke-width="2"/>'
        )
    elif kind == "prs_reviewed":
        g += (
            f'<path d="M2 12 C6 5, 18 5, 22 12 C18 19, 6 19, 2 12 Z" fill="none" '
            f'stroke="{color}" stroke-width="2"/>'
            f'<circle cx="12" cy="12" r="3.2" fill="{color}"/>'
        )
    g += "</g>"
    return g


def render_svg(stats: Stats, theme_name: str) -> str:
    t = THEMES[theme_name]
    icon_colors = {
        "commits": t["accent"],
        "prs": t["accent2"],
        "prs_reviewed": t["accent3"],
    }
    values = {
        "commits": stats.commits,
        "prs": stats.prs,
        "prs_reviewed": stats.prs_reviewed,
    }

    columns_svg = ""
    for col, cx in zip(COLUMNS, COLUMN_CENTERS, strict=True):
        columns_svg += _icon(col["key"], cx, icon_colors[col["key"]])
        columns_svg += (
            f'<text x="{cx}" y="124" text-anchor="middle" font-family="ui-monospace, monospace" '
            f'font-size="28" font-weight="700" fill="{t["text"]}">{values[col["key"]]:,}</text>'
        )
        columns_svg += (
            f'<text x="{cx}" y="138" text-anchor="middle" font-family="ui-monospace, monospace" '
            f'font-size="10" letter-spacing="1.5" fill="{t["muted"]}">{col["label"]}</text>'
        )

    dividers = "".join(
        f'<line x1="{x}" y1="60" x2="{x}" y2="134" stroke="{t["border"]}" stroke-width="1"/>'
        for x in (241, 459)
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="700" height="150" viewBox="0 0 700 150">
  <rect x="0.5" y="0.5" width="699" height="149" rx="12" fill="{t["bg"]}" stroke="{t["border"]}"/>
  <rect x="0.5" y="0.5" width="699" height="4" rx="2" fill="url(#accent-gradient-{theme_name})"/>
  <defs>
    <linearGradient id="accent-gradient-{theme_name}" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="{t["accent"]}"/>
      <stop offset="50%" stop-color="{t["accent2"]}"/>
      <stop offset="100%" stop-color="{t["accent3"]}"/>
    </linearGradient>
  </defs>
  <text x="24" y="32" font-family="ui-monospace, monospace" font-size="13" font-weight="600" \
letter-spacing="2" fill="{t["muted"]}">LIFETIME CONTRIBUTIONS</text>
  <text x="676" y="32" text-anchor="end" font-family="ui-monospace, monospace" font-size="11" \
fill="{t["muted"]}">as of {stats.last_updated}</text>
  <line x1="24" y1="46" x2="676" y2="46" stroke="{t["border"]}" stroke-width="1"/>
  {dividers}
  {columns_svg}
</svg>
"""


def render_svgs(stats: Stats) -> None:
    SVG_LIGHT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SVG_LIGHT_PATH.write_text(render_svg(stats, "light"))
    SVG_DARK_PATH.write_text(render_svg(stats, "dark"))


def main() -> None:
    stats = gather_stats()
    save_cache(stats)
    render_svgs(stats)
    print(
        f"commits={stats.commits} prs={stats.prs} prs_reviewed={stats.prs_reviewed} as_of={stats.last_updated}"
    )


if __name__ == "__main__":
    main()
