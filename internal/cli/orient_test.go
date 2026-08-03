package cli

import (
	"net/url"
	"strings"
	"testing"
)

// The renderers were already tested; the command wiring was not. What `next`'s flags turn into on
// the wire is the contract — a dropped filter is invisible in the output (it just returns more).
func TestNext_QueryConstruction(t *testing.T) {
	cases := map[string]struct {
		args   []string
		want   map[string]string
		absent []string
	}{
		"workspace only": {
			[]string{"next", "-w", "auth"},
			map[string]string{"workspace": "1"},
			[]string{"track", "segment", "kind", "limit"},
		},
		"track scope": {
			[]string{"next", "-w", "auth", "-t", "api"},
			map[string]string{"workspace": "1", "track": "10"},
			[]string{"segment", "kind"},
		},
		"segment subtree": {
			[]string{"next", "-w", "auth", "-s", "20"},
			map[string]string{"workspace": "1", "segment": "20"},
			nil,
		},
		"kind filter resolves the name": {
			[]string{"next", "-w", "auth", "--kind", "bug"},
			map[string]string{"workspace": "1", "kind": "200"},
			nil,
		},
		"kind by id": {
			[]string{"next", "-w", "auth", "--kind", "200"},
			map[string]string{"workspace": "1", "kind": "200"},
			nil,
		},
		"everything": {
			[]string{"next", "-w", "auth", "-t", "api", "--kind", "bug", "--limit", "3"},
			map[string]string{"workspace": "1", "track": "10", "kind": "200", "limit": "3"},
			nil,
		},
	}
	base, log := newDriftServer(t)
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			log.reset()
			if _, err := runCLI(t, base, "", tc.args...); err != nil {
				t.Fatalf("%v: %v", tc.args, err)
			}
			req, ok := log.find("GET", "/next")
			if !ok {
				t.Fatalf("no GET /next recorded: %v", log.all())
			}
			q, err := url.ParseQuery(req.RawQuery)
			if err != nil {
				t.Fatalf("query %q: %v", req.RawQuery, err)
			}
			for k, want := range tc.want {
				if got := q.Get(k); got != want {
					t.Errorf("%s = %q, want %q (query %q)", k, got, want, req.RawQuery)
				}
			}
			for _, k := range tc.absent {
				if q.Has(k) {
					t.Errorf("%s should be omitted entirely, query was %q", k, req.RawQuery)
				}
			}
		})
	}
}

// An unknown kind is an error naming the registry, not a silently empty frontier — that's the
// whole reason the filter goes through the registry instead of matching free text.
func TestNext_UnknownKind(t *testing.T) {
	base, log := newDriftServer(t)

	_, err := runCLI(t, base, "", "next", "-w", "auth", "--kind", "nope")
	if err == nil || !strings.Contains(err.Error(), "available: bug") {
		t.Fatalf("err = %v, want the available-kinds message", err)
	}
	if _, ok := log.find("GET", "/next"); ok {
		t.Errorf("must fail before querying the frontier")
	}
}

func TestNext_RequiresWorkspace(t *testing.T) {
	base, _ := newDriftServer(t)

	if _, err := runCLI(t, base, "", "next"); err == nil ||
		!strings.Contains(err.Error(), "--workspace required") {
		t.Fatalf("err = %v, want the -w requirement", err)
	}
}

// -q skips the status lookup nobody would see (the render is the only consumer).
func TestNext_QuietSkipsStatusLookup(t *testing.T) {
	base, log := newDriftServer(t)

	out, _ := runCLIExit(t, base, "", "next", "-w", "auth", "-q")
	if out != "5\n" {
		t.Errorf("got %q, want the bare id", out)
	}
	if _, ok := log.find("GET", "/workspaces/1/statuses"); ok {
		t.Errorf("-q should not fetch the status registry, recorded %v", log.all())
	}
}

// The empty rails: exit 1 with a message, per the grep convention.
func TestOrient_EmptyResults(t *testing.T) {
	base, _ := newDriftServer(t)

	// the fixture's only workspace has a task, so scope to a segment that holds none
	out, code := runCLIExit(t, base, "", "next", "-w", "auth", "-s", "999")
	if code != ExitEmpty {
		t.Errorf("exit = %d, want %d", code, ExitEmpty)
	}
	if !strings.Contains(out, "nothing") && !strings.Contains(out, "(") {
		t.Errorf("got %q, want an empty-set message", out)
	}
}

// tree walks tracks → segments → tasks and resolves status names for the render.
func TestTree_Wiring(t *testing.T) {
	base, log := newDriftServer(t)

	out, err := runCLI(t, base, "", "tree", "-w", "auth")
	if err != nil {
		t.Fatalf("tree: %v", err)
	}
	for _, want := range []string{"auth", "api", "seed"} {
		if !strings.Contains(out, want) {
			t.Errorf("got %q, want it to contain %q", out, want)
		}
	}
	for _, p := range []string{"/workspaces/1/tracks", "/tracks/10/segments", "/tracks/10/tasks"} {
		if _, ok := log.find("GET", p); !ok {
			t.Errorf("want GET %s, recorded %v", p, log.all())
		}
	}
}

// ls counts each workspace's tracks, which is why it reads tracks per workspace.
func TestLs_Wiring(t *testing.T) {
	base, _ := newDriftServer(t)

	out, code := runCLIExit(t, base, "", "ls")
	if code != ExitOK {
		t.Fatalf("exit = %d, want %d", code, ExitOK)
	}
	if !strings.Contains(out, "auth  (1 track)") {
		t.Errorf("got %q, want the singular track count", out)
	}
}
