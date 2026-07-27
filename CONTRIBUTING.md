# Contributing to viva-marketplace

viva-marketplace is the **ecosystem ledger** for the vivarium / process-bigraph
workbench. It has exactly one thing you edit by hand — the **registry of repos**,
[`viva_marketplace/modules.json`](viva_marketplace/modules.json). Everything else
(`ecosystem-index.json`) is machine-generated.

Changes go through **pull requests** — lightweight, but reviewed, so the ledger
stays trustworthy. A PR touching `modules.json` is validated by CI
([`validate.yml`](.github/workflows/validate.yml) → `scripts/validate_modules.py`)
and then merged by a maintainer.

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

- **`modules.json` only** is human-edited. `ecosystem-index.json` is generated —
  don't hand-edit it (your change will be overwritten on the next build).
- **One repo per entry; unique `name`.** The validator rejects duplicates,
  missing `name`/`source`, and non-GitHub sources.
- **PRs, not direct pushes.** Keep the ledger reviewable.

## Rebuild the index locally

```bash
pip install pyyaml
python scripts/build_ecosystem_index.py                 # all repos
python scripts/build_ecosystem_index.py --only pbg-yourthing   # just yours
python scripts/validate_modules.py                      # run the PR gate locally
```
