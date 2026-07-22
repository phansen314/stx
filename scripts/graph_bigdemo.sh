#!/usr/bin/env bash
# Seed an ISOLATED stx db with a larger, realistic DAG (3 tracks, nested segments, ~13 tasks in
# mixed statuses/kinds/priorities, a cross-track blocks DAG and relations) and render it with
# examples/graph.toml. Never touches your real daemon/db.
#
#   scripts/graph_bigdemo.sh          # daemon on :8501, renders to build/graph-bigdemo
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
STX="$ROOT/bin/stx"
STYLE="$ROOT/examples/graph.toml"

DAEMON="$ROOT/build/install/stx/bin/stx"
[ -x "$DAEMON" ] || DAEMON="/home/superuser/code/stx/build/install/stx/bin/stx"
[ -x "$DAEMON" ] || { echo "no daemon binary — run ./gradlew installDist first" >&2; exit 1; }

PORT="${PORT:-8501}"
STATE="$(mktemp -d)"
OUTDIR="${OUTDIR:-$ROOT/build/graph-bigdemo}"
mkdir -p "$OUTDIR"
export STX_URL="http://127.0.0.1:$PORT"

echo "test db: $STATE/stx/stx.db   (daemon on :$PORT)"
XDG_STATE_HOME="$STATE" STX_PORT="$PORT" "$DAEMON" >"$STATE/daemon.log" 2>&1 &
DPID=$!
trap 'kill "$DPID" 2>/dev/null || true' EXIT
for _ in $(seq 1 50); do curl -sf "$STX_URL/health" >/dev/null 2>&1 && break; sleep 0.2; done
curl -sf "$STX_URL/health" >/dev/null || { echo "daemon did not start; see $STATE/daemon.log" >&2; exit 1; }

id() { python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])'; }
# advance a task from Backlog up the default kanban chain to a target status (stepwise, adjacent).
advance() { local t="$1" target="$2" s; for s in Implementation Review Done; do
  "$STX" mv "$t" "$s" >/dev/null 2>&1 || true; [ "$s" = "$target" ] && break; done; }

W=bigdemo
"$STX" ws new "$W" >/dev/null
for k in feature bug chore; do "$STX" kind new "$k" -w "$W" >/dev/null; done
for tr in backend frontend infra; do "$STX" track new "$tr" -w "$W" >/dev/null; done

# nested segments
auth=$( "$STX" segment new auth   -w "$W" -t backend  --json | id)
db=$(   "$STX" segment new db     -w "$W" -t backend  --json | id)
ui=$(   "$STX" segment new ui     -w "$W" -t frontend --json | id)
state=$("$STX" segment new state  -w "$W" -t frontend --json | id)
ci=$(   "$STX" segment new ci     -w "$W" -t infra    --json | id)
deploy=$("$STX" segment new deploy -w "$W" -t infra   --json | id)

# add <title> <track-or-seg-flag> <ref> <kind> <priority>  -> echoes id
add() { "$STX" add "$1" -w "$W" "$2" "$3" --kind "$4" -p "$5" --json | id; }

t1=$( add "design REST schema"  -t backend  feature 5)   # backend root
t2=$( add "JWT middleware"      -s "$auth"  feature 4)
t3=$( add "refresh tokens"      -s "$auth"  feature 3)
t4=$( add "fix login CSRF"      -s "$auth"  bug     8)
t5=$( add "schema migrations"   -s "$db"    chore   4)
t6=$( add "connection pool"     -s "$db"    feature 3)
t7=$( add "login page"          -s "$ui"    feature 4)
t8=$( add "dashboard"           -s "$ui"    feature 2)
t9=$( add "auth store"          -s "$state" feature 3)
t10=$(add "fix cache race"      -s "$state" bug     7)
t11=$(add "test pipeline"       -s "$ci"    chore   3)
t12=$(add "k8s manifests"       -s "$deploy" chore  5)
t13=$(add "blue-green rollout"  -s "$deploy" feature 2)

# blocks DAG (block X --on Y  ==  Y blocks X); several cross-track
"$STX" block "$t2"  --on "$t1"  >/dev/null
"$STX" block "$t5"  --on "$t1"  >/dev/null
"$STX" block "$t7"  --on "$t1"  >/dev/null
"$STX" block "$t3"  --on "$t2"  >/dev/null
"$STX" block "$t4"  --on "$t2"  >/dev/null
"$STX" block "$t6"  --on "$t5"  >/dev/null
"$STX" block "$t9"  --on "$t7"  >/dev/null
"$STX" block "$t9"  --on "$t2"  >/dev/null   # cross-track: backend→frontend
"$STX" block "$t12" --on "$t11" >/dev/null
"$STX" block "$t12" --on "$t6"  >/dev/null   # cross-track: backend→infra
"$STX" block "$t13" --on "$t12" >/dev/null
# relations
"$STX" relate "$t10" --to "$t7"  --kind relates_to >/dev/null
"$STX" relate "$t13" --to "$t8"  --kind spawns     >/dev/null

# spread statuses so the color legend is visible
advance "$t1"  Done
advance "$t5"  Done
advance "$t11" Done
advance "$t2"  Review
advance "$t7"  Implementation
advance "$t4"  Implementation
advance "$t12" Implementation
# the rest stay Backlog

echo "--- render (style: $STYLE) ---"
"$STX" graph -w "$W" --style "$STYLE"                   -o "$OUTDIR/big"          --png
"$STX" graph -w "$W" --style "$STYLE" --cluster track   -o "$OUTDIR/big-track"    --png
"$STX" graph -w "$W" --style "$STYLE" --cluster segment -o "$OUTDIR/big-segment"  --png
"$STX" graph -w "$W" --style "$STYLE" --cluster segment --vertical -o "$OUTDIR/big-segment-v" --svg
ls -la "$OUTDIR"
