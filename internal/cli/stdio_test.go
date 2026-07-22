package cli

import (
	"errors"
	"strings"
	"testing"

	"github.com/spf13/cobra"
)

// cmdWithStdin returns a bare command whose InOrStdin() is the given text, and clears the
// stdin claim so each case starts fresh.
func cmdWithStdin(text string) *cobra.Command {
	stdinClaimed = ""
	c := &cobra.Command{}
	c.SetIn(strings.NewReader(text))
	return c
}

func TestReadIDs_SingleArg(t *testing.T) {
	ids, err := readIDs(cmdWithStdin(""), "42")
	if err != nil || len(ids) != 1 || ids[0] != 42 {
		t.Fatalf("want [42], got %v (err %v)", ids, err)
	}
	if stdinClaimed != "" {
		t.Fatalf("a literal id must not claim stdin")
	}
}

// `-` accepts both output modes stx itself produces: bare ids (-q) and the padded human render.
func TestReadIDs_Stdin(t *testing.T) {
	cases := map[string]struct {
		in   string
		want []int64
	}{
		"bare ids":       {"41\n42\n", []int64{41, 42}},
		"blank lines":    {"41\n\n  \n42\n", []int64{41, 42}},
		"hash prefix":    {"#41\n#42\n", []int64{41, 42}},
		"comments":       {"# a note\n41\n", []int64{41}},
		"frontier lines": {"  41  P2  [Todo]  wire it\n  42      [Doing]  ship it\n", []int64{41, 42}},
		"no trailing nl": {"41", []int64{41}},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			ids, err := readIDs(cmdWithStdin(tc.in), "-")
			if err != nil {
				t.Fatalf("readIDs: %v", err)
			}
			if len(ids) != len(tc.want) {
				t.Fatalf("want %v, got %v", tc.want, ids)
			}
			for i := range ids {
				if ids[i] != tc.want[i] {
					t.Fatalf("want %v, got %v", tc.want, ids)
				}
			}
		})
	}
}

func TestReadIDs_StdinErrors(t *testing.T) {
	if _, err := readIDs(cmdWithStdin(""), "-"); err == nil {
		t.Fatal("empty stdin should error, not silently no-op")
	}
	if _, err := readIDs(cmdWithStdin("41x\n"), "-"); err == nil {
		t.Fatal("a malformed id should error")
	}
}

// Stdin is one stream: the second `-` in a single command is a user mistake, not a re-read.
func TestClaimStdin_OncePerCommand(t *testing.T) {
	c := cmdWithStdin("41\n")
	if _, err := readIDs(c, "-"); err != nil {
		t.Fatalf("first claim: %v", err)
	}
	_, err := readValue(c, "-", "--desc")
	if err == nil || !strings.Contains(err.Error(), "already being read") {
		t.Fatalf("want an already-claimed error, got %v", err)
	}
}

func TestReadValue_Stdin(t *testing.T) {
	got, err := readValue(cmdWithStdin("line one\nline two\n"), "-", "--desc")
	if err != nil {
		t.Fatalf("readValue: %v", err)
	}
	if got != "line one\nline two" { // exactly one trailing newline trimmed
		t.Fatalf("got %q", got)
	}
	if got, _ := readValue(cmdWithStdin("ignored"), "literal", "--desc"); got != "literal" {
		t.Fatalf("a literal value must not read stdin, got %q", got)
	}
}

// A batch keeps going past a failure and reports how many died; a single id passes its error
// through verbatim (so `mv`'s "legal from …" hint survives).
func TestRunIDs_BatchVsSingle(t *testing.T) {
	c := cmdWithStdin("")
	var errOut strings.Builder
	c.SetErr(&errOut)
	seen := 0
	err := runIDs(c, []int64{1, 2, 3}, func(id int64) error {
		seen++
		if id == 2 {
			return errBoom
		}
		return nil
	})
	if seen != 3 {
		t.Fatalf("batch should visit every id, saw %d", seen)
	}
	if err == nil || !strings.Contains(err.Error(), "1 of 3 failed") {
		t.Fatalf("want a batch summary error, got %v", err)
	}
	if !strings.Contains(errOut.String(), "boom") {
		t.Fatalf("the per-id failure belongs on stderr, got %q", errOut.String())
	}
	if err := runIDs(c, []int64{1}, func(int64) error { return errBoom }); err != errBoom {
		t.Fatalf("single id should propagate verbatim, got %v", err)
	}
}

var errBoom = errors.New("boom")
