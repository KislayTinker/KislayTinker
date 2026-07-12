#!/usr/bin/env python3
"""
generate_readme_stats.py

Fetches GitHub profile stats (repos, stars, followers, total commits,
top languages) and renders them into an animated SVG card for a
GitHub profile README.

Requires an environment variable ACCESS_TOKEN containing a GitHub
Personal Access Token with `read:user` and `repo` scopes (repo scope
is needed to see private-repo contributions/commit counts; use only
`read:user` + `public_repo` if you'd rather keep private repos out
of the count).

Usage:
    ACCESS_TOKEN=xxx GITHUB_USERNAME=KislayTinker python generate_readme_stats.py
"""

import os
import sys
import datetime
import requests
from collections import defaultdict

USERNAME = os.environ.get("GITHUB_USERNAME", "KislayTinker")
TOKEN = os.environ.get("ACCESS_TOKEN")

if not TOKEN:
    print("ERROR: ACCESS_TOKEN environment variable not set.", file=sys.stderr)
    sys.exit(1)

API_URL = "https://api.github.com/graphql"
HEADERS = {"Authorization": f"bearer {TOKEN}"}

REPOS_STARS_LANGS_QUERY = """
query ($login: String!, $cursor: String) {
  user(login: $login) {
    repositories(first: 100, after: $cursor, ownerAffiliations: OWNER, isFork: false) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        stargazers { totalCount }
        languages(first: 5, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node { name color }
          }
        }
      }
    }
    followers { totalCount }
  }
}
"""

COMMITS_QUERY = """
query ($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar { totalContributions }
      totalCommitContributions
      restrictedContributionsCount
    }
  }
}
"""


def gql(query, variables):
    resp = requests.post(API_URL, json={"query": query, "variables": variables}, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


def fetch_repo_stats(login):
    stars = 0
    repo_count = 0
    lang_sizes = defaultdict(int)
    lang_colors = {}
    cursor = None
    while True:
        data = gql(REPOS_STARS_LANGS_QUERY, {"login": login, "cursor": cursor})
        repos = data["user"]["repositories"]
        repo_count = repos["totalCount"]
        for node in repos["nodes"]:
            stars += node["stargazers"]["totalCount"]
            for edge in node["languages"]["edges"]:
                name = edge["node"]["name"]
                lang_sizes[name] += edge["size"]
                lang_colors[name] = edge["node"]["color"] or "#858585"
        if not repos["pageInfo"]["hasNextPage"]:
            break
        cursor = repos["pageInfo"]["endCursor"]
    followers = data["user"]["followers"]["totalCount"]
    return repo_count, stars, followers, lang_sizes, lang_colors


def fetch_total_commits(login, account_created_at):
    """GraphQL only allows a max ~1 year window per call, so page year by year."""
    start = datetime.datetime.fromisoformat(account_created_at.replace("Z", "+00:00"))
    now = datetime.datetime.now(datetime.timezone.utc)
    total = 0
    cursor = start
    while cursor < now:
        window_end = min(cursor + datetime.timedelta(days=365), now)
        data = gql(COMMITS_QUERY, {
            "login": login,
            "from": cursor.isoformat(),
            "to": window_end.isoformat(),
        })
        cc = data["user"]["contributionsCollection"]
        total += cc["totalCommitContributions"] + cc["restrictedContributionsCount"]
        cursor = window_end
    return total


def fetch_account_created_at(login):
    resp = requests.get(f"https://api.github.com/users/{login}", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()["created_at"]


def top_languages(lang_sizes, top_n=5):
    total = sum(lang_sizes.values()) or 1
    ranked = sorted(lang_sizes.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    return [(name, size / total * 100) for name, size in ranked]


def render_svg(username, repo_count, stars, followers, commits, langs, lang_colors):
    row_height = 26
    lang_rows = ""
    y = 205
    for name, pct in langs:
        color = lang_colors.get(name, "#858585")
        bar_width = max(2, pct * 2.4)  # scale to ~240px max
        lang_rows += f"""
    <g transform="translate(30, {y})">
      <text class="lang-name" x="0" y="0">{name}</text>
      <text class="lang-pct" x="240" y="0" text-anchor="end">{pct:.1f}%</text>
      <rect x="0" y="8" width="240" height="6" rx="3" fill="#2a2f3a"/>
      <rect x="0" y="8" width="{bar_width:.1f}" height="6" rx="3" fill="{color}">
        <animate attributeName="width" from="0" to="{bar_width:.1f}" dur="1.2s" fill="freeze"/>
      </rect>
    </g>"""
        y += row_height

    svg = f"""<svg width="480" height="{y + 20}" viewBox="0 0 480 {y + 20}" xmlns="http://www.w3.org/2000/svg">
  <style>
    .bg {{ fill: #0d1117; }}
    .border {{ fill: none; stroke: #30363d; stroke-width: 1; }}
    .title {{ font: 600 18px 'Segoe UI', sans-serif; fill: #58a6ff; }}
    .stat-label {{ font: 400 13px 'Segoe UI', sans-serif; fill: #8b949e; }}
    .stat-value {{ font: 700 20px 'Segoe UI', sans-serif; fill: #e6edf3; }}
    .lang-name {{ font: 400 12px 'Segoe UI', sans-serif; fill: #c9d1d9; }}
    .lang-pct {{ font: 400 12px 'Segoe UI', sans-serif; fill: #8b949e; }}
    .fade-in {{ animation: fadeIn 0.8s ease-in-out forwards; opacity: 0; }}
    @keyframes fadeIn {{ to {{ opacity: 1; }} }}
  </style>

  <rect class="bg" width="480" height="{y + 20}" rx="10"/>
  <rect class="border" x="0.5" y="0.5" width="479" height="{y + 19}" rx="10"/>

  <text class="title fade-in" x="30" y="40" style="animation-delay:0.1s">{username}'s GitHub Stats</text>

  <g class="fade-in" style="animation-delay:0.3s">
    <text class="stat-label" x="30" y="75">Total Commits</text>
    <text class="stat-value" x="30" y="98">{commits:,}</text>

    <text class="stat-label" x="180" y="75">Stars Earned</text>
    <text class="stat-value" x="180" y="98">{stars:,}</text>

    <text class="stat-label" x="330" y="75">Repositories</text>
    <text class="stat-value" x="330" y="98">{repo_count:,}</text>

    <text class="stat-label" x="30" y="135">Followers</text>
    <text class="stat-value" x="30" y="158">{followers:,}</text>
  </g>

  <text class="stat-label fade-in" x="30" y="188" style="animation-delay:0.5s">Top Languages</text>
  {lang_rows}
</svg>"""
    return svg


def main():
    created_at = fetch_account_created_at(USERNAME)
    repo_count, stars, followers, lang_sizes, lang_colors = fetch_repo_stats(USERNAME)
    commits = fetch_total_commits(USERNAME, created_at)
    langs = top_languages(lang_sizes)

    svg = render_svg(USERNAME, repo_count, stars, followers, commits, langs, lang_colors)

    out_path = "stats_card.svg"
    with open(out_path, "w") as f:
        f.write(svg)

    print(f"Wrote {out_path}")
    print(f"  repos={repo_count} stars={stars} followers={followers} commits={commits}")
    print(f"  top languages: {langs}")


if __name__ == "__main__":
    main()
