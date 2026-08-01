# Contributing to viva-marketplace

viva-marketplace is the **ecosystem ledger** for the vivarium / process-bigraph
workbench. Both files are now **machine-generated** — you don't hand-edit them:

- `viva_marketplace/modules.json` — the registry of repos, **discovered from
  GitHub topics** (see below).
- `viva_marketplace/ecosystem-index.json` — the aggregated artifact index,
  built by cloning + scanning each discovered repo.

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
- Both `modules.json` and `ecosystem-index.json` are generated — don't hand-edit
  them (changes are overwritten on the next build).

## Rebuild locally

```bash
pip install pyyaml
export GITHUB_TOKEN=$(gh auth token)      # discovery authenticates the search API
python scripts/build_ecosystem_index.py               # discover + clone/scan all
python scripts/build_ecosystem_index.py --no-discover # use committed modules.json as-is
python scripts/build_ecosystem_index.py --only viva-biofilm  # just one repo
```
