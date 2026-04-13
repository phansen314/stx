#!/usr/bin/env bash
set -euo pipefail

# ── Colors ──────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
BOLD='\033[1m'
CYAN='\033[0;36m'
RESET='\033[0m'

# ── Temp dir + cleanup ─────────────────────────────────────────────
TMPDIR="$(mktemp -d)"
DB="$TMPDIR/test.db"
CONFIG="$TMPDIR/tui.toml"
trap 'rm -rf "$TMPDIR"' EXIT

CMD="stx --db $DB --config $CONFIG"

pass_count=0
fail_count=0

section() {
    echo -e "\n${BOLD}${CYAN}── $1 ──${RESET}"
}

run() {
    local desc="$1"; shift
    echo -e "  ${BOLD}$desc${RESET}"
    echo -e "    \$ $*"
    if output=$("$@" 2>&1); then
        echo "$output" | sed 's/^/    /'
        echo -e "    ${GREEN}PASS${RESET}"
        ((pass_count++)) || true
    else
        echo "$output" | sed 's/^/    /'
        echo -e "    ${RED}FAIL${RESET} (exit $?)"
        ((fail_count++)) || true
        exit 1
    fi
}

run_expect_fail() {
    local desc="$1"; shift
    echo -e "  ${BOLD}$desc${RESET}"
    echo -e "    \$ $*"
    if output=$("$@" 2>&1); then
        echo "$output" | sed 's/^/    /'
        echo -e "    ${RED}FAIL${RESET} (expected non-zero exit)"
        ((fail_count++)) || true
        exit 1
    else
        echo "$output" | sed 's/^/    /'
        echo -e "    ${GREEN}PASS (expected failure)${RESET}"
        ((pass_count++)) || true
    fi
}

# ════════════════════════════════════════════════════════════════════
#  WORKSPACE
# ════════════════════════════════════════════════════════════════════
section "Workspace commands"

run "Create workspace 'Work' with seeded statuses" \
    $CMD workspace create Work --statuses "Backlog,In Progress,Done"

run "Create workspace 'Personal'" \
    $CMD workspace create Personal

run "List workspaces" \
    $CMD workspace ls

run "Switch to 'Work'" \
    $CMD workspace use Work

run "Rename active workspace to 'Office'" \
    $CMD workspace edit --name Office

run "List workspaces (verify rename)" \
    $CMD workspace ls

run "Switch to 'Personal'" \
    $CMD workspace use Personal

run "Archive 'Personal'" \
    $CMD workspace archive Personal --force

run "List workspaces (archived hidden)" \
    $CMD workspace ls

run "List workspaces (--archived include)" \
    $CMD workspace ls --archived include

run "Switch to 'Office'" \
    $CMD workspace use Office

# ── Workspace error paths ──────────────────────────────────────────
section "Workspace error paths"

run_expect_fail "Duplicate workspace name" \
    $CMD workspace create Office

# ════════════════════════════════════════════════════════════════════
#  STATUS
# ════════════════════════════════════════════════════════════════════
section "Status commands"

run "List statuses (seeded at workspace create)" \
    $CMD status ls

run "Add status 'Review'" \
    $CMD status create Review

run "Rename 'Review' to 'In Review'" \
    $CMD status edit Review --name "In Review"

run "List statuses (verify rename)" \
    $CMD status ls

run "Archive status 'In Review'" \
    $CMD status archive "In Review" --force

run "List statuses (after archive)" \
    $CMD status ls

# ════════════════════════════════════════════════════════════════════
#  TASK
# ════════════════════════════════════════════════════════════════════
section "Task: create"

run "Create task 'Set up CI'" \
    $CMD task create "Set up CI" -S "In Progress" --desc "GitHub Actions pipeline" --priority 2

run "Create task 'Write docs'" \
    $CMD task create "Write docs" -S "In Progress"

run "Create task 'Fix login bug' with due date" \
    $CMD task create "Fix login bug" -S "In Progress" --due 2026-04-01 --priority 3

# ────────────────────────────────────────────────────────────────────
section "Task: ls"

run "List tasks" \
    $CMD task ls

run "List tasks (--archived include)" \
    $CMD task ls --archived include

# ────────────────────────────────────────────────────────────────────
section "Task: show"

run "Show task 1" \
    $CMD task show task-0001

run "Show task 2" \
    $CMD task show task-0002

# ────────────────────────────────────────────────────────────────────
section "Task: edit"

run "Edit task title" \
    $CMD task edit task-0002 --title "Write documentation"

run "Edit task description and priority" \
    $CMD task edit task-0001 --desc "CI with GitHub Actions + linting" --priority 1

run "Edit task due date" \
    $CMD task edit task-0002 --due 2026-05-01

run "Preview edit (--dry-run)" \
    $CMD task edit task-0002 --priority 5 --dry-run

run "Show task 2 (verify edits)" \
    $CMD task show task-0002

# ────────────────────────────────────────────────────────────────────
section "Task: meta"

run "Set metadata key" \
    $CMD task meta set task-0001 branch feat/ci

run "List metadata" \
    $CMD task meta ls task-0001

run "Get metadata key" \
    $CMD task meta get task-0001 branch

run "Delete metadata key" \
    $CMD task meta del task-0001 branch

# ────────────────────────────────────────────────────────────────────
section "Task: mv"

run "Move task 1 to 'Done'" \
    $CMD task mv task-0001 --status Done

run "List tasks (verify move)" \
    $CMD task ls

# ────────────────────────────────────────────────────────────────────
section "Task: archive"

run "Archive task 2" \
    $CMD task archive task-0002 --force

run "List tasks (task 2 hidden)" \
    $CMD task ls

run "List tasks (--archived only)" \
    $CMD task ls --archived only

# ────────────────────────────────────────────────────────────────────
section "Task: log"

run "Show change log for task 1" \
    $CMD task log task-0001

# ════════════════════════════════════════════════════════════════════
#  GROUPS
# ════════════════════════════════════════════════════════════════════
section "Group commands"

run "Create group 'Backend'" \
    $CMD group create Backend --desc "Core API services"

run "Create nested group 'Auth' under 'Backend'" \
    $CMD group create Auth --parent Backend

run "List groups" \
    $CMD group ls

run "Show group 'Auth'" \
    $CMD group show Auth

run "Assign task 1 to 'Auth'" \
    $CMD group assign task-0001 Auth

run "Unassign task 1" \
    $CMD group unassign task-0001

run "Move 'Auth' to root level" \
    $CMD group mv Auth --to-top

run "Archive group 'Auth'" \
    $CMD group archive Auth --force

# ════════════════════════════════════════════════════════════════════
#  EDGES
# ════════════════════════════════════════════════════════════════════
section "Edge commands"

run "Create task edge (task-0003 blocks task-0001)" \
    $CMD edge create --source task-0003 --target task-0001 --kind blocks

run "List edges" \
    $CMD edge ls

run "Show task 3 (verify edge)" \
    $CMD task show task-0003

run "Set edge metadata" \
    $CMD edge meta set --source task-0003 --target task-0001 --kind blocks rationale "CI pipeline required"

run "List edge metadata" \
    $CMD edge meta ls --source task-0003 --target task-0001 --kind blocks

# ════════════════════════════════════════════════════════════════════
#  WORKSPACE SHOW (snapshot)
# ════════════════════════════════════════════════════════════════════
section "Workspace show"

run "Workspace snapshot" \
    $CMD workspace show

# ════════════════════════════════════════════════════════════════════
#  EXPORT (run while edge exists so Mermaid diagram has content)
# ════════════════════════════════════════════════════════════════════
section "Export"

EXPORT_PATH="$TMPDIR/export.md"

run "Export database to markdown" \
    $CMD export --md -o "$EXPORT_PATH"

echo -e "  Export written to: ${BOLD}${EXPORT_PATH}${RESET}"

run "Archive edge" \
    $CMD edge archive --source task-0003 --target task-0001 --kind blocks

run "Show task 3 (edge archived)" \
    $CMD task show task-0003

# ════════════════════════════════════════════════════════════════════
#  INFO
# ════════════════════════════════════════════════════════════════════
section "Info"

run "Show file locations" \
    $CMD info

# ════════════════════════════════════════════════════════════════════
#  BACKUP
# ════════════════════════════════════════════════════════════════════
section "Backup"

BACKUP_PATH="$TMPDIR/backup.db"

run "Backup database" \
    $CMD backup "$BACKUP_PATH"

# ════════════════════════════════════════════════════════════════════
#  ERROR PATHS
# ════════════════════════════════════════════════════════════════════
section "Error paths"

run_expect_fail "Show missing task" \
    $CMD task show task-9999

run_expect_fail "Move missing task" \
    $CMD task mv task-9999 --status "In Progress"

# Test no active workspace error: separate DB with no workspace set
NO_WORKSPACE_DB="$TMPDIR/no-workspace.db"
NO_WORKSPACE_CONFIG="$TMPDIR/no-workspace.toml"
run_expect_fail "No active workspace" \
    stx --db "$NO_WORKSPACE_DB" --config "$NO_WORKSPACE_CONFIG" task ls

# ════════════════════════════════════════════════════════════════════
#  SUMMARY
# ════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}════════════════════════════════════════${RESET}"
echo -e "${GREEN}  All $pass_count checks passed.${RESET}"
echo -e "${BOLD}════════════════════════════════════════${RESET}"
