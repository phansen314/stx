# Releasing

Checklist for cutting a new `sticky-notes` release. The version lives in two files that must move together: `pyproject.toml` (the Python package) and `.claude-plugin/plugin.json` (the Claude Code plugin). Missing one silently ships a mismatched release.

## 1. Pre-release checks

- `python -m pytest tests/` — full suite must pass
- `git status` — working tree clean on the release branch
- All user-visible changes since the previous release are reflected in `CHANGELOG.md` under `## [Unreleased]`

## 2. Version bump

Pick the new version per [SemVer](https://semver.org/):

- **Major** (`X.0.0`) — breaking changes to the CLI surface, schema, or TUI keybindings
- **Minor** (`0.X.0`) — new user-visible feature, backwards-compatible
- **Patch** (`0.0.X`) — bugfix-only, no new features

Update both files in a single commit:

- `pyproject.toml` → `version = "X.Y.Z"` under `[project]`
- `.claude-plugin/plugin.json` → `"version": "X.Y.Z"`

## 3. CHANGELOG promotion

In `CHANGELOG.md`:

1. Rename `## [Unreleased]` to `## [X.Y.Z] — YYYY-MM-DD` (today's date)
2. Add a fresh empty `## [Unreleased]` section above it
3. Confirm the new version block has the right subsections (`Added` / `Changed` / `Fixed` / `Removed` / `Deprecated` / `Security` — include only the ones that apply)
4. Add a new link reference at the bottom: `[X.Y.Z]: https://github.com/phansen314/sticky-notes/releases/tag/vX.Y.Z`
5. Update the `[Unreleased]` compare link to point from the new version: `.../compare/vX.Y.Z...HEAD`

## 4. Commit, tag, push

```sh
git commit -m "release vX.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z"
git push && git push --tags
```

## 5. Post-release

- If the release was cut on a feature branch, open (or update) the PR and merge to `main`
- Optional: `gh release create vX.Y.Z --notes-from-tag` to create a GitHub Release object from the tag

## Notes

- **Never retag** a published version. If something is wrong with `vX.Y.Z`, ship `vX.Y.(Z+1)` instead.
- **Never skip hooks** (`--no-verify`) or bypass signing when creating the release commit.
- **Tests must pass before tagging** — a tagged commit is the canonical release artifact, and CI-green history matters for future bisects.
