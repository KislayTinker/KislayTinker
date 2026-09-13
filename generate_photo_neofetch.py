#!/usr/bin/env python3
"""
generate_photo_neofetch.py

Combines:
  1. A photo converted to dense ASCII/block art (left column)
  2. Live GitHub stats in neofetch/fastfetch style (right column)

...into a single fenced code block, injected into README.md between
marker comments:

    <!-- NEOFETCH:START -->
    ...generated content...
    <!-- NEOFETCH:END -->

Requires:
    pip install requests pillow
    env ACCESS_TOKEN=<github PAT with read:user + repo>
    env GITHUB_USERNAME=KislayTinker
    photo.png must sit alongside this script (commit it to the repo once;
    it doesn't change on every run, only the stats do).
"""

import os
import sys
import datetime
import requests
from PIL import Image, ImageOps

USERNAME = os.environ.get("GITHUB_USERNAME", "KislayTinker")
TOKEN = os.environ.get("ACCESS_TOKEN")
README_PATH = os.environ.get("README_PATH", "README.md")
PHOTO_PATH = os.environ.get("PHOTO_PATH", "photo.png")
ART_WIDTH = int(os.environ.get("ART_WIDTH", "42"))  # characters wide

START_MARKER = "<!-- NEOFETCH:START -->"
END_MARKER = "<!-- NEOFETCH:END -->"

if not TOKEN:
    print("ERROR: ACCESS_TOKEN not set", file=sys.stderr)
    sys.exit(1)

HEADERS = {"Authorization": f"bearer {TOKEN}"}
API_URL = "https://api.github.com/graphql"

QUERY = """
query ($login: String!, $cursor: String) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    repositories(first: 100, after: $cursor, ownerAffiliations: OWNER, isFork: false) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        stargazers { totalCount }
        primaryLanguage { name }
      }
    }
  }
}
"""

COMMITS_QUERY = """
query ($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      restrictedContributionsCount
    }
  }
}
"""

# Dense-to-sparse ramp: index 0 = darkest/densest char, last = blank.
RAMP = "@@@@%%%%##**++==;;::,,..    "


def gql(query, variables):
    r = requests.post(API_URL, json={"query": query, "variables": variables}, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


def fetch_stats(login):
    stars = 0
    repo_count = 0
    langs = {}
    cursor = None
    created_at = None
    followers = 0
    while True:
        data = gql(QUERY, {"login": login, "cursor": cursor})
        user = data["user"]
        created_at = user["createdAt"]
        followers = user["followers"]["totalCount"]
        repos = user["repositories"]
        repo_count = repos["totalCount"]
        for node in repos["nodes"]:
            stars += node["stargazers"]["totalCount"]
            lang = node["primaryLanguage"]["name"] if node["primaryLanguage"] else None
            if lang:
                langs[lang] = langs.get(lang, 0) + 1
        if not repos["pageInfo"]["hasNextPage"]:
            break
        cursor = repos["pageInfo"]["endCursor"]

    start = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    now = datetime.datetime.now(datetime.timezone.utc)
    total_commits = 0
    cur = start
    while cur < now:
        window_end = min(cur + datetime.timedelta(days=365), now)
        cc = gql(COMMITS_QUERY, {"login": login, "from": cur.isoformat(), "to": window_end.isoformat()})
        c = cc["user"]["contributionsCollection"]
        total_commits += c["totalCommitContributions"] + c["restrictedContributionsCount"]
        cur = window_end

    uptime_days = (now - start).days
    years = uptime_days // 365
    months = (uptime_days % 365) // 30
    days = (uptime_days % 365) % 30

    top_langs = sorted(langs.items(), key=lambda kv: kv[1], reverse=True)[:5]

    return {
        "repo_count": repo_count,
        "stars": stars,
        "followers": followers,
        "commits": total_commits,
        "uptime": f"{years} years, {months} months, {days} days",
        "top_langs": [name for name, _ in top_langs],
    }


def image_to_ascii_lines(path, out_width=42, char_aspect=2.0):
    img = Image.open(path).convert("L")
    img = ImageOps.autocontrast(img, cutoff=1)
    w, h = img.size
    out_height = int((h / w) * out_width / char_aspect)
    img = img.resize((out_width, out_height))
    pixels = img.load()
    ramp_len = len(RAMP)

    lines = []
    for y in range(out_height):
        row = []
        for x in range(out_width):
            brightness = pixels[x, y]
            idx = int(brightness / 255 * (ramp_len - 1))
            row.append(RAMP[idx])
        lines.append("".join(row))
    return lines


def dot_line(label, value, total_width=48):
    dots_needed = max(total_width - len(label) - len(value) - 2, 3)
    return f"{label}: {'.' * dots_needed} {value}"


def build_info_lines(username, stats):
    return [
        f"{username.lower()}@github",
        "-" * (len(username) + 7),
        dot_line("OS", "Linux, Windows, Android"),
        dot_line("Uptime", stats["uptime"]),
        dot_line("Host", "Arya College of Engineering, Jaipur"),
        dot_line("Role", "Data Analytics Intern @ Coderbot"),
        "",
        dot_line("Languages.Programming", ", ".join(stats["top_langs"]) or "N/A"),
        dot_line("Languages.Human", "English, Hindi"),
        "",
        dot_line("Interests", "ML/AI research, systems, football"),
        "",
        "- GitHub Stats " + "-" * 20,
        dot_line("Repos", str(stats["repo_count"])),
        dot_line("Stars", str(stats["stars"])),
        dot_line("Commits", str(stats["commits"])),
        dot_line("Followers", str(stats["followers"])),
    ]


def build_block(username, stats):
    art_lines = image_to_ascii_lines(PHOTO_PATH, out_width=ART_WIDTH)
    info_lines = build_info_lines(username, stats)

    art_width = max((len(l) for l in art_lines), default=0)
    max_lines = max(len(art_lines), len(info_lines))

    rows = []
    for i in range(max_lines):
        left = art_lines[i] if i < len(art_lines) else ""
        right = info_lines[i] if i < len(info_lines) else ""
        rows.append(f"{left.ljust(art_width)}   {right}")

    body = "\n".join(rows)
    return f"```text\n{body}\n```"


def inject_into_readme(block):
    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    new_section = f"{START_MARKER}\n{block}\n{END_MARKER}"

    if START_MARKER in content and END_MARKER in content:
        start = content.index(START_MARKER)
        end = content.index(END_MARKER) + len(END_MARKER)
        content = content[:start] + new_section + content[end:]
    else:
        content = content.rstrip() + "\n\n" + new_section + "\n"

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    stats = fetch_stats(USERNAME)
    block = build_block(USERNAME, stats)
    inject_into_readme(block)
    print("README updated with photo + stats block.")
    print(block)


if __name__ == "__main__":
    main()
