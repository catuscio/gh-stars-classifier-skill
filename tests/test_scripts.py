"""Unit tests for the pure-function helpers in scripts/.

Run from the repo root:
    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from fetch_stars import (  # noqa: E402
    flatten,
    stratified_sample,
    trim_for_summary,
)
from apply_classification import (  # noqa: E402
    append_progress,
    load_memberships,
    load_progress,
    load_stars_index,
    validate_plan,
)
from get_lists import load_taxonomy_names  # noqa: E402


class StratifiedSampleTests(unittest.TestCase):
    def test_returns_all_when_n_gte_len(self):
        items = [{"language": "Python"}, {"language": "Go"}]
        self.assertEqual(stratified_sample(items, 5), items)
        self.assertEqual(stratified_sample(items, 2), items)

    def test_round_robin_picks_each_language_before_repeating(self):
        items = [
            {"language": "Python", "name": "p1"},
            {"language": "Python", "name": "p2"},
            {"language": "Python", "name": "p3"},
            {"language": "Go", "name": "g1"},
            {"language": "Go", "name": "g2"},
        ]
        picked = stratified_sample(items, 3)
        self.assertEqual(len(picked), 3)
        self.assertEqual({i["language"] for i in picked[:2]}, {"Python", "Go"})

    def test_empty_language_is_bucketed(self):
        items = [{"language": "", "name": "a"}, {"language": "", "name": "b"}]
        self.assertEqual(len(stratified_sample(items, 10)), 2)


class FlattenTests(unittest.TestCase):
    def test_null_primary_language_becomes_empty_string(self):
        raw = {
            "id": "R_1",
            "name": "x",
            "nameWithOwner": "o/x",
            "url": "https://x",
            "description": None,
            "primaryLanguage": None,
            "stargazerCount": 0,
            "repositoryTopics": {"nodes": []},
        }
        out = flatten(raw)
        self.assertEqual(out["language"], "")
        self.assertEqual(out["description"], "")
        self.assertEqual(out["topics"], [])

    def test_topics_and_stars_extracted(self):
        raw = {
            "id": "R_2",
            "name": "y",
            "nameWithOwner": "o/y",
            "url": "https://y",
            "description": "d",
            "primaryLanguage": {"name": "Rust"},
            "stargazerCount": 42,
            "repositoryTopics": {
                "nodes": [{"topic": {"name": "cli"}}, {"topic": {"name": "llm"}}]
            },
        }
        out = flatten(raw)
        self.assertEqual(out["topics"], ["cli", "llm"])
        self.assertEqual(out["language"], "Rust")
        self.assertEqual(out["stars"], 42)


class TrimForSummaryTests(unittest.TestCase):
    def test_long_description_truncated_with_ellipsis(self):
        repo = {
            "nameWithOwner": "o/n",
            "description": "x" * 500,
            "language": "Go",
            "stars": 10,
            "topics": list("abcdefghij"),
        }
        out = trim_for_summary(repo)
        self.assertTrue(out["description"].endswith("…"))
        self.assertEqual(len(out["description"]), 201)
        self.assertEqual(len(out["topics"]), 8)

    def test_short_description_unchanged(self):
        repo = {
            "nameWithOwner": "o/n",
            "description": "short",
            "language": "Go",
            "stars": 10,
            "topics": ["a", "b"],
        }
        out = trim_for_summary(repo)
        self.assertEqual(out["description"], "short")


class ValidatePlanTests(unittest.TestCase):
    def test_valid_plan(self):
        plan = {
            "list_ids": {"A": "UL_1", "B": "UL_2"},
            "assignments": [{"repo": "o/a", "lists": ["A"]}],
        }
        list_ids, assignments = validate_plan(plan)
        self.assertEqual(list_ids, {"A": "UL_1", "B": "UL_2"})
        self.assertEqual(len(assignments), 1)

    def test_rejects_non_dict(self):
        with self.assertRaises(SystemExit):
            validate_plan([])

    def test_rejects_bad_list_ids(self):
        with self.assertRaises(SystemExit):
            validate_plan({"list_ids": {"A": 1}, "assignments": []})

    def test_rejects_non_list_assignments(self):
        with self.assertRaises(SystemExit):
            validate_plan({"list_ids": {}, "assignments": "nope"})

    def test_rejects_repo_without_slash(self):
        with self.assertRaises(SystemExit):
            validate_plan({
                "list_ids": {},
                "assignments": [{"repo": "no-slash", "lists": []}],
            })

    def test_rejects_lists_as_string(self):
        with self.assertRaises(SystemExit):
            validate_plan({
                "list_ids": {},
                "assignments": [{"repo": "o/a", "lists": "A"}],
            })


def _write_json(data) -> Path:
    tmp = tempfile.NamedTemporaryFile(
        "w", delete=False, suffix=".json", encoding="utf-8"
    )
    json.dump(data, tmp)
    tmp.close()
    return Path(tmp.name)


class LoadMembershipsTests(unittest.TestCase):
    def test_none_path_returns_empty(self):
        self.assertEqual(load_memberships(None), {})

    def test_builds_inverse_index(self):
        path = _write_json([
            {"id": "L1", "name": "A", "items": ["o/x", "o/y"]},
            {"id": "L2", "name": "B", "items": ["o/x"]},
            {"id": "L3", "name": "C"},
        ])
        self.assertEqual(
            load_memberships(path),
            {"o/x": ["L1", "L2"], "o/y": ["L1"]},
        )


class LoadStarsIndexTests(unittest.TestCase):
    def test_name_with_owner_to_id(self):
        path = _write_json([
            {"nameWithOwner": "o/a", "id": "R_1"},
            {"nameWithOwner": "o/b", "id": "R_2"},
            {"nameWithOwner": "o/c"},
        ])
        self.assertEqual(
            load_stars_index(path),
            {"o/a": "R_1", "o/b": "R_2"},
        )


class ProgressFileTests(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.jsonl"
            self.assertEqual(load_progress(path), set())
            append_progress(path, "o/a")
            append_progress(path, "o/b")
            self.assertEqual(load_progress(path), {"o/a", "o/b"})

    def test_tolerates_bad_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.jsonl"
            path.write_text('{"repo":"o/a"}\nnot-json\n{"not":"repo"}\n')
            self.assertEqual(load_progress(path), {"o/a"})

    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_progress(Path(tmp) / "missing.jsonl"), set())


class TaxonomyNamesTests(unittest.TestCase):
    def test_empty_when_path_none(self):
        self.assertEqual(load_taxonomy_names(None), set())

    def test_extracts_names(self):
        path = _write_json([
            {"name": "A", "description": "a"},
            {"name": "B"},
            {"description": "no name"},
            "not-a-dict",
        ])
        self.assertEqual(load_taxonomy_names(str(path)), {"A", "B"})


if __name__ == "__main__":
    unittest.main()
