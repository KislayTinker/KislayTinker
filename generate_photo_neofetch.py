#!/usr/bin/env python3

import os
import sys
import datetime
import requests
from PIL import Image, ImageOps

USERNAME = os.environ.get("GITHUB_USERNAME", "KislayTinker")
TOKEN = os.environ.get("ACCESS_TOKEN")
README_PATH = os.environ.get("README_PATH", "README.md")
PHOTO_PATH = os.environ.get("PHOTO_PATH", "photo.png")
ART_WIDTH = int(os.environ.get("ART_WIDTH", "55"))  # characters wide

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
        name
        stargazers { totalCount }
        primaryLanguage { name }
      }
    }
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays { date contributionCount }
        }
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


def gql(query, variables):
    r = requests.post(API_URL, json={"query": query, "variables": variables}, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


def compute_streaks(days):
    """days: list of {"date": "YYYY-MM-DD", "contributionCount": int}, chronological."""
    longest = current = 0
    running = 0
    for d in days:
        if d["contributionCount"] > 0:
            running += 1
            longest = max(longest, running)
        else:
            running = 0
    # current streak = count back from the most recent day with contributions
    for d in reversed(days):
        if d["contributionCount"] > 0:
            current += 1
        else:
            break
    return current, longest


def fetch_stats(login):
    stars = 0
    repo_count = 0
    langs = {}
    cursor = None
    created_at = None
    followers = 0
    best_repo = None
    best_repo_stars = -1
    calendar = None
    while True:
        data = gql(QUERY, {"login": login, "cursor": cursor})
        user = data["user"]
        created_at = user["createdAt"]
        followers = user["followers"]["totalCount"]
        calendar = user["contributionsCollection"]["contributionCalendar"]
        repos = user["repositories"]
        repo_count = repos["totalCount"]
        for node in repos["nodes"]:
            s = node["stargazers"]["totalCount"]
            stars += s
            if s > best_repo_stars:
                best_repo_stars = s
                best_repo = node["name"]
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
    days_rem = (uptime_days % 365) % 30

    top_langs = sorted(langs.items(), key=lambda kv: kv[1], reverse=True)[:5]

    all_days = [d for week in calendar["weeks"] for d in week["contributionDays"]]
    current_streak, longest_streak = compute_streaks(all_days)

    return {
        "repo_count": repo_count,
        "stars": stars,
        "followers": followers,
        "commits": total_commits,
        "uptime": f"{years} years, {months} months, {days_rem} days",
        "top_langs": [name for name, _ in top_langs],
        "contributions_this_year": calendar["totalContributions"],
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "best_repo": best_repo or "N/A",
        "best_repo_stars": max(best_repo_stars, 0),
    }


import numpy as np

# Dense-to-sparse ramp for dithering: index 0 = darkest ink char, last = blank.
DITHER_RAMP = "@%#*+=:. "

# Default crop box tuned for this specific photo (head + shoulders, minimal
# background). Override with PHOTO_CROP="left,top,right,bottom" if you swap photos.
DEFAULT_CROP = (230, 20, 500, 320)


def _floyd_steinberg(arr, ramp=DITHER_RAMP):
    h, w = arr.shape
    levels = len(ramp) - 1
    arr = arr.copy()
    out = [[" "] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            old = arr[y, x]
            level = round(old / 255 * levels)
            level = min(max(level, 0), levels)
            new = level / levels * 255
            err = old - new
            out[y][x] = ramp[levels - level]  # bright -> dense char, dark -> sparse
            if x + 1 < w:
                arr[y, x + 1] += err * 7 / 16
            if y + 1 < h:
                if x - 1 >= 0:
                    arr[y + 1, x - 1] += err * 3 / 16
                arr[y + 1, x] += err * 5 / 16
                if x + 1 < w:
                    arr[y + 1, x + 1] += err * 1 / 16
    return ["".join(row) for row in out]


def image_to_ascii_lines(path, out_width=55, char_aspect=2.0, contrast=1.5, crop_box=None):
    from PIL import ImageEnhance
    img = Image.open(path).convert("L")
    box = crop_box or DEFAULT_CROP
    if box:
        img = img.crop(box)
    img = ImageOps.autocontrast(img, cutoff=1)
    img = ImageEnhance.Contrast(img).enhance(contrast)
    w, h = img.size
    out_height = int((h / w) * out_width / char_aspect)
    img = img.resize((out_width, out_height), Image.LANCZOS)
    arr = np.asarray(img, dtype=np.float64)
    return _floyd_steinberg(arr)


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
        dot_line("Contributions (this yr)", str(stats["contributions_this_year"])),
        dot_line("Current Streak", f"{stats['current_streak']} days"),
        dot_line("Longest Streak", f"{stats['longest_streak']} days"),
        dot_line("Top Repo", f"{stats['best_repo']} ({stats['best_repo_stars']}★)"),
    ]


def build_block(username, stats):
    art_lines = image_to_ascii_lines(PHOTO_PATH, out_width=ART_WIDTH, char_aspect=2.0, contrast=1.5)
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
