#!/usr/bin/env bash
# parity.sh — the "keeps us honest" check: run the same commands through the Go client and
# the Python oracle against a LIVE daemon, and diff. Extend the matrix as commands are ported.
#
#   ./scripts/parity.sh [workspace] [task-id]
#     (no args)      → ls only
#     workspace      → + tree/next for that workspace
#     workspace id   → + show <id>, and a Go→Python edit round-trip on <id>
#
# Requires: a running daemon, `jq`, bin/stx-go (Go), bin/stx (Python oracle).
set -uo pipefail
cd "$(dirname "$0")/.."

GO=./bin/stx-go
PY=./bin/stx-py     # the Python oracle (bin/stx is the Go client after the cutover)
WS=${1:-}
TID=${2:-}
fails=0

norm() { jq -S . 2>/dev/null; }

diff_text() { # diff_text "<label>" <cmd...>
	local label=$1; shift
	if [[ "$("$PY" "$@" 2>&1)" == "$("$GO" "$@" 2>&1)" ]]; then echo "ok   $label"
	else echo "DIFF $label"; diff <("$PY" "$@" 2>&1) <("$GO" "$@" 2>&1) | sed 's/^/     /'; ((fails++)); fi
}

diff_json() { # diff_json "<label>" <cmd...>
	local label=$1; shift
	local g p; g=$("$GO" "$@" --json 2>&1 | norm); p=$("$PY" "$@" --json 2>&1 | norm)
	if [[ "$g" == "$p" ]]; then echo "ok   $label"
	else echo "DIFF $label"; diff <(echo "$p") <(echo "$g") | sed 's/^/     /'; ((fails++)); fi
}

echo "== ls =="
diff_json "ls --json" ls
diff_text "ls (text)" ls

if [[ -n "$WS" ]]; then
	echo "== tree / next  (-w $WS) =="
	diff_text "tree (text)" tree -w "$WS"
	diff_json "tree --json" tree -w "$WS"
	diff_text "next (text)" next -w "$WS"
	diff_json "next --json" next -w "$WS"
fi

if [[ -n "$TID" ]]; then
	echo "== show #$TID =="
	diff_text "show (text)" show "$TID"
	diff_json "show --json" show "$TID"
	echo "== write: edit round-trip #$TID =="
	stamp="parity-$(date +%s 2>/dev/null || echo x)"
	"$GO" edit "$TID" --desc "$stamp" >/dev/null
	got=$("$PY" show "$TID" --json | jq -r '.task.description')
	if [[ "$got" == "$stamp" ]]; then echo "ok   edit round-trip (Go wrote, Python reads '$stamp')"
	else echo "DIFF edit round-trip: python sees '$got', expected '$stamp'"; ((fails++)); fi
fi

echo
if ((fails)); then echo "$fails parity failure(s)"; exit 1; else echo "parity clean"; fi
