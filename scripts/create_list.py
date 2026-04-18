#!/usr/bin/env python3
"""Create a new GitHub User List via GraphQL.

Usage:
    create_list.py --name NAME [--description TEXT] [--private]

Prints the new list as JSON: {"id": "UL_...", "name": "...", "slug": "..."}.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

MUTATION = """
mutation($name: String!, $description: String, $isPrivate: Boolean) {
  createUserList(input: {name: $name, description: $description, isPrivate: $isPrivate}) {
    list { id name slug isPrivate }
  }
}
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()

    cmd = [
        "gh", "api", "graphql",
        "-f", f"query={MUTATION}",
        "-f", f"name={args.name}",
    ]
    if args.description:
        cmd += ["-f", f"description={args.description}"]
    cmd += ["-F", f"isPrivate={'true' if args.private else 'false'}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"gh api failed: {result.stderr.strip()}")
    payload = json.loads(result.stdout)
    if "errors" in payload:
        sys.exit(f"GraphQL errors: {payload['errors']}")

    new_list = payload["data"]["createUserList"]["list"]
    print(json.dumps(new_list, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
