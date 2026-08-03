package cli

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// blockerServer serves a populated blocker graph, which the shared drift fixture deliberately does
// not have (its one task is unblocked, so the two reads stay consistent there).
// #7 is blocked by #6 (depth 1) and #4 (depth 2); #4 blocks two paths but appears once.
func blockerServer(t *testing.T) (string, *reqLog) {
	t.Helper()
	write := func(w http.ResponseWriter, v any) { _ = json.NewEncoder(w).Encode(v) }
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(200) })
	mux.HandleFunc("GET /tasks/7", func(w http.ResponseWriter, _ *http.Request) {
		write(w, map[string]any{
			"task":     map[string]any{"id": 7, "workspaceId": 1, "title": "ship it", "statusId": 100},
			"blocksIn": []any{}, "blocksOut": []any{}, "relates": []any{},
		})
	})
	mux.HandleFunc("GET /workspaces/1/statuses", func(w http.ResponseWriter, _ *http.Request) {
		write(w, map[string]any{"items": []map[string]any{{"id": 100, "name": "Backlog"}}})
	})
	mux.HandleFunc("GET /tasks/7/blockers", func(w http.ResponseWriter, r *http.Request) {
		rows := []map[string]any{
			{"id": 6, "title": "write migration", "priority": 2, "statusId": 100, "depth": 1},
			{"id": 4, "title": "design schema", "priority": 0, "statusId": 100, "depth": 2},
		}
		if r.URL.Query().Get("depth") == "1" {
			rows = rows[:1]
		}
		write(w, map[string]any{"items": rows})
	})
	// #4 is at the head of the chain — nothing blocks it
	mux.HandleFunc("GET /tasks/4", func(w http.ResponseWriter, _ *http.Request) {
		write(w, map[string]any{
			"task":     map[string]any{"id": 4, "workspaceId": 1, "title": "design schema", "statusId": 100},
			"blocksIn": []any{}, "blocksOut": []any{}, "relates": []any{},
		})
	})
	mux.HandleFunc("GET /tasks/4/blockers", func(w http.ResponseWriter, _ *http.Request) {
		write(w, map[string]any{"items": []map[string]any{}})
	})

	log := &reqLog{}
	srv := httptest.NewServer(record(log, mux))
	t.Cleanup(srv.Close)
	return srv.URL, log
}

// The text render is a depth-layered list: shallowest first, indent = minimum hop count.
func TestBlockers_DepthLayeredRender(t *testing.T) {
	base, _ := blockerServer(t)

	out, code := runCLIExit(t, base, "", "blockers", "7")
	if code != ExitOK {
		t.Fatalf("exit = %d, want %d", code, ExitOK)
	}
	lines := strings.Split(strings.TrimRight(out, "\n"), "\n")
	if len(lines) != 3 {
		t.Fatalf("got %d lines, want a header + 2 blockers:\n%s", len(lines), out)
	}
	if !strings.Contains(lines[0], "#7  blocked by 2 unfinished tasks") {
		t.Errorf("header = %q", lines[0])
	}
	if !strings.Contains(lines[1], "write migration") || !strings.Contains(lines[2], "design schema") {
		t.Errorf("wrong order — depth 1 must come first:\n%s", out)
	}
	if indent := func(s string) int { return len(s) - len(strings.TrimLeft(s, " ")) }; indent(lines[2]) <= indent(lines[1]) {
		t.Errorf("depth 2 should be indented deeper than depth 1:\n%s", out)
	}
}

// -q emits the BLOCKER ids, not the queried id. That divergence from `show -q` is the point:
// `stx blockers 7 -q | stx done -` clears the path.
func TestBlockers_QuietEmitsBlockerIDs(t *testing.T) {
	base, log := blockerServer(t)

	out, _ := runCLIExit(t, base, "", "blockers", "7", "-q")
	if out != "6\n4\n" {
		t.Errorf("got %q, want the blocker ids 6 and 4", out)
	}
	if _, ok := log.find("GET", "/workspaces/1/statuses"); ok {
		t.Errorf("-q should skip the status registry, recorded %v", log.all())
	}
}

// Nothing blocking is an empty result set: exit 1 with a plain statement, not an error and not
// silence. `if stx blockers 4 -q >/dev/null` therefore reads as "is it blocked?".
func TestBlockers_NothingBlockingIsExitOne(t *testing.T) {
	base, _ := blockerServer(t)

	out, code := runCLIExit(t, base, "", "blockers", "4")
	if code != ExitEmpty {
		t.Errorf("exit = %d, want %d", code, ExitEmpty)
	}
	if !strings.Contains(out, "nothing is blocking it") {
		t.Errorf("got %q, want the not-blocked line", out)
	}

	q, code := runCLIExit(t, base, "", "blockers", "4", "-q")
	if q != "" || code != ExitEmpty {
		t.Errorf("-q = %q (exit %d), want no output and exit 1", q, code)
	}
}

func TestBlockers_DepthFlag(t *testing.T) {
	base, log := blockerServer(t)

	out, err := runCLI(t, base, "", "blockers", "7", "--depth", "1")
	if err != nil {
		t.Fatalf("blockers --depth: %v", err)
	}
	if strings.Contains(out, "design schema") {
		t.Errorf("--depth 1 should stop after the direct blockers:\n%s", out)
	}
	req, _ := log.find("GET", "/tasks/7/blockers")
	if req.RawQuery != "depth=1" {
		t.Errorf("query = %q, want depth=1", req.RawQuery)
	}

	// without the flag the param is omitted entirely — the daemon owns the default
	log.reset()
	if _, err := runCLI(t, base, "", "blockers", "7"); err != nil {
		t.Fatalf("blockers: %v", err)
	}
	if req, _ := log.find("GET", "/tasks/7/blockers"); req.RawQuery != "" {
		t.Errorf("query = %q, want no depth param", req.RawQuery)
	}
}

func TestBlockers_JSONAndBatch(t *testing.T) {
	base, log := blockerServer(t)

	js, err := runCLI(t, base, "", "blockers", "7", "--json")
	if err != nil {
		t.Fatalf("blockers --json: %v", err)
	}
	for _, want := range []string{`"depth": 1`, `"depth": 2`, `"id": 6`} {
		if !strings.Contains(js, want) {
			t.Errorf("--json %q missing %q", js, want)
		}
	}

	log.reset()
	out, _ := runCLIExit(t, base, "7\n4\n", "blockers", "-", "-q")
	if out != "6\n4\n" {
		t.Errorf("batch -q = %q, want the union of blockers (7's two, 4's none)", out)
	}
	for _, p := range []string{"/tasks/7/blockers", "/tasks/4/blockers"} {
		if _, ok := log.find("GET", p); !ok {
			t.Errorf("want GET %s, recorded %v", p, log.all())
		}
	}
}
