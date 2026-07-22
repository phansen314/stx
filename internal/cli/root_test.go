package cli

import (
	"bytes"
	"strings"
	"testing"
)

// Under `go test`, stdin/stdout aren't char devices, so interactive() is false and bare `stx`
// must fall back to help — never block trying to launch the builder.
func TestBareStx_NonInteractiveShowsHelp(t *testing.T) {
	root := NewRootCmd()
	var out bytes.Buffer
	root.SetArgs([]string{})
	root.SetOut(&out)
	root.SetErr(&out)
	if err := root.Execute(); err != nil {
		t.Fatalf("bare stx should print help, got error: %v", err)
	}
	if !strings.Contains(out.String(), "Usage:") {
		t.Fatalf("expected help output, got:\n%s", out.String())
	}
}

// An unrecognized command word is an error, not a silent builder launch.
func TestBareStx_UnknownCommandErrors(t *testing.T) {
	root := NewRootCmd()
	root.SetArgs([]string{"bogus"})
	root.SetOut(&bytes.Buffer{})
	root.SetErr(&bytes.Buffer{})
	err := root.Execute()
	if err == nil || !strings.Contains(err.Error(), "unknown command") {
		t.Fatalf("want unknown-command error, got: %v", err)
	}
}
