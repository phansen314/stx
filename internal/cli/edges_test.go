package cli

import (
	"encoding/json"
	"strings"
	"testing"
)

// Edge orientation is the bug that hides here: `block <id> --on <blocker>` means the *blocker* is
// the source and the named task is the target, and `relate <a> --to <b>` is the other way round.
// Asserting the wire body is the only way to pin that down.
func TestEdges_Orientation(t *testing.T) {
	cases := []struct {
		name string
		args []string
		path string
		want map[string]any
		text string
	}{
		{
			"block", []string{"block", "5", "--on", "9"}, "/blocks",
			map[string]any{"sourceTaskId": float64(9), "targetTaskId": float64(5)},
			"#5 now blocked by #9",
		},
		{
			"unblock", []string{"unblock", "5", "--on", "9"}, "/blocks/archive",
			map[string]any{"sourceTaskId": float64(9), "targetTaskId": float64(5)},
			"#5 no longer blocked by #9",
		},
		{
			"relate", []string{"relate", "5", "--to", "9", "--kind", "spawns"}, "/relates",
			map[string]any{"sourceTaskId": float64(5), "targetTaskId": float64(9), "kind": "spawns"},
			"#5 spawns #9",
		},
		{
			"unrelate", []string{"unrelate", "5", "--to", "9", "--kind", "spawns"}, "/relates/archive",
			map[string]any{"sourceTaskId": float64(5), "targetTaskId": float64(9), "kind": "spawns"},
			"#5 no longer spawns #9",
		},
	}
	base, log := newDriftServer(t)
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			log.reset()
			out, err := runCLI(t, base, "", tc.args...)
			if err != nil {
				t.Fatalf("%v: %v", tc.args, err)
			}
			if strings.TrimSpace(out) != tc.text {
				t.Errorf("text = %q, want %q", strings.TrimSpace(out), tc.text)
			}
			req, ok := log.find("POST", tc.path)
			if !ok {
				t.Fatalf("want POST %s, recorded %v", tc.path, log.all())
			}
			var body map[string]any
			if err := json.Unmarshal([]byte(req.Body), &body); err != nil {
				t.Fatalf("body %q: %v", req.Body, err)
			}
			for k, want := range tc.want {
				if body[k] != want {
					t.Errorf("%s = %v, want %v (body %q)", k, body[k], want, req.Body)
				}
			}
		})
	}
}

func TestEdges_RequiredFlags(t *testing.T) {
	base, _ := newDriftServer(t)
	cases := map[string][]string{
		"block without --on":    {"block", "5"},
		"unblock without --on":  {"unblock", "5"},
		"relate without --to":   {"relate", "5", "--kind", "spawns"},
		"relate without --kind": {"relate", "5", "--to", "9"},
	}
	for name, args := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := runCLI(t, base, "", args...); err == nil {
				t.Errorf("%v: want a required-flag error, got nil", args)
			}
		})
	}
}

// relate-kinds is a query: empty is exit 1 with a message, and -q prints the kind *strings* (not
// ids — it's the one -q that isn't an id list).
func TestEdges_RelateKinds(t *testing.T) {
	base, _ := newDriftServer(t)

	out, code := runCLIExit(t, base, "", "relate-kinds", "-w", "auth")
	if code != ExitEmpty {
		t.Errorf("exit = %d, want %d for an empty result set", code, ExitEmpty)
	}
	if !strings.Contains(out, "(no relation kinds in use)") {
		t.Errorf("got %q, want the empty message", out)
	}

	if q, _ := runCLIExit(t, base, "", "relate-kinds", "-w", "auth", "-q"); q != "" {
		t.Errorf("-q on an empty set = %q, want nothing (rule of silence)", q)
	}
}

// `-` batches edges the same way it batches everything else.
func TestEdges_BatchFromStdin(t *testing.T) {
	base, log := newDriftServer(t)

	out, err := runCLI(t, base, "5\n5\n", "block", "-", "--on", "9")
	if err != nil {
		t.Fatalf("block -: %v", err)
	}
	if n := strings.Count(out, "now blocked by #9"); n != 2 {
		t.Errorf("lines = %d, want 2", n)
	}
	var posts int
	for _, r := range log.all() {
		if r.Method == "POST" && r.Path == "/blocks" {
			posts++
		}
	}
	if posts != 2 {
		t.Errorf("POST /blocks = %d, want 2", posts)
	}
}
