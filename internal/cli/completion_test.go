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

func TestShellInitBundlesWizardAndCompletion(t *testing.T) {
	out := runRoot(t, "shell-init")
	for _, want := range []string{
		"_stx_build",               // the guided builder
		"stx() {",                  // the wrapper function (bare stx → builder)
		"read -r -e -i",            // assembled command lands on an editable prompt
		"_stxb_task",               // a daemon-backed picker
		"complete -F _stx_fzf stx", // completion bundled in too
	} {
		if !strings.Contains(out, want) {
			t.Fatalf("shell-init missing %q", want)
		}
	}
}

func TestFzfCompletionScriptShape(t *testing.T) {
	out := runRoot(t, "fzf-completion")
	for _, want := range []string{
		"complete -F _stx_fzf stx",     // registers the completer
		"stx __commands",               // feeds the fzf command menu
		"--preview 'stx {1} -h'",       // help in the preview pane
		"stx __complete",               // delegates flags/subcommands past the command word
		"compgen -W",                   // filters the delegated candidates
	} {
		if !strings.Contains(out, want) {
			t.Fatalf("script missing %q", want)
		}
	}
}
