package cli

import (
	"strings"
	"testing"
)

func TestShow_SingleAndBatch(t *testing.T) {
	base, log := newDriftServer(t)

	out, err := runCLI(t, base, "", "show", "5")
	if err != nil {
		t.Fatalf("show: %v", err)
	}
	if !strings.Contains(out, "seed") {
		t.Errorf("got %q, want the task title", out)
	}

	log.reset()
	if _, err := runCLI(t, base, "5\n5\n", "show", "-"); err != nil {
		t.Fatalf("show -: %v", err)
	}
	var details int
	for _, r := range log.all() {
		if r.Method == "GET" && r.Path == "/tasks/5" {
			details++
		}
	}
	if details != 2 {
		t.Errorf("GET /tasks/5 = %d, want 2 (one per id on stdin)", details)
	}
}

// --json is the daemon's shape verbatim, and a single id emits the bare object rather than a
// one-element array.
func TestShow_JSONIsVerbatim(t *testing.T) {
	base, _ := newDriftServer(t)

	out, err := runCLI(t, base, "", "show", "5", "--json")
	if err != nil {
		t.Fatalf("show --json: %v", err)
	}
	if strings.HasPrefix(strings.TrimSpace(out), "[") {
		t.Errorf("one id should emit the bare object, got %q", out)
	}
	for _, want := range []string{`"task"`, `"blocksIn"`, `"blocksOut"`, `"relates"`} {
		if !strings.Contains(out, want) {
			t.Errorf("got %q, want it to contain %q", out, want)
		}
	}
}

// The status/kind registries exist only to render text, so --json and -q must skip both fetches.
// Regressing this is invisible in the output — it just costs two extra round trips per id.
func TestShow_QuietAndJSONSkipRegistryFetches(t *testing.T) {
	base, log := newDriftServer(t)

	for _, flag := range []string{"-q", "--json"} {
		log.reset()
		if _, err := runCLI(t, base, "", "show", "5", flag); err != nil {
			t.Fatalf("show %s: %v", flag, err)
		}
		for _, p := range []string{"/workspaces/1/statuses", "/workspaces/1/kinds"} {
			if _, ok := log.find("GET", p); ok {
				t.Errorf("%s should not fetch %s, recorded %v", flag, p, log.all())
			}
		}
	}

	// …and the text path does need them
	log.reset()
	if _, err := runCLI(t, base, "", "show", "5"); err != nil {
		t.Fatalf("show: %v", err)
	}
	for _, p := range []string{"/workspaces/1/statuses", "/workspaces/1/kinds"} {
		if _, ok := log.find("GET", p); !ok {
			t.Errorf("the text render needs %s, recorded %v", p, log.all())
		}
	}
}
