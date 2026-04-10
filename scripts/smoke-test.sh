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
trap 'rm -rf "$TMPDIR"' EXIT

CMD="todo --db $DB"

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

run "Create workspace 'Work'" \
    $CMD workspace create Work

run "Create workspace 'Personal'" \
    $CMD workspace create Personal

run "List workspaces" \
    $CMD workspace ls

run "Switch to 'Work'" \
    $CMD workspace use Work

run "Rename active workspace to 'Office'" \
    $CMD workspace rename Office

run "List workspaces (verify rename)" \
    $CMD workspace ls

run "Switch back to 'Personal'" \
    $CMD workspace use Personal

run "Archive 'Personal'" \
    $CMD workspace archive Personal --force

run "List workspaces (archived hidden)" \
    $CMD workspace ls

run "List workspaces --all (archived visible)" \
    $CMD workspace ls --all

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

run "Add status 'Backlog'" \
    $CMD status create Backlog

run "Add status 'In Progress'" \
    $CMD status create "In Progress"

run "Add status 'Done'" \
    $CMD status create Done

run "List statuses" \
    $CMD status ls

run "Rename 'Backlog' to 'Todo'" \
    $CMD status rename Backlog Todo

run "List statuses (verify rename)" \
    $CMD status ls

run "Archive status 'Todo'" \
    bash -c "echo y | $CMD status archive Todo --force"

run "List statuses (after archive)" \
    $CMD status ls

# ════════════════════════════════════════════════════════════════════
#  PROJECT
# ════════════════════════════════════════════════════════════════════
section "Project commands"

run "Create project 'Backend'" \
    $CMD project create Backend --desc "Backend services"

run "Create project 'Frontend'" \
    $CMD project create Frontend

run "List projects" \
    $CMD project ls

run "Show project 'Backend'" \
    $CMD project show Backend

run "Archive project 'Frontend'" \
    $CMD project archive Frontend --force

run "List projects (after archive)" \
    $CMD project ls

# ════════════════════════════════════════════════════════════════════
#  TASK
# ════════════════════════════════════════════════════════════════════
section "Task: create"

run "Create task 'Set up CI'" \
    $CMD task create "Set up CI" -S "In Progress" --desc "GitHub Actions pipeline" --project Backend --priority 2

run "Create task 'Write docs'" \
    $CMD task create "Write docs" -S "In Progress"

run "Create task 'Fix login bug' with due date" \
    $CMD task create "Fix login bug" -S "In Progress" --due 2026-04-01 --priority 3

# ────────────────────────────────────────────────────────────────────
section "Task: ls"

run "List tasks" \
    $CMD task ls

run "List tasks --all (includes archived)" \
    $CMD task ls --all

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

run "Show task 2 (verify edits)" \
    $CMD task show task-0002

# ────────────────────────────────────────────────────────────────────
section "Task: mv"

run "Move task 1 to 'Done'" \
    $CMD task mv task-0001 Done

run "List tasks (verify move)" \
    $CMD task ls

# ────────────────────────────────────────────────────────────────────
section "Task: archive"

run "Archive task 2" \
    $CMD task archive task-0002 --force

run "List tasks (task 2 hidden)" \
    $CMD task ls

run "List tasks --all (task 2 visible)" \
    $CMD task ls --all

# ────────────────────────────────────────────────────────────────────
section "Task: log"

run "Show change log for task 1" \
    $CMD task log task-0001

# ════════════════════════════════════════════════════════════════════
#  TAGS
# ════════════════════════════════════════════════════════════════════
section "Tag commands"

run "Create tag 'urgent'" \
    $CMD tag create urgent

run "List tags" \
    $CMD tag ls

run "Tag task 3" \
    $CMD task edit task-0003 --tag urgent

run "Show task 3 (verify tag)" \
    $CMD task show task-0003

run "Archive tag 'urgent'" \
    $CMD tag archive urgent --unassign --force

# ════════════════════════════════════════════════════════════════════
#  GROUPS
# ════════════════════════════════════════════════════════════════════
section "Group commands"

run "Create group 'Sprint 1'" \
    $CMD group create "Sprint 1" --project Backend

run "List groups" \
    $CMD group ls --project Backend

run "Assign task 1 to group" \
    $CMD group assign task-0001 "Sprint 1" --project Backend

run "Show group 'Sprint 1'" \
    $CMD group show "Sprint 1" --project Backend

run "Unassign task 1 from group" \
    $CMD group unassign task-0001

run "Archive group 'Sprint 1'" \
    $CMD group archive "Sprint 1" --project Backend --force

# ════════════════════════════════════════════════════════════════════
#  DEPENDENCIES
# ════════════════════════════════════════════════════════════════════
section "Dependency commands"

run "Add dep: task 3 depends on task 1" \
    $CMD dep create task-0003 task-0001

run "Show task 3 (verify dep)" \
    $CMD task show task-0003

# ════════════════════════════════════════════════════════════════════
#  EXPORT (run while dep exists so Mermaid diagram has content)
# ════════════════════════════════════════════════════════════════════
section "Export"

EXPORT_PATH="$TMPDIR/export.md"

run "Export database to markdown" \
    $CMD export --md -o "$EXPORT_PATH"

echo -e "  Export written to: ${BOLD}${EXPORT_PATH}${RESET}"

run "Remove dep: task 3 no longer depends on task 1" \
    $CMD dep archive task-0003 task-0001

run "Show task 3 (dep removed)" \
    $CMD task show task-0003

# ════════════════════════════════════════════════════════════════════
#  CONTEXT
# ════════════════════════════════════════════════════════════════════
section "Context"

run "Workspace context snapshot" \
    $CMD context

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
    $CMD task mv task-9999 "In Progress"

# Test no active workspace error: use a separate DB with no workspace set
NO_WORKSPACE_DB="$TMPDIR/no-workspace.db"
run_expect_fail "No active workspace" \
    todo --db "$NO_WORKSPACE_DB" task ls

# ════════════════════════════════════════════════════════════════════
#  SUMMARY
# ════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}════════════════════════════════════════${RESET}"
echo -e "${GREEN}  All $pass_count checks passed.${RESET}"
echo -e "${BOLD}════════════════════════════════════════${RESET}"
