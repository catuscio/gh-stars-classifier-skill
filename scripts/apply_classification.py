#!/usr/bin/env python3
"""Apply a classification plan to GitHub Lists.

Reads a plan JSON of the form:
    {
      "list_ids": {"category_name": "UL_...", ...},
      "assignments": [
        {"repo": "owner/name", "lists": ["category_a", "category_b"]},
        ...
      ]
    }

Resolves each repo to its node ID and calls updateUserListsForItem.

Membership preservation
-----------------------
updateUserListsForItem REPLACES the full list-set for a repo. To avoid
wiping manual assignments to lists outside the taxonomy, pass
--current-memberships from `get_lists.py --with-items` output. The script
then computes:

    final = (new list ids from plan) ∪ (current ids NOT in managed set)

where "managed set" = values of plan.list_ids. Memberships in orphan
lists (not part of this taxonomy) are preserved; memberships in managed
lists are refreshed from the plan.

Without --current-memberships the old replacement behavior is used and a
warning is printed.

Resume support
--------------
Pass --progress-file to append each successful repo to a JSONL log. On
re-run with the same file, already-processed repos are skipped — so an
interrupted bulk apply can be restarted safely without redoing work.

Usage:
    apply_classification.py plan.json
        [--current-memberships PATH]    # get_lists --with-items output
        [--stars-index PATH]            # stars.json (skip per-repo resolve)
        [--progress-file PATH]          # JSONL resume log
        [--dry-run]
        [--sleep SECONDS]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) { id }
}
"""

# GitHub node IDs are base64-ish; length-bounded regex keeps the inlined
# mutation literal safe even if the schema ever admits oddities.
_ID_RE = re.compile(r"^[A-Za-z0-9_=+/-]{1,128}$")


def gh_graphql(args: list[str]) -> dict:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    payload = json.loads(result.stdout)
    if "errors" in payload:
        raise RuntimeError(str(payload["errors"]))
    return payload["data"]


def resolve_repo_id(full: str) -> str:
    owner, name = full.split("/", 1)
    data = gh_graphql([
        "gh", "api", "graphql",
        "-f", f"query={REPO_QUERY}",
        "-F", f"owner={owner}",
        "-F", f"name={name}",
    ])
    if not data["repository"]:
        raise RuntimeError(f"repo not found: {full}")
    return data["repository"]["id"]


def update_lists_for_item(item_id: str, list_ids: list[str]) -> None:
    if not _ID_RE.match(item_id):
        raise RuntimeError(f"unsafe item id: {item_id!r}")
    for lid in list_ids:
        if not _ID_RE.match(lid):
            raise RuntimeError(f"unsafe list id: {lid!r}")
    list_ids_literal = "[" + ",".join(f'"{lid}"' for lid in list_ids) + "]"
    mutation = (
        "mutation { updateUserListsForItem(input: "
        f'{{itemId: "{item_id}", listIds: {list_ids_literal}}}'
        ") { clientMutationId } }"
    )
    gh_graphql(["gh", "api", "graphql", "-f", f"query={mutation}"])


def validate_plan(plan: object) -> tuple[dict, list]:
    if not isinstance(plan, dict):
        raise SystemExit("plan must be a JSON object")
    list_ids = plan.get("list_ids")
    assignments = plan.get("assignments")
    if not isinstance(list_ids, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in list_ids.items()
    ):
        raise SystemExit("plan.list_ids must be {str: str}")
    if not isinstance(assignments, list):
        raise SystemExit("plan.assignments must be a list")
    for i, item in enumerate(assignments):
        if not isinstance(item, dict):
            raise SystemExit(f"plan.assignments[{i}] must be an object")
        if not isinstance(item.get("repo"), str) or "/" not in item["repo"]:
            raise SystemExit(f"plan.assignments[{i}].repo must be 'owner/name'")
        lists = item.get("lists")
        if not isinstance(lists, list) or not all(isinstance(x, str) for x in lists):
            raise SystemExit(f"plan.assignments[{i}].lists must be list[str]")
    return list_ids, assignments


def load_stars_index(path: Path | None) -> dict[str, str]:
    """Build {nameWithOwner: node_id} from stars.json so we can skip
    per-repo resolve calls."""
    if not path:
        return {}
    data = json.loads(path.read_text())
    return {r["nameWithOwner"]: r["id"] for r in data if r.get("id")}


def load_memberships(path: Path | None) -> dict[str, list[str]]:
    """Build inverse index {nameWithOwner: [list_id, ...]} from
    get_lists.py --with-items output."""
    if not path:
        return {}
    data = json.loads(path.read_text())
    inverse: dict[str, list[str]] = {}
    for lst in data:
        for repo in lst.get("items", []):
            inverse.setdefault(repo, []).append(lst["id"])
    return inverse


def load_progress(path: Path | None) -> set[str]:
    """Return the set of repos already completed in a prior apply run.

    Malformed lines are skipped so a half-flushed write doesn't abort
    the resume."""
    if not path or not path.exists():
        return set()
    done: set[str] = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("repo"), str):
            done.add(entry["repo"])
    return done


def append_progress(path: Path | None, repo: str) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"repo": repo, "ts": int(time.time())}) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan")
    parser.add_argument("--current-memberships",
                        help="lists.json from get_lists.py --with-items; preserves orphan assignments")
    parser.add_argument("--stars-index",
                        help="stars.json (skip per-repo ID resolve by using the cached id field)")
    parser.add_argument("--progress-file",
                        help="JSONL resume log; already-processed repos are skipped on re-run")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.2,
                        help="seconds to sleep between mutations (default: 0.2)")
    args = parser.parse_args()

    plan = json.loads(Path(args.plan).read_text())
    list_ids, assignments = validate_plan(plan)
    managed_ids = set(list_ids.values())
    stars_index = load_stars_index(Path(args.stars_index) if args.stars_index else None)
    memberships = load_memberships(
        Path(args.current_memberships) if args.current_memberships else None
    )
    progress_path = Path(args.progress_file) if args.progress_file else None
    # Dry runs deliberately ignore the log so you always see the full plan.
    done_repos = load_progress(progress_path) if not args.dry_run else set()
    if done_repos:
        print(f"resume: {len(done_repos)} repos already processed, skipping",
              file=sys.stderr)

    if not args.current_memberships:
        print("WARNING: --current-memberships not set; manual list assignments "
              "outside the taxonomy will be OVERWRITTEN.", file=sys.stderr)

    total = len(assignments)
    ok, skipped, failed, preserved, resumed = 0, 0, 0, 0, 0

    for idx, item in enumerate(assignments, 1):
        repo = item["repo"]
        cats = item["lists"]

        if repo in done_repos:
            resumed += 1
            continue

        target_ids = [list_ids[c] for c in cats if c in list_ids]
        missing = [c for c in cats if c not in list_ids]
        if missing:
            print(f"[{idx}/{total}] SKIP {repo}: missing list ids for {missing}", file=sys.stderr)
            skipped += 1
            continue

        current = memberships.get(repo, [])
        orphan = [lid for lid in current if lid not in managed_ids]
        final_ids = list(dict.fromkeys(target_ids + orphan))  # dedupe, preserve order
        if orphan:
            preserved += len(orphan)

        if not final_ids:
            print(f"[{idx}/{total}] SKIP {repo}: no target lists", file=sys.stderr)
            skipped += 1
            continue

        if args.dry_run:
            note = f" (+{len(orphan)} preserved)" if orphan else ""
            print(f"[{idx}/{total}] DRY {repo} -> {cats}{note}")
            ok += 1
            continue

        try:
            item_id = stars_index.get(repo) or resolve_repo_id(repo)
            update_lists_for_item(item_id, final_ids)
            note = f" (+{len(orphan)} preserved)" if orphan else ""
            print(f"[{idx}/{total}] OK   {repo} -> {cats}{note}")
            append_progress(progress_path, repo)
            ok += 1
            time.sleep(args.sleep)
        except Exception as exc:
            print(f"[{idx}/{total}] FAIL {repo}: {exc}", file=sys.stderr)
            failed += 1

    summary = (f"\ndone. ok={ok} skipped={skipped} failed={failed} "
               f"orphan_memberships_preserved={preserved}")
    if resumed:
        summary += f" resumed_skipped={resumed}"
    print(summary)


if __name__ == "__main__":
    main()
