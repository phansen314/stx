package cli

import (
	"strings"
	"testing"

	"github.com/phansen314/stx/internal/version"
)

// `stx version` must work with the daemon down — that's half of what you run it for. Pointing
// --base-url at a dead port proves it never dial()s.
func TestVersion_DaemonDown(t *testing.T) {
	out, code := runCLIExit(t, "http://127.0.0.1:1", "", "version")
	if code != ExitOK {
		t.Fatalf("exit = %d, want %d (a version is never an empty result)", code, ExitOK)
	}
	if want := "stx " + version.Version; !strings.Contains(out, want) {
		t.Errorf("got %q, want it to contain %q", out, want)
	}
	if strings.Contains(out, "daemon:") {
		t.Errorf("got %q, want no daemon line when the daemon is down", out)
	}
}

// -q is the scriptable form: the bare version and nothing else, so `v=$(stx version -q)` works.
func TestVersion_Quiet(t *testing.T) {
	out, _ := runCLIExit(t, "http://127.0.0.1:1", "", "version", "-q")
	if out != version.Version+"\n" {
		t.Errorf("got %q, want %q", out, version.Version+"\n")
	}
}

// With the daemon up, the text form gains a daemon line and --json gains the daemon object —
// which is what finally gives GET /changes a consumer.
func TestVersion_DaemonUp(t *testing.T) {
	base, log := newDriftServer(t)

	out, code := runCLIExit(t, base, "", "version")
	if code != ExitOK {
		t.Fatalf("exit = %d, want %d", code, ExitOK)
	}
	if !strings.Contains(out, "schema 1, seq 7") {
		t.Errorf("got %q, want the fixture's schema/seq", out)
	}
	if _, ok := log.find("GET", "/changes"); !ok {
		t.Errorf("want a GET /changes, got %v", log.all())
	}

	js, _ := runCLIExit(t, base, "", "version", "--json")
	for _, want := range []string{`"version"`, `"daemon"`, `"schema": 1`, `"seq": 7`} {
		if !strings.Contains(js, want) {
			t.Errorf("--json output %q missing %q", js, want)
		}
	}
}
