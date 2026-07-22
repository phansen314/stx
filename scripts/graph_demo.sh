#!/usr/bin/env bash
# Seed an ISOLATED stx "test db" with a rich graph — two tracks, nested segments, tasks spread
# across them, a blocks DAG, and relations — then render it with `stx graph -o` (SVG + PNG, LR and
# --vertical). Exercises the graphviz scaffolding without touching your real daemon/db.
#
#   scripts/graph_demo.sh            # spins a throwaway daemon on port 8499, renders to build/graph-demo
#   OUTDIR=/tmp/g PORT=8501 scripts/graph_demo.sh
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
STX="$ROOT/bin/stx"

# The daemon is CLI-agnostic; reuse the installed binary from the main checkout if this worktree
# hasn't built one. Build it with `./gradlew installDist` if neither exists.
DAEMON="$ROOT/build/install/stx/bin/stx"
[ -x "$DAEMON" ] || DAEMON="/home/superuser/code/stx/build/install/stx/bin/stx"
if [ ! -x "$DAEMON" ]; then
  echo "no daemon binary — run ./gradlew installDist first" >&2
  exit 1
fi

PORT="${PORT:-8499}"
STATE="$(mktemp -d)"
OUTDIR="${OUTDIR:-$ROOT/build/graph-demo}"
mkdir -p "$OUTDIR"
export STX_URL="http://127.0.0.1:$PORT"

echo "test db: $STATE/stx/stx.db   (daemon on :$PORT)"
XDG_STATE_HOME="$STATE" STX_PORT="$PORT" "$DAEMON" >"$STATE/daemon.log" 2>&1 &
DPID=$!
trap 'kill "$DPID" 2>/dev/null || true' EXIT

for _ in $(seq 1 50); do
  curl -sf "$STX_URL/health" >/dev/null 2>&1 && break
  sleep 0.2
done
curl -sf "$STX_URL/health" >/dev/null || { echo "daemon did not come up; see $STATE/daemon.log" >&2; exit 1; }

id() { python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])'; }

W=graphdemo
"$STX" ws new "$W" >/dev/null
"$STX" track new auth    -w "$W" >/dev/null
"$STX" track new billing -w "$W" >/dev/null

# nested segments (segment new returns the created segment as JSON)
login=$(     "$STX" segment new login     -w "$W" -t auth    --json | id)
oauth=$(     "$STX" segment new oauth      -w "$W" -t auth    --json | id)
invoicing=$( "$STX" segment new invoicing  -w "$W" -t billing --json | id)

# tasks: -t <track> files under the track's root segment; -s <seg> files under a segment
t1=$("$STX" add "design auth schema" -w "$W" -t auth        --json | id)
t2=$("$STX" add "login form"         -w "$W" -s "$login"    --json | id)
t3=$("$STX" add "session cookies"    -w "$W" -s "$login"    --json | id)
t4=$("$STX" add "google oauth"       -w "$W" -s "$oauth"    --json | id)
t5=$("$STX" add "token refresh"      -w "$W" -s "$oauth"    --json | id)
t6=$("$STX" add "billing model"      -w "$W" -t billing     --json | id)
t7=$("$STX" add "invoice PDF"        -w "$W" -s "$invoicing" --json | id)
t8=$("$STX" add "email invoice"      -w "$W" -s "$invoicing" --json | id)

# blocks DAG: `block X --on Y` == "X is blocked by Y" == edge Y→X
"$STX" block "$t2" --on "$t1" >/dev/null
"$STX" block "$t4" --on "$t1" >/dev/null
"$STX" block "$t3" --on "$t2" >/dev/null
"$STX" block "$t5" --on "$t4" >/dev/null
"$STX" block "$t7" --on "$t6" >/dev/null
"$STX" block "$t8" --on "$t7" >/dev/null
# relations (decorative, dashed in the graph)
"$STX" relate "$t5" --to "$t3" --kind relates_to >/dev/null
"$STX" relate "$t8" --to "$t6" --kind spawns     >/dev/null
# finish one task so the graph shows a filled terminal node (best-effort — needs a legal path)
"$STX" done "$t1" >/dev/null 2>&1 || true

echo "--- DOT (stdout) ---"
"$STX" graph -w "$W"
echo "--- render ---"
"$STX" graph -w "$W"            -o "$OUTDIR/graph.svg"
"$STX" graph -w "$W"            -o "$OUTDIR/graph.png"
"$STX" graph -w "$W" --vertical -o "$OUTDIR/graph-vertical.svg"
"$STX" graph -w "$W" --blocks-only --vertical -o "$OUTDIR/graph-blocks.png"
echo "--- output ---"
ls -la "$OUTDIR"
