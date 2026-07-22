package cli

import (
	"bytes"
	"strings"
	"testing"
)

// runCLI executes the real command tree against the drift fixture daemon, with `in` as stdin,
// and returns stdout. Errors are returned separately so callers can assert on both.
func runCLI(t *testing.T, base, in string, args ...string) (string, error) {
	t.Helper()
	root := NewRootCmd()
	var out bytes.Buffer
	root.SetArgs(append(args, "--base-url", base))
	root.SetOut(&out)
	root.SetErr(&out)
	root.SetIn(strings.NewReader(in))
	err := root.Execute()
	return out.String(), err
}

// -q is the pipe format: ids only, one per line, no padding or decoration.
func TestQuiet_IdsOnly(t *testing.T) {
	base := driftServer(t)
	cases := map[string]struct {
		args []string
		want string
	}{
		"ls":   {[]string{"ls", "-q"}, "1\n"},
		"next": {[]string{"next", "-w", "auth", "-q"}, "5\n"},
		"tree": {[]string{"tree", "-w", "auth", "-q"}, "5\n"},
		"show": {[]string{"show", "5", "-q"}, "5\n"},
		"add":  {[]string{"add", "seed", "-w", "auth", "-t", "api", "-q"}, "5\n"},
		"mv":   {[]string{"mv", "5", "Doing", "-q"}, "5\n"},
		"done": {[]string{"done", "5", "-q"}, "5\n"},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			out, err := runCLI(t, base, "", tc.args...)
			if err != nil {
				t.Fatalf("stx %v: %v", tc.args, err)
			}
			if out != tc.want {
				t.Fatalf("want %q, got %q", tc.want, out)
			}
		})
	}
}

// The whole point: one command's -q output is the next command's stdin.
func TestQuiet_PipesIntoStdinIDs(t *testing.T) {
	base := driftServer(t)
	ids, err := runCLI(t, base, "", "next", "-w", "auth", "-q")
	if err != nil {
		t.Fatalf("next -q: %v", err)
	}
	out, err := runCLI(t, base, ids, "done", "-")
	if err != nil {
		t.Fatalf("done -: %v", err)
	}
	if !strings.Contains(out, "done #5 → Done") {
		t.Fatalf("want the done line, got %q", out)
	}
}

// Both flags own stdout; picking one silently would surprise a script.
func TestQuiet_JSONMutuallyExclusive(t *testing.T) {
	base := driftServer(t)
	_, err := runCLI(t, base, "", "ls", "-q", "--json")
	if err == nil || !strings.Contains(err.Error(), "mutually exclusive") {
		t.Fatalf("want a mutual-exclusion error, got %v", err)
	}
}

// --desc - stores stdin as the description.
func TestStdin_DescFromStdin(t *testing.T) {
	base := driftServer(t)
	out, err := runCLI(t, base, "from a file\n", "add", "seed", "-w", "auth", "-t", "api", "--desc", "-")
	if err != nil {
		t.Fatalf("add --desc -: %v", err)
	}
	if !strings.Contains(out, "added #5") {
		t.Fatalf("got %q", out)
	}
}

func TestBareValue_StringsUnquoted(t *testing.T) {
	if got := bareValue("main"); got != "main" {
		t.Fatalf(`want main, got %q`, got)
	}
	if got := bareValue(map[string]any{"a": float64(1)}); got != `{"a":1}` {
		t.Fatalf("want compact JSON, got %q", got)
	}
}
