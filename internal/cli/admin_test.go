package cli

import (
	"encoding/json"
	"strings"
	"testing"
)

// Every admin leaf, driven through the real command tree: the text line it prints, and the
// method+path it sent. admin.go was the largest untested file in the CLI.
func TestAdmin_Commands(t *testing.T) {
	cases := []struct {
		name       string
		args       []string
		wantText   string
		wantMethod string
		wantPath   string
	}{
		{"ws new", []string{"ws", "new", "auth"}, "workspace #1  auth", "POST", "/workspaces"},
		{"ws rename", []string{"ws", "rename", "auth2", "-w", "auth"}, "renamed #1  auth2", "PATCH", "/workspaces/1"},
		{"track new", []string{"track", "new", "api", "-w", "auth"}, "track #10  api", "POST", "/workspaces/1/tracks"},
		{"track edit", []string{"track", "edit", "api", "-w", "auth", "--name", "core"}, "edited track #10  core", "PATCH", "/tracks/10"},
		{"segment new", []string{"segment", "new", "root", "-w", "auth", "-t", "api"}, "segment #20  root", "POST", "/tracks/10/segments"},
		{"status new", []string{"status", "new", "New", "-w", "auth", "--order", "3"}, "status #103  New", "POST", "/workspaces/1/statuses"},
		{"status default", []string{"status", "default", "Backlog", "-w", "auth"}, "default status → Backlog", "POST", "/workspaces/1/statuses/100/default"},
		{"status archive", []string{"status", "archive", "Backlog", "-w", "auth"}, "archived status Backlog", "POST", "/workspaces/1/statuses/100/archive"},
		{"kind new", []string{"kind", "new", "chore", "-w", "auth"}, "kind #201  chore", "POST", "/workspaces/1/kinds"},
		{"kind archive", []string{"kind", "archive", "bug", "-w", "auth"}, "archived kind bug", "POST", "/workspaces/1/kinds/200/archive"},
		{"transition", []string{"transition", "-w", "auth", "--from", "Backlog", "--to", "Doing"}, "transition Backlog → Doing", "POST", "/workspaces/1/transitions"},
	}
	base, log := newDriftServer(t)
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			log.reset()
			out, err := runCLI(t, base, "", tc.args...)
			if err != nil {
				t.Fatalf("%v: %v", tc.args, err)
			}
			if strings.TrimSpace(out) != tc.wantText {
				t.Errorf("text = %q, want %q", strings.TrimSpace(out), tc.wantText)
			}
			if _, ok := log.find(tc.wantMethod, tc.wantPath); !ok {
				t.Errorf("want %s %s, recorded %v", tc.wantMethod, tc.wantPath, log.all())
			}
		})
	}
}

// `status ls` is a query command: it prints the kanban order with the default/terminal tags, and
// -q gives the bare ids.
func TestAdmin_StatusLs(t *testing.T) {
	base, _ := newDriftServer(t)

	out, code := runCLIExit(t, base, "", "status", "ls", "-w", "auth")
	if code != ExitOK {
		t.Fatalf("exit = %d, want %d", code, ExitOK)
	}
	for _, want := range []string{"Backlog (default)", "Done (terminal)"} {
		if !strings.Contains(out, want) {
			t.Errorf("got %q, want it to contain %q", out, want)
		}
	}
	if q, _ := runCLIExit(t, base, "", "status", "ls", "-w", "auth", "-q"); q != "100\n101\n102\n" {
		t.Errorf("-q = %q, want the three ids", q)
	}
}

// track edit's field flags are the whole command — no flags is an error, not a silent no-op, and
// it must not reach the daemon.
func TestAdmin_TrackEditRequiresAField(t *testing.T) {
	base, log := newDriftServer(t)

	_, err := runCLI(t, base, "", "track", "edit", "api", "-w", "auth")
	if err == nil || !strings.Contains(err.Error(), "nothing to edit") {
		t.Fatalf("err = %v, want the nothing-to-edit error", err)
	}
	if _, ok := log.find("PATCH", "/tracks/10"); ok {
		t.Errorf("must not PATCH when there's nothing to change")
	}
}

// --desc - reads the description from stdin, like `add`/`edit` do.
func TestAdmin_TrackEditDescFromStdin(t *testing.T) {
	base, log := newDriftServer(t)

	if _, err := runCLI(t, base, "from stdin\n", "track", "edit", "api", "-w", "auth", "--desc", "-"); err != nil {
		t.Fatalf("track edit --desc -: %v", err)
	}
	req, _ := log.find("PATCH", "/tracks/10")
	var body map[string]any
	_ = json.Unmarshal([]byte(req.Body), &body)
	if body["description"] != "from stdin" {
		t.Errorf("description = %v, want %q (body %q)", body["description"], "from stdin", req.Body)
	}
	if _, ok := body["name"]; ok {
		t.Errorf("only the passed field should be sent, got %q", req.Body)
	}
}

// The CAS write carries the version it read, so the daemon can reject a stale edit.
func TestAdmin_RenameSendsExpectedVersion(t *testing.T) {
	base, log := newDriftServer(t)

	if _, err := runCLI(t, base, "", "ws", "rename", "auth2", "-w", "auth"); err != nil {
		t.Fatalf("ws rename: %v", err)
	}
	req, _ := log.find("PATCH", "/workspaces/1")
	var body map[string]any
	_ = json.Unmarshal([]byte(req.Body), &body)
	if body["expectedVersion"] != float64(1) {
		t.Errorf("expectedVersion = %v, want the fixture's version 1 (body %q)", body["expectedVersion"], req.Body)
	}
	if body["name"] != "auth2" {
		t.Errorf("name = %v, want auth2", body["name"])
	}
}

// The RunE-level guards: a missing -w and an unknown registry name both fail with a message that
// tells you what to do next.
func TestAdmin_Rejections(t *testing.T) {
	base, _ := newDriftServer(t)
	cases := map[string]struct {
		args []string
		want string
	}{
		"no workspace":   {[]string{"track", "new", "api"}, "--workspace required"},
		"unknown status": {[]string{"status", "default", "Nope", "-w", "auth"}, "available: Backlog, Doing, Done"},
		"unknown kind":   {[]string{"kind", "archive", "nope", "-w", "auth"}, "available: bug"},
		"unknown ws":     {[]string{"track", "new", "api", "-w", "nope"}, "no workspace named 'nope'"},
		"no track flag":  {[]string{"segment", "new", "root", "-w", "auth"}, `required flag(s) "track" not set`},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			_, err := runCLI(t, base, "", tc.args...)
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Errorf("err = %v, want it to contain %q", err, tc.want)
			}
		})
	}
}
