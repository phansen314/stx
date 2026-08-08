# Installing stx as a Claude Code plugin

The repo doubles as a **Claude Code plugin** so Claude can drive the daemon through skills
instead of you re-explaining the CLI every session. Two skills ship:

| Skill | What it is for |
|-------|----------------|
| `skills/stx/SKILL.md` | the command reference — the full verb surface, pipeline conventions, agent leases |
| `skills/next/SKILL.md` | "what should I work on" — read the frontier, hydrate the top task, offer to start it |

The manifest is [`.claude-plugin/plugin.json`](../.claude-plugin/plugin.json) and the
marketplace that serves it is [`.claude-plugin/marketplace.json`](../.claude-plugin/marketplace.json),
whose single plugin has `"source": "./"` — the repo itself.

## Install

```
/plugin marketplace add ~/code/stx     # once; registers this repo as a marketplace
/plugin install stx@stx
```

Then confirm it resolved — the skill should appear in the session's skill list, and

```
/stx:next
```

should run rather than reporting an unknown command. (Registering the marketplace does **not**
install the plugin. The two are separate steps, and skipping the second is why `/stx:next` never
resolved here between 2026-07-14 and 2026-08-04 despite the marketplace being registered the whole
time.)

## The part that will bite you: an install is a COPY

A directory-source marketplace is *referenced* in place — `known_marketplaces.json` points
`installLocation` straight at `~/code/stx`. The **plugin** is not. On install it is snapshotted into

```
~/.claude/plugins/cache/stx/stx/<version>/
```

and that copy is what Claude loads. **Editing `skills/*/SKILL.md` in the repo changes nothing in a
live session.** The copy is only refreshed when you update the plugin.

Worse, nothing tells you the copy is behind, because the only version marker is the hand-maintained
`version` field in `plugin.json`. The precedent is sitting on this machine: `codenav` was installed
2026-04-06, and its cached `plugin.json` still differs from its repo in description, author and
keywords — while both sides read `"version": "0.1.0"`. Content diverged; the version said nothing
had.

### So: the version must move for an update to do anything

```jsonc
// .claude-plugin/plugin.json
"version": "3.1.0"      // ← must change, or the update is a no-op
```

```
/plugin update stx@stx
```

**This collides with the release rule, deliberately.** [`RELEASING.md`](../RELEASING.md) requires
`plugin.json` and `build.gradle.kts` to move **together**, so `plugin.json` tracks the *daemon*
version. A skills-only edit therefore has no version of its own, and in practice it reaches sessions
at the next release — which is fine while releases are frequent, and is the current rule.

If that ever becomes too slow, the fix is to decouple on purpose (let `plugin.json` advance its
patch digit for skills-only changes) rather than to bump it quietly and leave the two manifests
disagreeing about what version stx is. Until then: **a skills edit is not live until the next
version bump**, and `/plugin update` before that bump does nothing at all.

### Checking whether the installed copy is stale

```bash
diff -r ~/.claude/plugins/cache/stx/stx/*/skills/ ~/code/stx/skills/
```

Empty output means the running plugin matches the working tree. Any output means a session is
loading skills you have already changed.

## Uninstall

```
/plugin uninstall stx@stx
```

The cache copy goes; the repo is untouched, since the marketplace only ever pointed at it.

## Why this keeps happening

stx has now produced three artifacts that something else installed a *copy* of, where nothing
noticed the copy went stale:

- a jar (`installDist` rewriting it under a live daemon — fixed by `make deploy`),
- a systemd unit (an installed copy drifting from the template — fixed by symlinking it),
- this plugin (a cache snapshot drifting from `skills/`).

The plugin is the one case where symlinking is *not* the fix: the cache is managed by Claude Code
and an update would overwrite it. Here the discipline has to be the version bump.
