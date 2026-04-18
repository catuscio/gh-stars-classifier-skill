#!/usr/bin/env python3
"""Resolve owner/name to a GitHub Repository node ID.

Usage:
    get_repo_id.py owner/name
"""
from __future__ import annotations

import json
import subprocess
import sys

QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) { id }
}
"""


def main() -> None:
    if len(sys.argv) != 2 or "/" not in sys.argv[1]:
        sys.exit("usage: get_repo_id.py owner/name")
    owner, name = sys.argv[1].split("/", 1)
    result = subprocess.run(
        [
            "gh", "api", "graphql",
            "-f", f"query={QUERY}",
            "-F", f"owner={owner}",
            "-F", f"name={name}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(f"gh api failed: {result.stderr.strip()}")
    payload = json.loads(result.stdout)
    if "errors" in payload or not payload["data"]["repository"]:
        sys.exit(f"could not resolve {sys.argv[1]}: {payload.get('errors')}")
    print(payload["data"]["repository"]["id"])


if __name__ == "__main__":
    main()
