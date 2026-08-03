# Contributing to viva-marketplace

viva-marketplace is the **ecosystem ledger** for the vivarium / process-bigraph
workbench. All three files are **machine-generated** — you don't hand-edit them:

- `viva_marketplace/modules.json` — the registry of repos, **discovered from
  GitHub topics** (see below).
- `viva_marketplace/ecosystem-index.json` — the aggregated artifact index,
  built by cloning + scanning each discovered repo.
- `viva_marketplace/composability-graph.json` — the experimental cross-repo
  port-compatibility graph, derived from the same scan.

**Before publishing**, run `viva-marketplace-selfcheck <your-name> --path .`
from your repo's checkout — it reuses the exact scanner the nightly build
uses, so you see the same artifact counts the ledger will, plus a heads-up if
your repo's GitHub description/topics leave `description`/`tags` empty. See
[README.md](README.md#selfcheck--drift-check-before-you-publish).

**Want your ref to count as reproducibility-attested?** See
[README.md](README.md#reproducibility-attestation) — pinning currently
requires a discovery-side change (topic discovery sets `ref` to each repo's
default branch), tracked as an open item, not something you can do today by
editing `modules.json` yourself.

## Publish your repository to the marketplace

**Add the `viva-marketplace` GitHub topic to your repo.** That's the whole step:

```bash
gh repo edit vivarium-collective/<your-repo> --add-topic viva-marketplace
```

(Or add it via the repo's GitHub page → About → ⚙ → Topics.) Your repo must be
**public** and not archived.

The nightly builder (and any manual re-run) then discovers every public,
non-archived `vivarium-collective` repo carrying the topic, refreshes
`modules.json` from that set, and **clones your repo and scans its source** — your
composites (`@composite_generator` / `*.composite.yaml`), `Process`/`Step`
subclasses, `studies/<slug>/study.yaml`, and
`investigations/<slug>/investigation.yaml` all appear in `ecosystem-index.json`
automatically. You never hand-write your artifact list.

To make your artifacts discoverable, follow the usual conventions:
`@composite_generator(name=…, description=…)` for composites, `Process`/`Step`
subclasses (with a `description` attribute or docstring) for processes, and the
`studies/`/`investigations/` YAML for those.

## Update your listing

Your `description` and `tags` come straight from your repo's **GitHub description
and topics** — edit them on GitHub and the next build picks them up. The artifact
index refreshes from your repo's source, so just keep your source current.

## Remove your repository

Remove the `viva-marketplace` topic (or archive / make the repo private) — it
drops out of the registry on the next build:

```bash
gh repo edit vivarium-collective/<your-repo> --remove-topic viva-marketplace
```

## Ground rules

- **Membership = the `viva-marketplace` topic on a public, non-archived repo.**
  No hand-maintained list to drift.
- **All three generated files are off-limits to hand-editing** —
  `modules.json`, `ecosystem-index.json`, `composability-graph.json` are all
  overwritten on the next build. `modules.json` is still schema-validated
  (`scripts/validate_modules.py` against
  [`schemas/modules.schema.json`](viva_marketplace/schemas/modules.schema.json))
  as a sanity check on the discovery output, not as a PR gate for hand edits.

## Rebuild locally

```bash
pip install -e ".[dev]"                                        # pyyaml + jsonschema + dev tooling
export GITHUB_TOKEN=$(gh auth token)                            # discovery authenticates the search API
python scripts/build_ecosystem_index.py --jobs 8                # discover + clone/scan all -> index + graph
python scripts/build_ecosystem_index.py --no-discover           # use committed modules.json as-is (offline)
python scripts/build_ecosystem_index.py --only viva-biofilm     # just one repo (debug)
python scripts/validate_modules.py                              # schema-check modules.json
pytest -v                                                        # unit + contract tests
```
