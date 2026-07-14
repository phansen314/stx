# stx integration test suites

Two black-box suites drive a fresh temp-DB daemon (isolated `XDG_STATE_HOME` + free port).
They share the launch/assert/pretty harness in `harness.py`.

| Suite | Transport | Covers | Run |
|---|---|---|---|
| `dev_sim.py` | raw HTTP (`requests`) | the wire contract — serialization, routing, malformed bodies, `VersionConflict`, every rejection path | `python scripts/dev_sim.py` |
| `clisim/` | the real CLI (`python -m cli`) | the CLI surface + daemon semantics *through* the CLI — arg validation, name/id resolution, `_retry_conflict`, `done`→terminal, error rendering | `python scripts/clisim/run.py` |

Both accept `--base-url URL` (attach instead of launch), `--no-build`, `--keep`.
`clisim/run.py` also takes `--only <name>[,<name>]` (scenarios: lifecycle, frontier, edges, archive, coherence).

The CLI suite prints the coverage boundaries it deliberately does **not** test (they belong to
the HTTP suite): malformed bodies, `VersionConflict` (masked by the CLI's retry), and client
methods with no CLI command.

Prereqs: `pip install -r scripts/requirements.txt` and a built daemon (`./gradlew installDist`,
done automatically on first launch).
