#!/usr/bin/env bash
# Smoke test for `stx hook {ls,events,validate,schema}`.
# Exercises every flag and exit-code branch against temp hooks.toml files.
#
# Run: bash scripts/smoke-hooks.sh
set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
BOLD='\033[1m'
CYAN='\033[0;36m'
DIM='\033[2m'
RESET='\033[0m'

TMPDIR="$(mktemp -d)"
DB="$TMPDIR/test.db"
CONFIG="$TMPDIR/tui.toml"
VALID="$TMPDIR/valid-hooks.toml"
INVALID="$TMPDIR/invalid-hooks.toml"
PARSE_BROKEN="$TMPDIR/unparseable.toml"
SCHEMA_OUT="$TMPDIR/schema.json"
trap 'rm -rf "$TMPDIR"' EXIT

CMD="stx --db $DB --config $CONFIG --text"
CMD_JSON="stx --db $DB --config $CONFIG --json"
pass_count=0
fail_count=0

section() { echo -e "\n${BOLD}${CYAN}── $1 ──${RESET}"; }

run() {
    local desc="$1" expected_exit="${2:-0}"; shift 2
    echo -e "  ${BOLD}$desc${RESET}"
    echo -e "    ${DIM}\$ $*${RESET}"
    set +e
    output="$("$@" 2>&1)"; actual=$?
    set -e
    echo "$output" | sed 's/^/    /'
    if [[ "$actual" == "$expected_exit" ]]; then
        echo -e "    ${GREEN}PASS${RESET} (exit $actual)"
        ((pass_count++)) || true
    else
        echo -e "    ${RED}FAIL${RESET} (expected exit $expected_exit, got $actual)"
        ((fail_count++)) || true
        exit 1
    fi
}

assert_contains() {
    local needle="$1" haystack="$2" desc="$3"
    if grep -q -- "$needle" <<<"$haystack"; then
        echo -e "    ${GREEN}✓${RESET} ${desc}"
        ((pass_count++)) || true
    else
        echo -e "    ${RED}✗${RESET} ${desc} — missing: $needle"
        ((fail_count++)) || true
        exit 1
    fi
}

assert_absent() {
    local needle="$1" haystack="$2" desc="$3"
    if grep -q -- "$needle" <<<"$haystack"; then
        echo -e "    ${RED}✗${RESET} ${desc} — unexpectedly present: $needle"
        ((fail_count++)) || true
        exit 1
    else
        echo -e "    ${GREEN}✓${RESET} ${desc}"
        ((pass_count++)) || true
    fi
}

# ── Fixtures ────────────────────────────────────────────────────────

cat > "$VALID" <<'EOF'
# Global post-hook
[[hooks]]
event = "task.created"
timing = "post"
command = "echo post-global"
name = "guard"

# Global post-hook, disabled
[[hooks]]
event = "task.created"
timing = "post"
command = "echo post-global-disabled"
enabled = false

# Workspace-scoped post-hook
[[hooks]]
event = "task.archived"
timing = "post"
command = "echo scoped"
workspace = "Work"
name = "archive-logger"
EOF

cat > "$INVALID" <<'EOF'
[[hooks]]
event = "bogus.event"
timing = "post"
command = "x"

[[hooks]]
event = "task.created"
timing = "pre"
command = "y"
EOF

cat > "$PARSE_BROKEN" <<'EOF'
[[hooks]
this is not valid toml
EOF

# ════════════════════════════════════════════════════════════════════
section "stx hook events"
# ════════════════════════════════════════════════════════════════════

out="$($CMD hook events)"
echo "$out" | head -5 | sed 's/^/    /'
echo -e "    ${DIM}(truncated)${RESET}"
assert_contains "task.created" "$out" "includes task.created"
assert_contains "edge.meta_removed" "$out" "includes edge.meta_removed"
assert_contains "workspace.archived" "$out" "includes workspace.archived"

# ════════════════════════════════════════════════════════════════════
section "stx hook ls — no filters, valid config"
# ════════════════════════════════════════════════════════════════════

out="$($CMD hook ls --path "$VALID")"
echo "$out" | sed 's/^/    /'
assert_contains "\[post\]" "$out" "post timing shown"
assert_contains "\[disabled\]" "$out" "disabled marker"
assert_contains "\[workspace=Work\]" "$out" "workspace bracket"
assert_contains "\[name='guard'\]" "$out" "name bracket"

# ════════════════════════════════════════════════════════════════════
section "stx hook ls — filters"
# ════════════════════════════════════════════════════════════════════

out="$($CMD hook ls --path "$VALID" --event task.archived)"
echo "$out" | sed 's/^/    /'
assert_contains "echo scoped" "$out" "event filter matches"
assert_absent  "echo pre-global" "$out" "event filter excludes other events"

out="$($CMD hook ls --path "$VALID" --workspace Work)"
echo "$out" | sed 's/^/    /'
assert_contains "workspace=Work" "$out" "workspace filter keeps scoped"
assert_absent  "pre-global" "$out" "workspace filter excludes globals"

out="$($CMD hook ls --path "$VALID" --globals-only)"
echo "$out" | sed 's/^/    /'
assert_contains "pre-global" "$out" "globals-only keeps globals"
assert_absent  "workspace=Work" "$out" "globals-only excludes scoped"

run "--globals-only is mutex with --workspace (argparse → exit 2)" 2 \
    $CMD hook ls --path "$VALID" --globals-only --workspace Work

run "Invalid --event value (exit 4)" 4 \
    $CMD hook ls --path "$VALID" --event bogus.event

# ════════════════════════════════════════════════════════════════════
section "stx hook ls — broken configs surface friendly errors"
# ════════════════════════════════════════════════════════════════════

set +e
out="$($CMD hook ls --path "$INVALID" 2>&1)"; actual=$?
set -e
echo "$out" | sed 's/^/    /'
if [[ "$actual" == "4" ]]; then
    echo -e "    ${GREEN}PASS${RESET} (exit 4 as expected)"
    ((pass_count++)) || true
else
    echo -e "    ${RED}FAIL${RESET} (expected exit 4, got $actual)"
    ((fail_count++)) || true
    exit 1
fi
assert_contains "hooks config invalid" "$out" "friendly invalid-config header"
assert_contains "stx hook validate" "$out" "points at 'stx hook validate'"
assert_contains "post-only" "$out" "migration hint mentions post-only"

run "Unparseable TOML exits non-zero" 4 \
    $CMD hook ls --path "$PARSE_BROKEN"

# ════════════════════════════════════════════════════════════════════
section "stx hook validate"
# ════════════════════════════════════════════════════════════════════

run "Valid config → exit 0" 0 \
    $CMD hook validate --path "$VALID"

run "Invalid config → exit 4" 4 \
    $CMD hook validate --path "$INVALID"

run "Missing config file → exit 0 (treated as empty)" 0 \
    $CMD hook validate --path "$TMPDIR/does-not-exist.toml"

# JSON-mode invalid should still emit structured payload before exiting 4
set +e
out="$($CMD_JSON hook validate --path "$INVALID" 2>&1)"; actual=$?
set -e
echo "$out" | sed 's/^/    /'
if [[ "$actual" == "4" ]]; then
    echo -e "    ${GREEN}PASS${RESET} (JSON mode exit 4)"
    ((pass_count++)) || true
else
    echo -e "    ${RED}FAIL${RESET} (expected exit 4, got $actual)"
    ((fail_count++)) || true
    exit 1
fi
assert_contains '"valid": false' "$out" "JSON payload reports valid=false"
assert_contains '"errors"'        "$out" "JSON payload includes errors list"

# ════════════════════════════════════════════════════════════════════
section "stx hook schema"
# ════════════════════════════════════════════════════════════════════

out="$($CMD hook schema)"
echo "$out" | head -5 | sed 's/^/    /'
echo -e "    ${DIM}(truncated)${RESET}"
assert_contains "json-schema.org" "$out" "has \$schema URL"
assert_contains "task.created" "$out" "references task.created"

run "schema --output writes file" 0 \
    $CMD hook schema --output "$SCHEMA_OUT"
test -s "$SCHEMA_OUT" && echo -e "    ${GREEN}✓${RESET} file non-empty" && ((pass_count++)) || { echo -e "    ${RED}✗${RESET} file empty"; exit 1; }

run "schema --output without --overwrite on existing file → exit 4" 4 \
    $CMD hook schema --output "$SCHEMA_OUT"

run "schema --output --overwrite replaces file" 0 \
    $CMD hook schema --output "$SCHEMA_OUT" --overwrite

# ════════════════════════════════════════════════════════════════════
echo
echo -e "${BOLD}${GREEN}${pass_count} checks passed${RESET}, ${RED}${fail_count} failed${RESET}"
