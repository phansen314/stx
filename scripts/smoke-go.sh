#!/usr/bin/env bash
# smoke-go.sh — exercise the Go stx CLI end to end (NOT unit tests; just runs the commands).
#
# Ported-to-Go commands exercised: ls, tree, next, show, add, edit, mv, done (+ --json, errors).
# Scaffolding uses the Python bin/stx for the commands not yet in Go (ws/track/segment/block).
# Creates a throwaway workspace and archives it at the end.
#
#   bash scripts/smoke-go.sh
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GO="$ROOT/bin/stx-go"
PY="$ROOT/bin/stx"
W="go-smoke-$$"          # unique per run

hr()  { printf '\n══ %s ══\n' "$*"; }
g()   { printf '$ stx %s\n' "$*"; "$GO" "$@"; printf '  [exit %s]\n' "$?"; }
scaf(){ printf '# scaffold: stx %s\n' "$*"; "$PY" "$@" >/dev/null; }
addid(){ "$GO" add "$1" "${@:2}" --json | jq -r .id; }   # create via Go, return id

command -v jq >/dev/null || { echo "need jq"; exit 1; }
"$GO" ls >/dev/null 2>&1 || { echo "daemon unreachable — is it running?"; exit 1; }

hr "0. scaffold a workspace (Python: ws/track/segment not yet in Go)"
WID=$("$PY" ws new "$W" --json | jq -r .id)     # capture id — archive needs it, not the name
scaf track new build -w "$W"
SEG=$("$PY" segment new api -w "$W" -t build --json | jq -r .id)
echo "workspace=$W (#$WID)  segment(api)=$SEG"

hr "1. add — create tasks with Go"
A1=$(addid "design schema"   -w "$W" -t build -p 2); echo "  design schema  → #$A1"
A2=$(addid "write migration" -w "$W" -t build       ); echo "  write migration → #$A2"
A3=$(addid "ship it"         -w "$W" -t build -p 1  ); echo "  ship it        → #$A3"
A4=$(addid "GET /users"      -w "$W" -s "$SEG"       ); echo "  GET /users     → #$A4 (in api segment)"
printf '\ntext form of one add:\n'; g add "extra task" -w "$W" -t build

hr "2. edit — title / description / priority (CAS)"
g edit "$A1" --desc "the core v3 schema" --priority 3
g edit "$A2" --title "write the migration"

hr "3. scaffold a blocks edge (Python) so 'next' has something to filter"
scaf block "$A2" --on "$A1"     # migration blocked by schema → should drop out of next

hr "4. reads — tree"
g tree -w "$W"
printf '\n--json:\n'; g tree -w "$W" --json

hr "5. reads — next (frontier; #$A2 blocked by #$A1 should be absent)"
g next -w "$W"
printf '\nscoped -t build:\n'; g next -w "$W" -t build --limit 2
printf '\n--json:\n';          g next -w "$W" --json

hr "6. reads — show (task detail + edges)"
g show "$A1"
printf '\n--json:\n'; g show "$A1" --json

hr "7. status flow — mv through the kanban, then done"
g mv "$A3" Implementation
g mv "$A3" Review
g done "$A3"
g show "$A3"

hr "8. error paths (each should print 'error: …' and exit 1)"
g show 99999999                              # NotFound
g mv "$A1" Nonsense                          # unknown status (resolve)
g edit "$A1"                                 # nothing to edit
g add "bad" -w "$W" -t build -s "$SEG"       # both -t and -s
g add "bad" -w no-such-workspace -t build    # unknown workspace
g next                                       # missing -w

hr "9. cleanup — archive the throwaway workspace by id (Python)"
if "$PY" archive workspace "$WID" --yes; then echo "archived $W (#$WID)"; else echo "CLEANUP FAILED for #$WID"; fi
"$GO" ls
