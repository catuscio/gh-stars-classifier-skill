#!/usr/bin/env python3
"""Fetch the viewer's GitHub Lists and print them as JSON.

Usage:
    get_lists.py [--out PATH] [--with-items]

Without --with-items: prints [{"id","name","slug","isPrivate"}], paginated
across all lists.

With --with-items: also enumerates each list's member repositories (paginated)
and emits [{"id","name","slug","isPrivate","items":["owner/name", ...]}].
This is what apply_classification.py needs to preserve manual memberships.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

LISTS_QUERY = """
query($cursor: String) {
  viewer {
    lists(first: 50, after: $cursor) {
      nodes { id name slug isPrivate }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""

ITEMS_QUERY = """
query($listId: ID!, $cursor: String) {
  node(id: $listId) {
    ... on UserList {
      items(first: 100, after: $cursor) {
        nodes {
          ... on Repository { nameWithOwner }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""


def gh_graphql(query: str, variables: dict) -> dict:
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        args += ["-F", f"{k}={v}"] if v is not None else []
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"gh api failed: {result.stderr.strip()}")
    payload = json.loads(result.stdout)
    if "errors" in payload:
        sys.exit(f"GraphQL errors: {payload['errors']}")
    return payload["data"]


def fetch_all_lists() -> list[dict]:
    collected: list[dict] = []
    cursor: str | None = None
    while True:
        data = gh_graphql(LISTS_QUERY, {"cursor": cursor} if cursor else {})
        page = data["viewer"]["lists"]
        collected.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            return collected
        cursor = page["pageInfo"]["endCursor"]


def fetch_list_items(list_id: str) -> list[str]:
    items: list[str] = []
    cursor: str | None = None
    while True:
        data = gh_graphql(
            ITEMS_QUERY,
            {"listId": list_id, "cursor": cursor} if cursor else {"listId": list_id},
        )
        page = data["node"]["items"]
        items.extend(n["nameWithOwner"] for n in page["nodes"] if n.get("nameWithOwner"))
        if not page["pageInfo"]["hasNextPage"]:
            return items
        cursor = page["pageInfo"]["endCursor"]


def load_taxonomy_names(path: str | None) -> set[str]:
    if not path:
        return set()
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"could not read --taxonomy {path}: {exc}")
    return {
        c["name"] for c in data
        if isinstance(c, dict) and isinstance(c.get("name"), str)
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    parser.add_argument("--with-items", action="store_true",
                        help="also fetch each list's member repositories")
    parser.add_argument("--taxonomy",
                        help="categories.json path; lists whose name appears in "
                             "the taxonomy skip the per-list items fetch "
                             "(apply_classification only needs orphan memberships)")
    args = parser.parse_args()

    lists = fetch_all_lists()
    skip_names = load_taxonomy_names(args.taxonomy)

    if args.with_items:
        for lst in lists:
            if lst["name"] in skip_names:
                lst["items"] = []
                print(f"  {lst['name']}: skipped (taxonomy)", file=sys.stderr)
                continue
            lst["items"] = fetch_list_items(lst["id"])
            print(f"  {lst['name']}: {len(lst['items'])} items", file=sys.stderr)

    text = json.dumps(lists, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {len(lists)} lists to {args.out}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
