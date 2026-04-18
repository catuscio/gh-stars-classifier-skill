# gh-stars-classifier-skill

A Claude Code plugin that organizes your GitHub Stars into semantic categories and syncs them to GitHub Lists — using Claude's reasoning instead of a fixed keyword table.

## What it does

1. Fetches every repository you've starred via the GitHub GraphQL API.
2. **Claude proposes a category taxonomy** that actually fits what you've starred (not a generic list).
3. You approve / edit the taxonomy.
4. Claude classifies each repo, shows you a preview, and — after you confirm — writes assignments to your GitHub Lists.

No opaque keyword rules. The LLM does the judgment; the scripts do the API plumbing.

## Install

```
/plugin marketplace add catuscio/gh-stars-classifier-skill
/plugin install gh-stars-classifier@gh-stars-classifier-marketplace
```

Replace `catuscio/gh-stars-classifier-skill` with your own `OWNER/REPO` if you forked this.

## Prerequisites

- [GitHub CLI](https://cli.github.com/) (`gh`) authenticated with the `user` scope:
  ```bash
  gh auth login
  gh auth refresh -h github.com -s user
  ```
- Python 3.8+ on PATH (for the helper scripts).

## Usage

In Claude Code, just ask:

> "organize my starred repos into GitHub Lists"
>
> "classify my GitHub stars into categories"

Claude will load this skill and walk you through five phases, pausing for your approval at each checkpoint.

### Power-user shortcut: bring your own taxonomy

If you run the skill regularly and want a **stable set of categories**, pre-populate `.gh-stars-workspace/categories.json` in your working directory:

```json
[
  {"name": "🤖 Agents",    "description": "autonomous agents, MCP, copilots"},
  {"name": "🧠 LLM Infra", "description": "inference, serving, fine-tuning"},
  ...
]
```

When the file exists, Phase 2 (taxonomy proposal) is skipped and the skill goes straight to reconciling with existing GitHub Lists.

## Behavior notes

**Fetch is cacheable.** The skill calls `fetch_stars.py --reuse-if-fresh 24`, so repeat runs within 24 hours reuse the cached `.gh-stars-workspace/stars.json` instead of refetching. Ask Claude to "refresh my stars" to force a new pull.

**Lists are created automatically** (with your confirmation) via the `createUserList` GraphQL mutation. If the approved taxonomy contains categories that don't yet exist as Lists, the skill will list them, ask you to confirm, and then create each one. Existing lists are reused by name match.

**Manual list assignments are preserved.** `updateUserListsForItem` on its own *replaces* a repo's full list-set, which would normally wipe memberships in any list outside the skill's taxonomy. To avoid that, the skill first reads the current memberships with `get_lists.py --with-items` and passes them to `apply_classification.py --current-memberships`. The apply script then computes `final = (new plan) ∪ (existing memberships in orphan lists)`, so lists you curated by hand are untouched.

## Layout

```
.
├── .claude-plugin/
│   ├── plugin.json          # Plugin manifest
│   └── marketplace.json     # Single-plugin marketplace
├── skills/
│   └── gh-stars-classifier/
│       └── SKILL.md         # Orchestration (what Claude reads)
├── scripts/
│   ├── fetch_stars.py           # Paginated fetch of starred repos
│   ├── get_lists.py             # Enumerate existing Lists
│   ├── create_list.py           # Create a new User List
│   ├── get_repo_id.py           # Resolve owner/name -> node ID
│   └── apply_classification.py  # Apply the plan to GitHub Lists
└── examples/
    └── plan.example.json    # Plan schema reference
```

## Development

### Running scripts standalone

```bash
python3 scripts/fetch_stars.py YOUR_USERNAME --out /tmp/stars.json
python3 scripts/get_lists.py
python3 scripts/apply_classification.py examples/plan.example.json --dry-run
```

### Running tests

The scripts ship with stdlib-only unit tests (no pytest dependency):

```bash
python3 -m unittest discover -s tests -v
```

### Hacking on the skill locally

1. Clone this repo anywhere, e.g. `~/src/gh-stars-classifier-skill`.
2. Install from the local path:
   ```
   /plugin marketplace add ~/src/gh-stars-classifier-skill
   /plugin install gh-stars-classifier@gh-stars-classifier-marketplace
   ```
3. Edit `skills/gh-stars-classifier/SKILL.md` or any script, then in Claude Code run:
   ```
   /plugin reload
   ```
   Changes to `.claude-plugin/plugin.json` or `marketplace.json` require a full Claude Code restart.

### Forking / republishing under your own name

If you fork and want to publish under your own handle, touch these spots:

1. `.claude-plugin/plugin.json` — `author.name`, `homepage`, `repository`
2. `.claude-plugin/marketplace.json` — `owner.name`
3. `README.md` — the `catuscio/gh-stars-classifier-skill` string in the install block
4. `LICENSE` — copyright line if you'd like

Nothing else is owner-coupled.

## License

MIT — see [LICENSE](LICENSE).
