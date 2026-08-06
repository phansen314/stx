#!/usr/bin/env bash
# smoke-go.sh — exercise the Go stx CLI end to end (NOT unit tests; just runs the commands).
#
# All 28 commands: ls, tree, next, show, blockers, claims, add, edit, mv, refile, done, claim,
# release, block, relate, unblock, unrelate, relate-kinds, meta, graph, archive, ws, track, segment,
# status, kind, transition, version (+ --json, errors), including the move/rename verbs (refile,
# segment edit, status edit/order, kind rename) and the agent lease. Creates a throwaway workspace
# and archives it at the end.
#
#   bash scripts/smoke-go.sh
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GO="$ROOT/bin/stx-go"
W="go-smoke-$$"          # unique per run

hr()   { printf '\n══ %s ══\n' "$*"; }
g()    { printf '$ stx %s\n' "$*"; "$GO" "$@"; printf '  [exit %s]\n' "$?"; }
gid()  { "$GO" "$@" --json | jq -r .id; }                # run a Go command, return the new id
addid(){ "$GO" add "$1" "${@:2}" --json | jq -r .id; }

command -v jq >/dev/null || { echo "need jq"; exit 1; }
# exit 1 is "no workspaces yet" (grep convention), not a failure — only 2 means trouble
"$GO" ls >/dev/null 2>&1; [ $? -le 1 ] || { echo "daemon unreachable — is it running?"; exit 1; }

hr "0. scaffold a workspace — pure Go (ws / track / segment)"
WID=$(gid ws new "$W")                           # capture id — archive needs it, not the name
# safety net: archive the throwaway workspace even if the run is interrupted (e.g. xclip SIGPIPE)
cleanup() { [ -n "${WID:-}" ] && "$GO" archive workspace "$WID" --yes >/dev/null 2>&1; }
trap cleanup EXIT
g track new build -w "$W" --desc "the build track"
SEG=$(gid segment new api -w "$W" -t build)
echo "workspace=$W (#$WID)  segment(api)=$SEG"

hr "0a. version — client build, plus the daemon's schema/seq"
g version
g track edit build -w "$W" --desc "the build track, renamed"

hr "0b. admin — status / kind / transition (Go)"
g status new Blocked -w "$W" --order 5           # add a status to the seeded kanban
g transition -w "$W" --from Backlog --to Blocked # ...and a legal move into it
g kind new bug -w "$W"

hr "1. add — create tasks with Go"
A1=$(addid "design schema"   -w "$W" -t build -p 2); echo "  design schema  → #$A1"
A2=$(addid "write migration" -w "$W" -t build       ); echo "  write migration → #$A2"
A3=$(addid "ship it"         -w "$W" -t build -p 1  ); echo "  ship it        → #$A3"
A4=$(addid "GET /users"      -w "$W" -s "$SEG"       ); echo "  GET /users     → #$A4 (in api segment)"
printf '\ntext form of one add (with the bug kind from §0b):\n'; g add "extra task" -w "$W" -t build --kind bug

hr "2. edit — title / description / priority (CAS)"
g edit "$A1" --desc "the core v3 schema" --priority 3
g edit "$A2" --title "write the migration"

hr "3. edges — block / relate / relate-kinds / unblock (Go)"
g block "$A2" --on "$A1"                       # migration blocked by schema → drops out of next
g relate "$A3" --to "$A1" --kind relates_to
g relate "$A4" --to "$A3" --kind spawns
g relate-kinds -w "$W"
printf '\ndemonstrate unblock then re-block:\n'
g unblock "$A2" --on "$A1"
g block "$A2" --on "$A1"

hr "4. reads — tree"
g tree -w "$W"
printf '\n--json:\n'; g tree -w "$W" --json

hr "5. reads — next (frontier; #$A2 blocked by #$A1 should be absent)"
g next -w "$W"
printf '\nscoped -t build:\n'; g next -w "$W" -t build --limit 2
printf '\n--json:\n';          g next -w "$W" --json

hr "5b. reads — next --kind (the registry filter) and -s (segment subtree)"
g edit "$A1" --kind bug                        # kinds are editable now, not set-once at add
printf '\nfiltered to kind bug:\n'; g next -w "$W" --kind bug
printf '\nscoped to the api segment subtree:\n'; g next -w "$W" -s "$SEG"
printf '\nunknown kind (should error and list the live kinds):\n'; g next -w "$W" --kind no-such-kind
g edit "$A1" --no-kind                         # …and clearable

hr "6. reads — show (task detail + edges)"
g show "$A1"
printf '\n--json:\n'; g show "$A1" --json

hr "6a. blockers — the inverse of next (#$A2 is blocked by #$A1)"
g blockers "$A2"
printf '\n--depth 1 (direct blockers only):\n'; g blockers "$A2" --depth 1
printf '\n--json:\n';                           g blockers "$A2" --json
printf '\n#%s is in next, so nothing blocks it (exit 1):\n' "$A1"; g blockers "$A1"
printf '\n-q prints the BLOCKER ids, so the path is pipeable:\n'; "$GO" blockers "$A2" -q

hr "6b. meta — set / ls / get / del (Go RMW over the metadata blob)"
g meta set --task "$A1" area schema           # bareword → JSON string
g meta set --task "$A1" points 5              # number
g meta set --task "$A1" tags '["v3","core"]'  # JSON array
g meta ls  --task "$A1"
printf '\n--json:\n'; g meta ls --task "$A1" --json
g meta get --task "$A1" area
g meta del --task "$A1" points
g meta set -w "$W" owner paul                 # metadata on the workspace itself
g meta ls  -w "$W"

hr "6c. graph — Graphviz DOT + json (pipe DOT to 'dot -Tsvg -o g.svg' for a picture)"
g graph -w "$W"
printf '\n--json:\n'; g graph -w "$W" --json

hr "7. status flow — mv through the kanban, then done"
g mv "$A3" Implementation
g mv "$A3" Review
g done "$A3"
g show "$A3"
printf '\nuse the custom Backlog→Blocked transition created in §0b:\n'
g mv "$A1" Blocked

hr '7b. unix composition — -q ids, `-` stdin, exit codes'
printf '$ stx next -w %s -q            (ids only, one per line)\n' "$W"; "$GO" next -w "$W" -q
printf '\n$ stx next -w %s -q | stx show -   (pipe the frontier into another command)\n' "$W"
"$GO" next -w "$W" -q | "$GO" show -
printf '\n$ stx add "from stdin" --desc -   (description read from stdin)\n'
echo "written by the smoke script" | g add "from stdin" -w "$W" -t build --desc -
printf '\nexit codes — 0 results / 1 empty / 2 error:\n'
"$GO" next -w "$W" -q >/dev/null;                    printf '  next (has ready tasks) → %s\n' "$?"
"$GO" meta ls --task "$A4" >/dev/null 2>&1;          printf '  meta ls (no keys set)  → %s\n' "$?"
"$GO" next -w "$W" -t no-such-track >/dev/null 2>&1; printf '  next (bad track)       → %s\n' "$?"

hr "7c. refile — a task moves through the FILING tree (mv's other axis)"
g track new triage -w "$W" --desc "the refile destination"
printf '\ncross-track, to the destination track'"'"'s root segment:\n'
g refile "$A4" -w "$W" -t triage
g tree -w "$W"
printf '\nand back into the api segment, named (not by id):\n'
g refile "$A4" -w "$W" -t build -s api
printf '\nthe blocks edge survives a refile — #%s is still blocked by #%s:\n' "$A2" "$A1"
g blockers "$A2"
printf '\nbatch: pipe a whole frontier into another track (-q ids in, -q ids out):\n'
"$GO" next -w "$W" -t build -q | "$GO" refile - -w "$W" -t triage -q
g tree -w "$W"

hr "7d. container / registry edits — nothing is filed once and stuck"
g segment new v2 -w "$W" -t build
g segment edit v2 -w "$W" -t build --name v2-api --under api   # rename + reparent in one call
g tree -w "$W"
printf '\na parent inside the moved segment'"'"'s own subtree is a cycle (exit 2):\n'
g segment edit api -w "$W" -t build --under v2-api
printf '\nthe root segment has no parent to change (exit 2):\n'
g segment edit "(root)" -w "$W" -t build --under api
printf '\ncross-track destinations are not nameable from -t build (exit 2):\n'
g segment edit api -w "$W" -t triage --name nope
printf '\nstatus rename keeps the id, so #%s stays where it is:\n' "$A1"
g status edit Blocked -w "$W" --name Waiting
g show "$A1"
printf '\nreorder the kanban (listed first, the rest keep their order behind them):\n'
g status order Waiting Backlog -w "$W"
g status ls -w "$W"
printf '\nrenaming onto another live status, any casing, is a duplicate (exit 2):\n'
g status edit Waiting -w "$W" --name "  backlog "
printf '\nkind rename — typed tasks keep their kind (same id):\n'
g edit "$A1" --kind bug
g kind new chore -w "$W"
g kind rename bug defect -w "$W"
g next -w "$W" --kind defect
printf '\nand a case-insensitive clash is refused (exit 2):\n'
g kind rename defect "  CHORE " -w "$W"

hr "7e. agent leases — claim / renew / release / expiry (no sweeper)"
g claim "$A1" --as agent-1 --ttl 60s
printf '\nthe frontier hides it from everyone else…\n'; g next -w "$W"
printf '\n…but not from its holder:\n';                 g next -w "$W" --as agent-1
printf '\nwho holds what:\n';                            g claims -w "$W"
printf '\na second agent is refused, and told who has it (exit 2):\n'
g claim "$A1" --as agent-2
printf '\nre-claiming your own task RENEWS it (no separate heartbeat verb):\n'
g claim "$A1" --as agent-1 --ttl 3600s
printf '\nreleasing someone else'"'"'s lease is refused (exit 2):\n'; g release "$A1" --as agent-2
printf '\nthe holder releases, and it returns to the frontier:\n'
g release "$A1" --as agent-1
g next -w "$W" -q
printf '\nexpiry needs no sweeper — a 2s lease, then wait:\n'
"$GO" claim "$A4" --as ghost --ttl 2s -q >/dev/null && echo "  #$A4 leased by ghost"
printf '  frontier now: '; "$GO" next -w "$W" -q | tr '\n' ' '; echo
sleep 3
printf '  after the TTL: '; "$GO" next -w "$W" -q | tr '\n' ' '; echo "  <- #$A4 is back"
g claims -w "$W"
printf '\nthe agent loop — claim the frontier, work it, release it:\n'
"$GO" next -w "$W" --claim --as loop-1 --ttl 60s --limit 2 -q | while read -r id; do
    printf '  working #%s\n' "$id"
    "$GO" release "$id" --as loop-1 -q >/dev/null
done

hr "8. error paths (each should print 'error: …' and exit 2)"
g claim "$A1" --as agent-1 --ttl 100ms      # sub-second ttl truncates to 0 — rejected client-side
g claim "$A1"                               # a lease needs a holder
g next -w "$W" --claim                      # --claim without --as
g refile "$A4" -w "$W"                       # refile without a destination track
g refile "$A4" -w "$W" -t build -s no-such-segment
g segment edit api -w "$W" -t build          # nothing to edit
g status edit Backlog -w "$W"                # nothing to edit
g show 99999999                              # NotFound
g mv "$A1" Nonsense                          # unknown status (resolve)
g edit "$A1"                                 # nothing to edit
g add "bad" -w "$W" -t build -s "$SEG"       # both -t and -s
g add "bad" -w no-such-workspace -t build    # unknown workspace
g next                                       # missing -w
g meta ls                                    # no target (need --task or -w)
g meta ls --task "$A1" -w "$W"               # both targets
g archive bogus 1                            # invalid entity type

hr "8b. ws rename — the workspace's own name is editable (CAS)"
g ws rename "$W-renamed" -w "$W"
W="$W-renamed"

hr "9. cleanup — archive the throwaway workspace by id (Go's own archive)"
if "$GO" archive workspace "$WID" --yes; then echo "archived $W (#$WID)"; else echo "CLEANUP FAILED for #$WID"; fi
"$GO" ls
