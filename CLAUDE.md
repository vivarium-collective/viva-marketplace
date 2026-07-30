# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

`viva-marketplace` is the **ecosystem ledger** for the vivarium /
process-bigraph workbench. It is a small, mostly-static Python package with
two data files and two scripts — there is no application code beyond that.

| File | What it is |
|---|---|
| `viva_marketplace/modules.json` | The **hand-edited** registry of ecosystem repos (`name`, `source`, `description`, `tags`, …). The single source of truth for *what repos exist*. |
| `viva_marketplace/ecosystem-index.json` | The **machine-generated** aggregated artifact index — every repo's processes/steps/composites/studies/investigations. Never hand-edit; rebuilt by CI and overwritten on every build. |

Consumers (`viva-superpowers`, `vivarium-workbench`) read both files via
`viva_marketplace.load_modules()` / `viva_marketplace.load_ecosystem_index()`
(`viva_marketplace/__init__.py`), and the same two files are published to
`gh-pages` for same-origin HTTP fetch by any deployed workbench:

```
https://vivarium-collective.github.io/viva-marketplace/modules.json
https://vivarium-collective.github.io/viva-marketplace/ecosystem-index.json
```

## Commands

```bash
# Rebuild the artifact index locally (needs git + PyYAML)
pip install pyyaml
python scripts/build_ecosystem_index.py                        # all repos
python scripts/build_ecosystem_index.py --only pbg-amici,Viva-munk   # subset (debug)

# Run the registry PR-gate validator locally (pure stdlib)
python scripts/validate_modules.py
```

There is no test suite, lint config, or build step beyond the wheel packaging
in `pyproject.toml` (hatchling).

## How the index builder works

`scripts/build_ecosystem_index.py` reads `modules.json` and, for each entry,
**shallow-clones the repo into a tempdir and statically scans its source** —
no published workbench dashboard is required, so coverage is complete
regardless of what a given repo publishes:

- **composites** — `@composite_generator(name=…, description=…)` call sites
  found via AST, plus any `*.composite.yaml` files (parsed with PyYAML if
  available).
- **processes / steps** — top-level `ast.ClassDef`s whose base class name ends
  in `Process` or `Step`; described by a `description = "..."` class attribute
  if present, else the first line of the docstring. Classes literally named
  `Process`/`Step` are skipped (base classes, not implementations).
- **studies** — `**/studies/*/study.yaml` (name + objective/purpose/title).
- **investigations** — `**/investigations/*/investigation.yaml` (name + title).

Repos that fail to clone are still listed in the output with `cloned: false`
and empty artifact lists, rather than being dropped — the index is meant to
enumerate the full registry, not just what happened to be reachable on a given
run.

## CI

- **`.github/workflows/validate.yml`** — PR gate. Runs on any PR touching
  `modules.json` or the validator script; runs `scripts/validate_modules.py`
  (checks: JSON list of objects, unique non-empty `name`, GitHub `source` URL,
  correct types for optional fields).
- **`.github/workflows/build-index.yml`** — rebuilds `ecosystem-index.json`
  daily (cron) and on any push to `main` touching `modules.json` or the
  builder script. Commits the refreshed index back to `main` with
  `[skip ci]`, then republishes both JSON files to `gh-pages`.

## Contribution flow (see CONTRIBUTING.md for the full version)

Adding/updating/removing a repo is **PR-only** and touches exactly one file:
append/edit/remove an object in `viva_marketplace/modules.json` (required
keys: `name` unique, `source` a GitHub URL). Never hand-edit
`ecosystem-index.json` — it's regenerated from each repo's live source on
merge and nightly, so any manual edit is overwritten on the next build.
