#!/usr/bin/env bash
#
# smoke.sh — end-to-end exercise of the stx v3 daemon over its loopback HTTP API.
#
# Stands up a full workspace → track → segment → task graph, drives the frontier
# (`next`) before/after unblocking, adds blocks/relates_to edges, demonstrates the
# structured error envelope, and archives a task. Every request and its pretty JSON
# response are printed so you can read it as a guided tour.
#
# Vocabulary map (the v3 model uses different words than a typical tracker):
#     track   == your "project"  (root-only line of work; carries description/metadata)
#     segment == your "folder"   (pure filing; nests under a track; one auto root per track)
#     task    == the only first-class node (status, kind, priority, edges)
#
# Usage:
#     daemon/scripts/smoke.sh                 # talks to 127.0.0.1:8473
#     STX_PORT=9000 daemon/scripts/smoke.sh   # override port
#     STX_HOST=127.0.0.1 STX_PORT=8473 daemon/scripts/smoke.sh
#
# The script ONLY talks HTTP — it appends a fresh, uniquely-named workspace each run,
# so it is safe to re-run against a long-lived daemon. For a throwaway clean slate,
# start the daemon with:  --db=/tmp/stx-smoke.db
#
# Requires: bash, curl, jq.

set -euo pipefail

HOST="${STX_HOST:-127.0.0.1}"
PORT="${STX_PORT:-8473}"
BASE="http://${HOST}:${PORT}"

# ── tiny presentation helpers ───────────────────────────────────────────────
# ALL human-facing output goes to stderr, so the only thing on stdout is a captured
# id (from `make`). That lets `VAR=$(make ...)` grab just the id while the request +
# pretty JSON response still stream to the terminal.
bold=$(printf '\033[1m'); cyan=$(printf '\033[36m'); dim=$(printf '\033[2m'); reset=$(printf '\033[0m')

step() { printf '\n%s━━ %s%s\n' "$bold$cyan" "$*" "$reset" >&2; }
note() { printf '%s%s%s\n' "$dim" "$*" "$reset" >&2; }

# _call METHOD PATH [JSON] — curl, narrate to stderr, echo the raw response to stdout.
_call() {
    local method="$1" path="$2" body="${3:-}"
    printf '%s» %s %s%s\n' "$bold" "$method" "$path" "$reset" >&2
    [ -n "$body" ] && note "  $body"
    local resp
    if [ -n "$body" ]; then
        resp=$(curl -sS -X "$method" "$BASE$path" -H 'Content-Type: application/json' -d "$body")
    else
        resp=$(curl -sS -X "$method" "$BASE$path")
    fi
    printf '%s\n' "$resp" | jq . >&2     # pretty response → terminal
    printf '%s' "$resp"                  # raw response → stdout (for capture)
}

# api METHOD PATH [JSON] — perform the call for its side effect + display only.
api() { _call "$@" >/dev/null; }

# make METHOD PATH [JSON] — perform the call and echo the created entity's .id.
# Use as: VAR=$(make POST /workspaces '{"name":"x"}')
make() { _call "$@" | jq -r '.id'; }

# expect_err METHOD PATH [JSON] — show HTTP status + body, never abort (for the
# deliberate-failure phase: these SHOULD be 4xx with an {error,kind} envelope).
expect_err() {
    local method="$1" path="$2" body="${3:-}"
    printf '%s» %s %s  %s(expecting failure)%s\n' "$bold" "$method" "$path" "$dim" "$reset" >&2
    [ -n "$body" ] && note "  $body"
    local out code resp
    if [ -n "$body" ]; then
        out=$(curl -sS -o - -w '\n%{http_code}' -X "$method" "$BASE$path" -H 'Content-Type: application/json' -d "$body")
    else
        out=$(curl -sS -o - -w '\n%{http_code}' -X "$method" "$BASE$path")
    fi
    code=$(printf '%s' "$out" | tail -n1)
    resp=$(printf '%s' "$out" | sed '$d')
    printf '  HTTP %s\n' "$code" >&2
    printf '%s\n' "$resp" | jq . >&2
}

# ── preflight ───────────────────────────────────────────────────────────────
command -v jq >/dev/null 2>&1 || { echo "error: jq is required (apt install jq)"; exit 1; }

step "Preflight: is the daemon up at $BASE ?"
if ! curl -sS "$BASE/health" >/dev/null 2>&1; then
    echo "error: cannot reach $BASE/health — is the daemon running?"
    echo "  start it with:  cd daemon && ./gradlew installDist && \\"
    echo "    ./build/install/stx-daemon/bin/stx-daemon --port=$PORT --db=/tmp/stx-smoke.db"
    exit 1
fi
note "health: $(curl -sS "$BASE/health")"

# Unique suffix so re-runs don't collide on the unique workspace name.
SUFFIX=$$

# ── build phase ─────────────────────────────────────────────────────────────
step "1. Create a workspace"
WS=$(make POST /workspaces "{\"name\":\"smoke-$SUFFIX\",\"metadata\":{\"owner\":\"demo\"}}")
note "workspace id = $WS"

step "2. Create statuses (Backlog, In Progress, Done[terminal])"
BACKLOG=$(make POST "/workspaces/$WS/statuses" '{"name":"Backlog","kanbanOrder":0}')
INPROG=$(make POST "/workspaces/$WS/statuses" '{"name":"In Progress","kanbanOrder":1}')
DONE=$(make POST "/workspaces/$WS/statuses" '{"name":"Done","terminal":true,"kanbanOrder":2}')
note "statuses: Backlog=$BACKLOG  InProgress=$INPROG  Done=$DONE"

step "3. Create legal transitions (Backlog→InProgress→Done, Backlog→Done)"
api POST "/workspaces/$WS/transitions" "{\"fromStatusId\":$BACKLOG,\"toStatusId\":$INPROG}" >/dev/null
api POST "/workspaces/$WS/transitions" "{\"fromStatusId\":$INPROG,\"toStatusId\":$DONE}" >/dev/null
api POST "/workspaces/$WS/transitions" "{\"fromStatusId\":$BACKLOG,\"toStatusId\":$DONE}" >/dev/null

step "4. Create a track (your \"project\") — auto-creates its root segment"
TRACK=$(make POST "/workspaces/$WS/tracks" '{"name":"Payments rewrite","description":"Move billing to the new ledger","metadata":{"quarter":"Q3"}}')
note "track id = $TRACK"

step "5. Create nested segments (your \"folders\") under the track"
SEG_API=$(make POST "/tracks/$TRACK/segments" '{"name":"API"}')
SEG_AUTH=$(make POST "/tracks/$TRACK/segments" "{\"name\":\"Auth\",\"parentSegmentId\":$SEG_API}")
note "segments: API=$SEG_API  API/Auth=$SEG_AUTH"

step "6. Create tasks (T1 on the track root segment; T2,T3 in API/Auth)"
T1=$(make POST "/tracks/$TRACK/tasks" '{"statusId":'"$BACKLOG"',"title":"Design ledger schema","priority":3,"kind":"design"}')
T2=$(make POST "/segments/$SEG_AUTH/tasks" '{"statusId":'"$BACKLOG"',"title":"Wire OAuth callback","priority":2,"kind":"feature","metadata":{"provider":"auth0"}}')
T3=$(make POST "/segments/$SEG_AUTH/tasks" '{"statusId":'"$BACKLOG"',"title":"Add token refresh","priority":1,"kind":"feature"}')
note "tasks: T1=$T1  T2=$T2  T3=$T3"

step "7. Add edges: T1 blocks T2 (spine); T2 relates_to T3 (decorative)"
api POST /blocks  "{\"source\":$T1,\"target\":$T2}" >/dev/null
api POST /relates "{\"kind\":\"duplicates\",\"source\":$T2,\"target\":$T3}" >/dev/null

# ── read / interact phase ───────────────────────────────────────────────────
step "8. List everything back (collections + single-entity reads)"
api GET /workspaces >/dev/null
api GET "/workspaces/$WS" >/dev/null
api GET "/workspaces/$WS/statuses" >/dev/null
api GET "/workspaces/$WS/transitions" >/dev/null
api GET "/workspaces/$WS/tracks" >/dev/null
api GET "/tracks/$TRACK" >/dev/null
api GET "/statuses/$BACKLOG" >/dev/null
api GET "/segments/$SEG_AUTH" >/dev/null
api GET "/tracks/$TRACK/segments" >/dev/null
api GET "/tracks/$TRACK/tasks" >/dev/null
api GET "/tasks/$T1" >/dev/null
note "segment tasks: direct vs. recursive subtree (T2,T3 live in API/Auth, under API)"
api GET "/segments/$SEG_API/tasks" >/dev/null
api GET "/segments/$SEG_API/tasks?recursive=true" >/dev/null

step "9. Frontier BEFORE unblocking — T2 should be ABSENT (blocked by T1)"
note "expect: T1 ($T1) and T3 ($T3) present; T2 ($T2) blocked and missing"
api GET "/next?workspace=$WS" >/dev/null

step "10. Move T1 Backlog → In Progress → Done, then recompute the frontier"
api POST "/tasks/$T1/status" "{\"toStatusId\":$INPROG}" >/dev/null
api POST "/tasks/$T1/status" "{\"toStatusId\":$DONE}" >/dev/null
note "T1 is now terminal — T2 should now APPEAR (recompute-on-read)"
api GET "/next?workspace=$WS" >/dev/null

step "11. Scoped frontier: only the Auth segment subtree, and by kind"
api GET "/next?workspace=$WS&segment=$SEG_AUTH" >/dev/null
api GET "/next?workspace=$WS&kind=feature" >/dev/null

# ── error-envelope phase (these SHOULD fail with {error,kind}) ──────────────
step "12. Illegal transition: T1 (Done) → Backlog has no transition → 400"
expect_err POST "/tasks/$T1/status" "{\"toStatusId\":$BACKLOG}"

step "13. Cycle rejection: T2 blocks T1 would close a cycle (T1→T2 exists) → 400"
expect_err POST /blocks "{\"source\":$T2,\"target\":$T1}"

step "14. NotFound: a task id that doesn't exist → 404"
expect_err GET "/tasks/999999"

# ── archive demo ────────────────────────────────────────────────────────────
step "15. Archive T3 (cascades its incident edges), then confirm it's gone from next"
api POST "/tasks/$T3/archive" >/dev/null
note "T3 ($T3) should no longer appear in the frontier"
api GET "/next?workspace=$WS" >/dev/null

# ── per-key metadata ──────────────────────────────────────────────────────────
step "16. Per-key metadata: set then delete a single key on T2 (blob stays intact)"
api PUT "/tasks/$T2/meta/jira_key" '{"value":"PAY-42"}' >/dev/null
note "key is normalized to lowercase; sibling keys (provider) are untouched"
api DELETE "/tasks/$T2/meta/jira_key" >/dev/null

# ── optimistic locking (CAS) ────────────────────────────────────────────────────
step "17. CAS: a stale ?expectedVersion is a 409; the current version succeeds"
VER=$(_call GET "/tasks/$T2" 2>/dev/null | jq -r '.version')
note "T2 current version = $VER"
expect_err PATCH "/tasks/$T2?expectedVersion=0" '{"priority":9}'   # 0 is stale after the meta writes
api PATCH "/tasks/$T2?expectedVersion=$VER" '{"priority":9}' >/dev/null

# ── refile a task under a different segment ──────────────────────────────────────
step "18. Refile T2 from API/Auth into the API segment"
api POST "/tasks/$T2/segment" "{\"toSegmentId\":$SEG_API}" >/dev/null
note "incident edge reads: T2's blocks/relates, and the whole-workspace edge list"
api GET "/tasks/$T2/blocks" >/dev/null
api GET "/workspaces/$WS/relates" >/dev/null

# ── rename a (pure-filing) segment ───────────────────────────────────────────────
step "19. Rename a segment (pure-filing nodes carry only a name)"
api PATCH "/segments/$SEG_API" '{"name":"API Layer"}' >/dev/null
note "the rename is reflected on the segment read-back"
api GET "/segments/$SEG_API" >/dev/null

# ── archive cascade ─────────────────────────────────────────────────────────────
step "20. Archive the whole track — cascades segments + tasks + edges; frontier empties"
api POST "/tracks/$TRACK/archive" >/dev/null
note "every task under the track is now archived → frontier should be empty"
api GET "/next?workspace=$WS" >/dev/null

step "Done."
note "workspace id = $WS  (name: smoke-$SUFFIX)"
note "Re-run any time — each run creates a fresh workspace. For a clean DB, start the"
note "daemon with --db=/tmp/stx-smoke.db and delete that file between runs."
