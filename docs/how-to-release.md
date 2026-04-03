# How to Release

Releases are published only when a **GitHub Release** is created — not on every push to main.

## Steps

1. **Update versions** on a feature branch before merging to main:
   - `rocks/ein-agent-worker/rockcraft.yaml` → `version: 'X.Y.Z'`
   - `ein-agent-cli/snap/snapcraft.yaml` → `version: 'X.Y.Z'`
   - `CHANGELOG.md` → add new section

2. **Merge to main** — CI runs build and tests, nothing is published.

3. **Create a GitHub Release** with tag `vX.Y.Z` targeting `main`. This triggers:
   - `release-rock.yaml` → publishes worker ROCK image to GHCR
   - `release-snap.yaml` → publishes CLI snap to Snap Store

Both release workflows verify that the git tag matches the version in the yaml files.
