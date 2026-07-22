package cli

import (
	"os"
	"testing"
)

// runExit drives Run() (the real main path) with the given argv and returns the exit code.
func runExit(t *testing.T, args ...string) int {
	t.Helper()
	orig := os.Args
	defer func() { os.Args = orig }()
	os.Args = append([]string{"stx"}, args...)
	return Run()
}

// grep's convention: 0 results, 1 empty result set, 2 error.
func TestRun_ExitCodes(t *testing.T) {
	base := driftServer(t)

	if code := runExit(t, "ls", "-q", "--base-url", base); code != ExitOK {
		t.Fatalf("ls with a workspace should exit 0, got %d", code)
	}
	// the fixture's relates-kinds list is empty — a successful command with no results
	if code := runExit(t, "relate-kinds", "-w", "auth", "-q", "--base-url", base); code != ExitEmpty {
		t.Fatalf("an empty result set should exit 1, got %d", code)
	}
	if code := runExit(t, "ls", "--base-url", "http://127.0.0.1:1"); code != ExitError {
		t.Fatalf("an unreachable daemon should exit 2, got %d", code)
	}
	// exit 1 must not leak into the next invocation
	if code := runExit(t, "ls", "-q", "--base-url", base); code != ExitOK {
		t.Fatalf("emptyResult leaked across invocations, got %d", code)
	}
}
