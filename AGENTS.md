# GitHub Stars Classifier — Agent Workflow

Canonical, portable workflow shared by every agentic CLI that reads repo-local
instruction files (Codex CLI, opencode, Claude Code, Gemini CLI via `@import`).

**Goal**: Organize the user's GitHub Stars into semantic categories and sync
them to GitHub Lists. Categories are proposed **dynamically** based on what
the user has actually starred — not from a hardcoded keyword table.

## When to invoke

The user says things like:

- "organize my GitHub stars"
- "classify my starred repos into GitHub Lists"
- "clean up my starred repositories"

## Prerequisites (check first, fail fast)

```bash
gh --version                                   # gh CLI installed
gh auth status                                 # authenticated
gh api user --jq .login                        # prints username
gh auth status 2>&1 | grep -q "'user'" || echo "need 'user' scope"
```

If `user` scope is missing: `gh auth refresh -h github.com -s user`.

## Root resolver (run once, before any phase)

Every phase calls scripts under `scripts/`. Resolve the repo root before the
first bash command of the session:

```bash
: "${GH_STARS_CLASSIFIER_ROOT:=${CLAUDE_PLUGIN_ROOT:-$PWD}}"
: "${GH_STARS_CLASSIFIER_ROOT:?set GH_STARS_CLASSIFIER_ROOT to the gh-stars-classifier-skill clone path}"
test -d "${GH_STARS_CLASSIFIER_ROOT}/scripts" || {
  echo "scripts/ not found under ${GH_STARS_CLASSIFIER_ROOT}"; exit 1;
}
```

- **Claude Code plugin**: `CLAUDE_PLUGIN_ROOT` is auto-set, so the resolver
  picks it up with no extra work.
- **Codex CLI / opencode / Gemini CLI**: `cd` into the repo clone (so `$PWD`
  works), or export `GH_STARS_CLASSIFIER_ROOT` explicitly.

Every `python3` invocation below uses `"${GH_STARS_CLASSIFIER_ROOT}/scripts/..."`.
Do not invent ad-hoc one-liners — the bundled scripts cover every step.

## Workflow

Follow these phases in order. Pause for user confirmation at each **[CONFIRM]**
checkpoint.

### Phase 1 — Fetch stars

```bash
mkdir -p .gh-stars-workspace
python3 "${GH_STARS_CLASSIFIER_ROOT}/scripts/fetch_stars.py" "$(gh api user --jq .login)" \
  --out .gh-stars-workspace/stars.json \
  --reuse-if-fresh 24
```

`--reuse-if-fresh 24` skips the API round-trip if the cached `stars.json` is
less than 24 h old. The summary is rebuilt either way, so bumping
`--sample-size` on a re-run is free. If the user explicitly asks to refresh,
drop the flag or delete `stars.json`.

Two files are written:

- `stars.json` — full flattened list, one entry per starred repo. Each entry:
  `{id, name, nameWithOwner, url, description, language, stars, topics}`.
  The `id` is the GraphQL node ID; Phase 5 uses it to skip per-repo resolve
  calls.
- `stars.summary.json` — pre-reduced view for Phase 2 (read this, not the raw
  list).

`stars.summary.json` schema:

```json
{
  "total": 575,
  "languages": [["Python", 142], ["TypeScript", 88], ...],
  "topics":    [["llm", 61], ["cli", 43], ...],
  "sample":    [{"nameWithOwner": "...", "description": "...",
                 "language": "...", "stars": 1234,
                 "topics": ["...", ...]}, ...]
}
```

Do **not** write ad-hoc analysis scripts against `stars.json` — everything
needed for category design is already in `stars.summary.json`.

### Phase 2 — Propose categories (with descriptions) **[CONFIRM]**

**Pre-existing taxonomy shortcut**: if `.gh-stars-workspace/categories.json`
already exists and is a valid list of `{name, description}` objects, **skip
the proposal step**. Load it, show a one-line summary ("Using N pre-defined
categories from categories.json"), confirm briefly, and jump to Phase 3.
Power users who re-run the skill weekly rely on this path for a stable
taxonomy.

Otherwise, propose fresh:

Read `stars.summary.json` (histograms + stratified sample). Based on the
language mix, topic frequencies, and representative repos, **propose a
category taxonomy** that fits this user's stars. Aim for 6–14 categories.
For **each** category, generate both:

- **name** — the List name shown on GitHub (include emoji if the user's style
  favors it; check existing Lists with `get_lists.py` first)
- **description** — a one-line description that (a) will be stored on the
  GitHub List itself via `createUserList` and (b) doubles as a classification
  hint in Phase 4

Good proposals:

- Are **mutually distinguishable** (don't propose both "AI" and "ML" as peers)
- Mix **domain** (LLM, DevOps, Security) and **form** (CLI tools, Learning
  resources) only when it clearly helps
- Include an `etc` / `Other` bucket for uncategorized items
- Descriptions are specific and scannable (not "various things") — they are
  visible to anyone viewing the List on github.com

Present the proposal like this, then ask the user to approve/edit **both
names and descriptions**:

```
Proposed categories (N total):

 1. 🤖 Agents
    → autonomous agents, MCP servers, copilots, orchestration frameworks
 2. 🧠 LLM Infra
    → inference engines, model serving, fine-tuning, quantization
 3. 📊 Data Engineering
    → ETL pipelines, warehouses, streaming, batch processing
...

Ready to proceed? Let me know if you want to rename, add, remove, or
rewrite any category. (Descriptions are shown on the GitHub List page itself.)
```

Write the approved taxonomy to `.gh-stars-workspace/categories.json`:

```json
[
  {
    "name": "🤖 Agents",
    "description": "autonomous agents, MCP servers, copilots, orchestration frameworks"
  }
]
```

### Phase 3 — Reconcile with existing Lists **[CONFIRM]**

```bash
python3 "${GH_STARS_CLASSIFIER_ROOT}/scripts/get_lists.py" \
  --with-items \
  --taxonomy .gh-stars-workspace/categories.json \
  --out .gh-stars-workspace/lists.json
```

`--with-items` pulls each list's current repositories so Phase 5 can
**preserve** manual assignments to lists outside the taxonomy (see
Guardrails). `--taxonomy` skips the per-list items fetch for lists already
in the approved taxonomy — those will be fully replaced by the apply step
anyway, so fetching them is wasted work. Only orphan lists' items are
actually needed for preservation.

Compare category names vs existing List names (case-insensitive,
emoji-tolerant). Three cases:

1. **Exact/near match** → reuse the existing list ID.
2. **Missing list** → confirm with the user (they already approved
   names+descriptions in Phase 2, but re-show which ones are *new*), then for
   each missing category read its `description` field from `categories.json`
   and run:

   ```bash
   python3 "${GH_STARS_CLASSIFIER_ROOT}/scripts/create_list.py" \
     --name "🤖 Agents" \
     --description "autonomous agents, MCP servers, copilots, orchestration frameworks"
   ```

   Repeat for every missing list. `--private` is available if the user wants
   private lists. Re-run `get_lists.py` after creation to refresh IDs.
3. **Orphan list** (exists but not in taxonomy) → leave it alone, don't
   touch.

### Phase 4 — Build classification plan **[CONFIRM]**

Classify every repo in `stars.json` into 1–3 of the approved categories.
Reason from name + description + topics + language. Write the plan to
`.gh-stars-workspace/plan.json` matching the schema in
`examples/plan.example.json`:

```json
{
  "list_ids": {"🤖 Agents": "UL_...", "...": "..."},
  "assignments": [
    {"repo": "microsoft/autogen", "lists": ["🤖 Agents"]}
  ]
}
```

Show the user a **summary** before applying:

```
Classified 342 repos:
  🤖 Agents: 47
  🧠 LLM Infra: 38
  ...
  ⚫ etc: 12

Sample assignments:
  microsoft/autogen → 🤖 Agents
  vllm-project/vllm → 🧠 LLM Infra
  ...

Apply now? (You can preview with --dry-run first.)
```

### Phase 5 — Apply

Always pass both `--stars-index` (skip per-repo resolve) and
`--current-memberships` (preserve manual assignments to orphan lists).
Run dry-run first:

```bash
python3 "${GH_STARS_CLASSIFIER_ROOT}/scripts/apply_classification.py" \
  .gh-stars-workspace/plan.json \
  --stars-index .gh-stars-workspace/stars.json \
  --current-memberships .gh-stars-workspace/lists.json \
  --progress-file .gh-stars-workspace/apply.progress.jsonl \
  --dry-run
```

Then apply for real (drop `--dry-run`). The script sleeps 0.2 s between
mutations. For > 500 repos, warn the user about the 5000 points/hour rate
limit and offer `--sleep 1.0`.

`--progress-file` appends each successful repo to a JSONL log. If the apply
is interrupted (network flake, rate limit, Ctrl-C), re-running the exact
same command resumes where it left off — repos already in the log are
skipped. Dry runs ignore the log so you always see the full plan.

Never omit `--current-memberships` — without it the script prints a WARNING
and falls back to replace-all semantics that destroy manual list
assignments.

## Guardrails

- **Never** create or delete GitHub Lists silently. Always confirm with the
  user.
- **Never** call `updateUserListsForItem` without showing the assignment
  first.
- If the plan has > 200 repos, default to dry-run and wait for explicit
  approval before the real run.
- Preserve manual list assignments automatically: Phase 3 fetches
  `--with-items`, Phase 5 passes `--current-memberships`. The script merges
  `(new assignments) ∪ (current memberships in orphan lists)` so nothing
  outside the active taxonomy is touched. If the user explicitly wants to
  wipe a repo's prior memberships, drop the flag (the script will warn,
  making this intentional).
- Keep `.gh-stars-workspace/` around after completion — it's useful for
  re-runs and debugging.

## Troubleshooting

- `GraphQL errors: ... requires authentication` →
  `gh auth refresh -h github.com -s user`
- `repository not found` during apply → private or renamed; skip and report
  at end.
- Rate limit hit → wait an hour or raise `--sleep`.
- `scripts/ not found under ...` from the resolver → either `cd` into the
  repo clone, or export `GH_STARS_CLASSIFIER_ROOT=/absolute/path`.
