# stx CLI

A thin, **stateless** command layer over the stx daemon — for agents and humans. Built on the
shared `stxc` client (same wire contract as the TUI and `scripts/dev_sim.py`).

## Install / run

The daemon must be running (`./gradlew run`, listens on `127.0.0.1:8420`).

```bash
./bin/stx ls                       # from the repo root
# or, from anywhere:
PYTHONPATH=/path/to/stx-v3 python3 -m cli ls
# optional: put it on PATH
ln -s "$PWD/bin/stx" ~/.local/bin/stx
```

Daemon location: `--base-url` flag or `STX_URL` env (default `http://127.0.0.1:8420`).

## Stateless by design — always pass `-w`

There is **no stored "current workspace."** Every workspace-scoped command takes `-w <name|id>`
explicitly. This is intentional: multiple agents / concurrent sessions would clobber any shared or
env-based "current context" (and Claude Code's shell state doesn't even persist between calls).
Nothing is written to disk; each command fully self-describes. Workspace-keyed commands without a
resolvable `-w` exit non-zero with a hint. Commands keyed by a global id (`show`, `mv`, `edit`,
`done`, `archive`) don't need `-w`.

Add `--json` to any command for raw output (pipe to `jq`); the default is compact text.

## Command reference

See the table and recipes in [`.claude/skills/stx/SKILL.md`](../.claude/skills/stx/SKILL.md) — it's
the single source for the command list. In short:

- **Orient:** `ls`, `tree -w <ws>`, `next -w <ws> [-t <track>]`, `show <id>`
- **Tasks:** `add`, `mv <id> <status>`, `edit`, `done`, `block`, `relate`, `archive`
- **Containers/registries:** `ws new`, `track new`, `segment new`, `status …`, `kind …`, `transition`

Optimistic-lock versions are handled automatically by `mv`/`edit`/`done` (read-modify-write with one
retry on conflict). Illegal status moves print the legal targets.
