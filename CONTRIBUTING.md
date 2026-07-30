# Contributing to viva-marketplace

viva-marketplace is the **ecosystem ledger** for the vivarium / process-bigraph
workbench. It has exactly one thing you edit by hand — the **registry of repos**,
[`viva_marketplace/modules.json`](viva_marketplace/modules.json). Everything else
(`ecosystem-index.json`, `composability-graph.json`) is machine-generated.

Changes go through **pull requests** — lightweight, but reviewed, so the ledger
stays trustworthy. A PR touching `modules.json` is validated by CI
([`validate.yml`](.github/workflows/validate.yml) → `scripts/validate_modules.py`,
which checks it against [`schemas/modules.schema.json`](viva_marketplace/schemas/modules.schema.json))
and then merged by a maintainer.

**Before opening a PR**, run `viva-marketplace-selfcheck <your-name> --path .`
from your repo's checkout — it reuses the exact scanner the nightly build uses,
so you'll see the same counts CI will see, plus a heads-up if your entry is
missing a `description`/`tags`. See [README.md](README.md#selfcheck--drift-check-before-you-open-a-registry-pr).

**Want your ref to count as reproducibility-attested?** Pin `ref` to a full
40-character commit SHA rather than a branch name — see
[README.md](README.md#reproducibility-attestation) for the full scoring.

## Add your repository

1. Open a PR that appends one object to the list in
   `viva_marketplace/modules.json`:

   ```json
   {
     "name": "pbg-yourthing",
     "display_name": "viva-yourthing",
     "description": "One line on what this repo provides (processes/composites).",
     "source": "https://github.com/vivarium-collective/pbg-yourthing.git",
     "ref": "main",
     "package": "pbg_yourthing",
     "homepage": "https://github.com/vivarium-collective/pbg-yourthing",
     "tags": ["your", "tags"]
   }
   ```

   Required: **`name`** (unique) and **`source`** (a GitHub URL). Everything else
   is optional but recommended.

2. CI validates the file; a maintainer reviews and merges.

3. On merge (and every night) the builder **clones your repo and scans its
   source** — your composites (`@composite_generator` / `*.composite.yaml`),
   processes/steps, studies, and investigations appear in `ecosystem-index.json`
   automatically. You do **not** hand-write your artifact list.

To make your artifacts discoverable, follow the usual conventions in your repo:
`@composite_generator(name=…, description=…)` for composites, `Process`/`Step`
subclasses (with a `description` attribute or docstring) for processes, and
`studies/<slug>/study.yaml` / `investigations/<slug>/investigation.yaml` for
studies/investigations.

## Update your listing

Open a PR editing your entry — e.g. change the `description`, `tags`, or pin a
different `ref`. The **artifact index refreshes itself** from your repo's source
on the nightly build, so you never edit `ecosystem-index.json`; just keep your
repo's source current.

## Remove your repository

Open a PR removing your entry from `modules.json`.

## Ground rules

- **`modules.json` only** is human-edited. `ecosystem-index.json` and
  `composability-graph.json` are generated — don't hand-edit them (your
  change will be overwritten on the next build).
- **One repo per entry; unique `name`.** The validator rejects duplicates,
  missing `name`/`source`, and non-GitHub sources (schema in
  [`schemas/modules.schema.json`](viva_marketplace/schemas/modules.schema.json)).
- **PRs, not direct pushes.** Keep the ledger reviewable.

## Rebuild the index locally

```bash
pip install -e ".[dev]"
python scripts/build_ecosystem_index.py                       # all repos
python scripts/build_ecosystem_index.py --only pbg-yourthing  # just yours
python scripts/validate_modules.py                            # run the PR gate locally
pytest -v                                                      # unit + contract tests
```
