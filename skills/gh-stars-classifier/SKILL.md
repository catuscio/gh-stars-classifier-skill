---
name: gh-stars-classifier
description: Classify the user's GitHub starred repositories into semantic categories and add them to GitHub Lists. Use when the user asks to organize, classify, categorize, or clean up their GitHub stars.
allowed-tools: Bash(gh *) Bash(python3 *) Bash(mkdir *) Read Write Edit
---

# GitHub Stars Classifier — Claude Code entry

The full workflow — 5 phases with **[CONFIRM]** checkpoints, guardrails, and
troubleshooting — lives in `AGENTS.md` at the plugin root. It is a portable
spec shared with Codex CLI, opencode, and Gemini CLI so there is one source
of truth.

**Step 1** — read `${CLAUDE_PLUGIN_ROOT}/AGENTS.md` with the Read tool.

**Step 2** — execute it exactly as written. The root-resolver preamble inside
AGENTS.md auto-detects `CLAUDE_PLUGIN_ROOT`, so no extra env export is needed
when invoked from this plugin.

Do not paraphrase, shortcut, or skip confirmations. The flag combinations
(`--current-memberships`, `--stars-index`, `--progress-file`) each guard
against a specific data-loss class described in the Guardrails section.
