package cli

import (
	"fmt"
	"os"
)

// Process exit codes, following grep's convention so shell predicates work:
// `if stx next -w x -q >/dev/null; then …` asks "is anything ready?" without parsing output.
const (
	ExitOK    = 0 // results
	ExitEmpty = 1 // the command succeeded but its result set is empty
	ExitError = 2 // anything went wrong
)

// emptyResult is set by markEmpty() when a query command's result set is empty. It rides beside
// the cobra error path rather than through it: a RunE returning an "empty" sentinel would make
// Execute() non-nil for a perfectly successful command (and would trip TestBuilders_NoDrift,
// which drives every builder against a fake daemon holding no tasks).
var emptyResult bool

// markEmpty flags the current invocation as having produced no results (exit 1). Query commands
// only — a mutation that changed nothing is not "empty", it's an error or a no-op.
func markEmpty() { emptyResult = true }

// Run executes the root command and returns the process exit code (see the Exit* constants).
func Run() int {
	if err := NewRootCmd().Execute(); err != nil {
		fmt.Fprintln(os.Stderr, FormatError(err))
		return ExitError
	}
	if emptyResult {
		return ExitEmpty
	}
	return ExitOK
}
