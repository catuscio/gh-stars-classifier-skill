#!/usr/bin/env python3
"""Fetch all starred repositories for a GitHub user via GraphQL.

Usage:
    fetch_stars.py <username> [--out PATH]

Streams progress to stderr, writes the JSON array of repos to --out
(default: ./stars.json). Requires `gh` CLI authenticated with user scope.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    starredRepositories(first: 100, after: $cursor, orderBy: {field: STARRED_AT, direction: DESC}) {
      nodes {
        id
        name
        nameWithOwner
        url
        description
        primaryLanguage { name }
        stargazerCount
        repositoryTopics(first: 20) {
          nodes { topic { name } }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


def run_query(login: str, cursor: str | None) -> dict:
    args = ["gh", "api", "graphql", "-f", f"query={QUERY}", "-F", f"login={login}"]
    if cursor:
        args += ["-F", f"cursor={cursor}"]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"gh api failed: {result.stderr.strip()}")
    payload = json.loads(result.stdout)
    if "errors" in payload:
        sys.exit(f"GraphQL errors: {payload['errors']}")
    return payload["data"]["user"]["starredRepositories"]


def flatten(repo: dict) -> dict:
    return {
        "id": repo["id"],
        "name": repo["name"],
        "nameWithOwner": repo["nameWithOwner"],
        "url": repo["url"],
        "description": repo.get("description") or "",
        "language": (repo.get("primaryLanguage") or {}).get("name") or "",
        "stars": repo.get("stargazerCount", 0),
        "topics": [t["topic"]["name"] for t in repo.get("repositoryTopics", {}).get("nodes", [])],
    }


def stratified_sample(items: list[dict], n: int) -> list[dict]:
    """Round-robin across languages so the sample covers the user's breadth."""
    if len(items) <= n:
        return items
    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in items:
        buckets[r["language"] or "None"].append(r)
    result: list[dict] = []
    while len(result) < n and buckets:
        for lang in list(buckets.keys()):
            if len(result) >= n:
                break
            result.append(buckets[lang].pop(0))
            if not buckets[lang]:
                del buckets[lang]
    return result


def trim_for_summary(repo: dict) -> dict:
    desc = repo["description"]
    return {
        "nameWithOwner": repo["nameWithOwner"],
        "description": (desc[:200] + "…") if len(desc) > 200 else desc,
        "language": repo["language"],
        "stars": repo["stars"],
        "topics": repo["topics"][:8],
    }


def build_summary(repos: list[dict], sample_size: int) -> dict:
    return {
        "total": len(repos),
        "languages": Counter(r["language"] or "None" for r in repos).most_common(15),
        "topics": Counter(t for r in repos for t in r["topics"]).most_common(30),
        "sample": [trim_for_summary(r) for r in stratified_sample(repos, sample_size)],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("--out", default="stars.json")
    parser.add_argument("--sample-size", type=int, default=60,
                        help="entries in the summary sample (default: 60)")
    parser.add_argument("--reuse-if-fresh", type=float, default=0,
                        help="skip the API fetch if --out exists and is younger "
                             "than N hours; summary is always rebuilt. (default: 0 = always fetch)")
    args = parser.parse_args()

    out = Path(args.out)
    reuse = False
    if args.reuse_if_fresh > 0 and out.exists():
        age_hours = (time.time() - out.stat().st_mtime) / 3600
        if age_hours < args.reuse_if_fresh:
            reuse = True
            print(f"reusing {out} (age {age_hours:.1f}h < {args.reuse_if_fresh}h)",
                  file=sys.stderr)

    collected: list[dict] | None = None
    if reuse:
        try:
            collected = json.loads(out.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            print(f"cached {out} unreadable ({exc}); refetching", file=sys.stderr)
            collected = None

    if collected is None:
        collected = []
        cursor: str | None = None
        while True:
            page = run_query(args.username, cursor)
            collected.extend(flatten(n) for n in page["nodes"])
            print(f"fetched {len(collected)} repos...", file=sys.stderr)
            if not page["pageInfo"]["hasNextPage"]:
                break
            cursor = page["pageInfo"]["endCursor"]
        out.write_text(json.dumps(collected, ensure_ascii=False, indent=2))
        print(f"wrote {len(collected)} repos to {out}", file=sys.stderr)

    summary_path = out.with_name(out.stem + ".summary.json")
    summary = build_summary(collected, args.sample_size)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"wrote summary to {summary_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
