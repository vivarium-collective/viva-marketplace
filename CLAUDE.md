# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

`viva-marketplace` is the **ecosystem ledger** for the vivarium /
process-bigraph workbench. It is a small Python package with three
**generated** data files, a shared scanner module, and a handful of scripts —
there is no application code beyond that.

| File | What it is |
|---|---|
| `viva_marketplace/modules.json` | The registry of ecosystem repos (`name`, `source`, `ref`, `package`, `homepage`, `description`, `tags`). **Generated** by `discover_modules()` in `scripts/build_ecosystem_index.py`: every build re-queries the GitHub search API for every public, non-archived `vivarium-collective` repo carrying the `viva-marketplace` topic and overwrites this file with the result. **Not hand-edited** — a repo joins by adding the topic (`gh repo edit <repo> --add-topic viva-marketplace`), not by a PR to this file. |
| `viva_marketplace/ecosystem-index.json` | The aggregated artifact index — every repo's processes/steps/composites/studies/investigations, plus a per-repo reproducibility `attestation` score. **Generated**; rebuilt by CI and overwritten on every build. |
| `viva_marketplace/composability-graph.json` | **Experimental** — a best-effort cross-repo port-compatibility graph derived from the same scan. **Generated**; not a verified wiring guarantee, and not yet consumed by any downstream repo. |

All three are schema-validated against `viva_marketplace/schemas/*.schema.json`
and published to `gh-pages` for same-origin HTTP fetch by any deployed
workbench:

```
https://vivarium-collective.github.io/viva-marketplace/modules.json
https://vivarium-collective.github.io/viva-marketplace/ecosystem-index.json
https://vivarium-collective.github.io/viva-marketplace/composability-graph.json
```

Consumers (`viva-superpowers`, `vivarium-workbench`) read all three via
`viva_marketplace.load_modules()` / `load_ecosystem_index()` /
`load_composability_graph()` (`viva_marketplace/__init__.py`) — the on-disk
location and file shape are implementation details behind that API.

## Commands

```bash
# Rebuild everything locally (needs git + PyYAML + jsonschema)
pip install -e ".[dev]"
export GITHUB_TOKEN=$(gh auth token)                          # discovery authenticates the search API
python scripts/build_ecosystem_index.py --jobs 8               # discover + clone/scan all -> index + graph
python scripts/build_ecosystem_index.py --no-discover          # skip topic discovery; use committed modules.json (offline)
python scripts/build_ecosystem_index.py --only viva-biofilm    # subset (debug)

# Schema-validate modules.json (pure stdlib + jsonschema; the PR gate)
python scripts/validate_modules.py

# Drift check before publishing a repo to the marketplace — run from that
# repo's own checkout, reuses the exact scanner the nightly build uses
viva-marketplace-selfcheck <your-registry-name> --path .
# or: python -m viva_marketplace.selfcheck <your-registry-name> --path .

# Tests / lint / types
pytest -v          # unit tests + contract tests (pin the shape vivarium-workbench depends on)
ruff check .
mypy
```

## How the index builder works

`scripts/build_ecosystem_index.py` first calls `discover_modules()` to query
the GitHub search API for `org:vivarium-collective topic:viva-marketplace
archived:false`, and rewrites `modules.json` from that result (falls back to
the committed file if discovery fails or `--no-discover` is passed — the
build never breaks on API errors). It then reads `modules.json` and, for each
entry, **shallow-clones the repo into a tempdir and statically scans its
source** via `viva_marketplace/scanner.py` — no published workbench dashboard
is required, so coverage is complete regardless of what a given repo
publishes. `scanner.py` is shared between the nightly builder and
`viva_marketplace.selfcheck` (a maintainer scanning their own local checkout
before publishing), so "what the ledger sees" and "what selfcheck sees" can
never diverge:

- **composites** — `@composite_generator(name=…, description=…)` call sites
  found via AST, plus any `*.composite.yaml` files (parsed with PyYAML if
  available).
- **processes / steps** — top-level `ast.ClassDef`s whose base class name ends
  in `Process` or `Step`; described by a `description = "..."` class attribute
  if present, else the first line of the docstring. Classes literally named
  `Process`/`Step` are skipped (base classes, not implementations). A
  best-effort `ports` dict (`{"inputs": {...}, "outputs": {...}}`) is recorded
  when `inputs()`/`outputs()` resolve to a literal `return {...}` — most real
  implementations compute ports from `self.config` and are simply omitted,
  not scored as absent.
- **studies** — `**/studies/*/study.yaml` (name + objective/purpose/title).
- **investigations** — `**/investigations/*/investigation.yaml` (name + title).
- **attestation** — a static, mechanically-verifiable reproducibility/FAIR-style
  score computed in the same pass (`scanner.attest()`): pinned commit ref
  (weight 0.25 — currently **structurally unreachable**, since topic
  discovery always sets `ref` to the repo's default branch; excluded from the
  weighted average rather than scored 0 for the whole registry), lockfile /
  license / citation presence, `workspace.yaml` `schema_version`, and study
  `acceptance_criteria`/`baseline` coverage (excluded, not zeroed, for repos
  with no studies). A heuristic signal, not a certification — see
  `README.md#reproducibility-attestation` for the exact weights and rationale.

Repos that fail to clone are still listed in the output with `cloned: false`
and empty artifact lists, rather than being dropped — the index is meant to
enumerate the full registry, not just what happened to be reachable on a given
run. Clone+scan runs concurrently across repos (`--jobs`, thread pool —
I/O-bound) but output order always matches `modules.json` input order, so the
index doesn't reorder on every run.

After scanning, `viva_marketplace/composability.py` builds the experimental
composability graph from whatever `ports` were statically extracted: it
matches producer output types to consumer input types by exact string
equality across independently-authored repos, tagging matches on
process-bigraph's own generic/primitive types (`float`, `string`, `map`, …)
as `generic_type` so the noisy total and the trustworthy
`n_cross_repo_specific_type_edges` count are reported separately. Not a
verified wiring guarantee — always confirm by actually composing.

## CI

- **`.github/workflows/validate.yml`** — PR gate. Runs on any PR touching
  `modules.json`, its schema, or the validator script; runs
  `scripts/validate_modules.py`. A sanity check on the (topic-discovered, not
  hand-edited) registry — catches a bad manual fix or schema regression before
  merge, not a membership review.
- **`.github/workflows/test.yml`** — pytest + ruff + mypy on any change to the
  package, scripts, or tests.
- **`.github/workflows/build-index.yml`** — runs daily (cron) and on pushes to
  `main` touching `modules.json`, `scanner.py`, `composability.py`, or the
  builder script. Discovers the registry from the `viva-marketplace` GitHub
  topic, refreshes `modules.json`, rebuilds `ecosystem-index.json` +
  `composability-graph.json`, schema-validates all three, commits them back to
  `main` with `[skip ci]`, then publishes all three to `gh-pages`.
- **`.github/workflows/verify-publish.yml`** — post-publish smoke test:
  fetches the **live** `gh-pages` JSON (not the local build output) and
  schema-validates it, catching publish-lag/staleness the build job's own exit
  code can't see.

## Contribution flow (see CONTRIBUTING.md for the full version)

**Publishing a repo no longer touches this repo at all.** Add the
`viva-marketplace` GitHub topic to your public, non-archived repo
(`gh repo edit vivarium-collective/<repo> --add-topic viva-marketplace`) —
the next nightly build (or a manual `workflow_dispatch`) discovers it,
refreshes `modules.json`, and clones + scans its source into
`ecosystem-index.json` automatically. No PR to `modules.json` needed or
accepted. Your listed `description`/`tags` come straight from your repo's
GitHub description/topics — edit them on GitHub, not here.

Removing a repo: drop the topic (or archive / make it private) — it falls out
of the registry on the next build.

All three generated files (`modules.json`, `ecosystem-index.json`,
`composability-graph.json`) are **off-limits to hand-editing** — every build
overwrites them. `modules.json` is still schema-validated on PRs as a sanity
check on the discovery output, not as a review gate for hand edits.

Before publishing, run `viva-marketplace-selfcheck <name> --path .` from your
own repo's checkout — informational only, never writes anything, never fails
a build.
