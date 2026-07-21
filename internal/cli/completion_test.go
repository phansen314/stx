package cli

import (
	"bytes"
	"strings"
	"testing"
)

func runRoot(t *testing.T, args ...string) string {
	t.Helper()
	root := NewRootCmd()
	var buf bytes.Buffer
	root.SetOut(&buf)
	root.SetArgs(args)
	if err := root.Execute(); err != nil {
		t.Fatalf("execute %v: %v", args, err)
	}
	return buf.String()
}

func TestCommandsEmitter(t *testing.T) {
	out := runRoot(t, "__commands")
	for _, name := range []string{"ls", "edit", "tree", "graph", "meta", "transition", "archive"} {
		if !strings.Contains(out, name+"\t") {
			t.Fatalf("missing %q in __commands output:\n%s", name, out)
		}
	}
	if strings.Contains(out, "__commands\t") {
		t.Fatal("__commands must not list itself")
	}
	// each line is name<TAB>help
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		if !strings.Contains(line, "\t") {
			t.Fatalf("line missing tab: %q", line)
		}
	}
}

func TestFzfCompletionScriptShape(t *testing.T) {
	out := runRoot(t, "fzf-completion")
	for _, want := range []string{
		"complete -F _stx_fzf stx",     // registers the completer
		"stx __commands",               // feeds the catalog
		"--preview 'stx {1} -h'",       // help in the preview pane
		"compgen -W",                   // graceful no-fzf fallback
	} {
		if !strings.Contains(out, want) {
			t.Fatalf("script missing %q", want)
		}
	}
}
