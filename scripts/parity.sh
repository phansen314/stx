#!/usr/bin/env bash
# parity.sh — the "keeps us honest" check: run the same commands through the Go client and
# the Python oracle against a LIVE daemon, and diff. Phase 0 covers `ls` (read) and `edit`
# (write + CAS). Extend the matrix as commands are ported.
#
# Requires: a running daemon, `jq`, the Go binary (bin/stx-go), and the Python CLI (bin/stx).
set -uo pipefail
cd "$(dirname "$0")/.."

GO=./bin/stx-go
PY=./bin/stx
fails=0

# norm: canonicalize JSON (sort keys) so key-order noise doesn't show as a diff.
norm() { jq -S . 2>/dev/null; }

diff_json() {  # diff_json "<label>" <cmd...>
	local label=$1; shift
	local g p
	g=$("$GO"  "$@" --json 2>&1 | norm)
	p=$("$PY"  "$@" --json 2>&1 | norm)
	if [[ "$g" == "$p" ]]; then
		echo "ok   $label"
	else
		echo "DIFF $label"; diff <(echo "$p") <(echo "$g") | sed 's/^/     /'; ((fails++))
	fi
}

diff_text() {  # diff_text "<label>" <cmd...>
	local label=$1; shift
	if diff <("$PY" "$@" 2>&1) <("$GO" "$@" 2>&1) >/dev/null; then
		echo "ok   $label"
	else
		echo "DIFF $label"; diff <("$PY" "$@" 2>&1) <("$GO" "$@" 2>&1) | sed 's/^/     /'; ((fails++))
	fi
}

echo "== reads =="
diff_json "ls --json"  ls
diff_text "ls (text)"  ls

# Writes: mutate through Go, confirm the Python oracle sees the new value (round-trip honesty).
# Pass a task id as $1 to exercise edit; skipped otherwise so the read checks always run.
if [[ $# -ge 1 ]]; then
	tid=$1
	echo "== write: edit #$tid =="
	stamp="parity-$(date +%s 2>/dev/null || echo x)"
	"$GO" edit "$tid" --desc "$stamp" >/dev/null
	got=$("$PY" show "$tid" --json | jq -r '.task.description')
	if [[ "$got" == "$stamp" ]]; then echo "ok   edit round-trip (Go wrote, Python reads '$stamp')"
	else echo "DIFF edit round-trip: python sees '$got', expected '$stamp'"; ((fails++)); fi
fi

echo
if ((fails)); then echo "$fails parity failure(s)"; exit 1; else echo "parity clean"; fi
