package cli

import (
	"strings"
	"testing"
)

func TestArchive_EachType(t *testing.T) {
	cases := map[string]struct {
		args []string
		path string
	}{
		"task":      {[]string{"archive", "task", "5"}, "/tasks/5/archive"},
		"segment":   {[]string{"archive", "segment", "20"}, "/segments/20/archive"},
		"track":     {[]string{"archive", "track", "10", "--yes"}, "/tracks/10/archive"},
		"workspace": {[]string{"archive", "workspace", "1", "--yes"}, "/workspaces/1/archive"},
	}
	base, log := newDriftServer(t)
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			log.reset()
			out, err := runCLI(t, base, "", tc.args...)
			if err != nil {
				t.Fatalf("%v: %v", tc.args, err)
			}
			if want := "archived " + name; !strings.Contains(out, want) {
				t.Errorf("got %q, want it to contain %q", out, want)
			}
			if _, ok := log.find("POST", tc.path); !ok {
				t.Errorf("want POST %s, recorded %v", tc.path, log.all())
			}
		})
	}
}

// The --yes guard for the cascading types is checked *before* dialing. That ordering is the guard:
// if it ran after, a confirm-less `archive workspace` would already have hit the daemon.
func TestArchive_CascadeGuardFiresBeforeDialing(t *testing.T) {
	base, log := newDriftServer(t)

	for _, typ := range []string{"track", "workspace"} {
		log.reset()
		_, err := runCLI(t, base, "", "archive", typ, "10")
		if err == nil || !strings.Contains(err.Error(), "pass --yes to confirm") {
			t.Errorf("%s: err = %v, want the --yes guard", typ, err)
		}
		if got := log.all(); len(got) != 0 {
			t.Errorf("%s: guard must fire before any request, got %v", typ, got)
		}
	}
	// task/segment don't cascade, so they need no confirmation
	for _, typ := range []string{"task", "segment"} {
		if _, err := runCLI(t, base, "", "archive", typ, map[string]string{"task": "5", "segment": "20"}[typ]); err != nil {
			t.Errorf("%s should not require --yes: %v", typ, err)
		}
	}
}

func TestArchive_InvalidType(t *testing.T) {
	base, log := newDriftServer(t)

	_, err := runCLI(t, base, "", "archive", "sprint", "5")
	if err == nil || !strings.Contains(err.Error(), `invalid type "sprint"`) {
		t.Fatalf("err = %v, want an invalid-type error", err)
	}
	if got := log.all(); len(got) != 0 {
		t.Errorf("must reject before dialing, got %v", got)
	}
}

// `-` batches, and a failing id doesn't stop the ones after it (xargs semantics) — the command
// still fails at the end.
func TestArchive_BatchContinuesPastFailure(t *testing.T) {
	base, log := newDriftServer(t)

	out, err := runCLI(t, base, "5\n404\n5\n", "archive", "task", "-")
	if err == nil {
		t.Fatalf("want the batch to fail (404 is not in the fixture), got nil")
	}
	if n := strings.Count(out, "archived task #5"); n != 2 {
		t.Errorf("archived-lines = %d, want 2 — the failing id must not abort the batch", n)
	}
	if _, ok := log.find("POST", "/tasks/404/archive"); !ok {
		t.Errorf("want the failing id attempted, recorded %v", log.all())
	}
}
