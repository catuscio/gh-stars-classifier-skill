# GitHub Stars Classifier — Gemini CLI entry

Gemini CLI reads this file automatically. The actual workflow is defined in
`AGENTS.md` and imported below — one source of truth across every supported
CLI agent.

@AGENTS.md

## Gemini-specific setup

Before invoking any bash command from the imported workflow, make sure the
root resolver can find the `scripts/` directory. The simplest path is to
`cd` into the clone first:

```bash
cd /path/to/gh-stars-classifier-skill
gemini          # opens with this directory as the working root
```

or export the variable explicitly:

```bash
export GH_STARS_CLASSIFIER_ROOT=/path/to/gh-stars-classifier-skill
```

Then ask Gemini to "organize my GitHub stars." It will execute the five-phase
workflow above, pausing at each **[CONFIRM]** checkpoint.
