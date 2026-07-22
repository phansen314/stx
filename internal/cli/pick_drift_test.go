package cli

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/phansen314/stx/internal/client"
	"github.com/spf13/cobra"
)

// TestBuilders_NoDrift is the guard against a builder drifting from its real command's required
// args. For every entry in `builders` it stubs the fzf/readline pickers to choose valid live
// values from a fake daemon, then executes the assembled argv through the *actual* cobra command.
// If a builder omits or mis-shapes a required arg, the real command rejects it — cobra's ExactArgs
// or the RunE-level `-w`/`-t` checks return an error, and Execute (hence this test) fails. The
// builder's requiredness is thus tied to the command itself, not hand-asserted here.
func TestBuilders_NoDrift(t *testing.T) {
	base := driftServer(t)
	defer setBaseURL(base)()

	// Pick the first candidate at every pane; free text is non-empty. Enough to drive each builder
	// down its happy path so the only thing that can fail Execute is a missing/invalid arg.
	defer stubFzf(func(lines []string, _ fzfOpts) ([]string, error) {
		if len(lines) == 0 {
			return nil, errPickCancelled
		}
		return fzfRunReal(lines[:1]), nil // value = first line's value column
	})()
	// "1" is non-empty (satisfies text/name/key prompts) and parses as an int (status --order).
	origPrompt := promptLine
	promptLine = func(string) (string, error) { return "1", nil }
	defer func() { promptLine = origPrompt }()
	// Picking the first candidate everywhere lands on the "$EDITOR" choice wherever a builder
	// offers one, so no builder may actually spawn an editor here. Leaving the buffer untouched
	// takes each command's "unchanged" path.
	origEditor := runEditor
	runEditor = func(*cobra.Command, string) error { return nil }
	defer func() { runEditor = origEditor }()

	for name, build := range builders {
		t.Run(name, func(t *testing.T) {
			argv, err := build(client.New(base))
			if err != nil {
				t.Fatalf("builder returned %v", err)
			}
			root := NewRootCmd()
			root.SetArgs(append(argv, "--base-url", base))
			root.SetOut(io.Discard)
			root.SetErr(io.Discard)
			if err := root.Execute(); err != nil {
				t.Fatalf("assembled `stx %v` rejected by its command: %v", argv, err)
			}
		})
	}
}

// fzfRunReal mimics the real fzfRun's value extraction (first TAB-field) without spawning fzf.
func fzfRunReal(lines []string) []string {
	out := make([]string, 0, len(lines))
	for _, l := range lines {
		for i := 0; i < len(l); i++ {
			if l[i] == '\t' {
				out = append(out, l[:i])
				break
			}
		}
	}
	if len(out) == 0 && len(lines) > 0 {
		out = append(out, lines[0]) // no TAB → whole line is the value
	}
	return out
}

// driftServer serves every read+write the 7 builders' commands touch, from one fixture:
// workspace auth(1) → track api(10) → root segment(20) → task #5 (status Backlog 100).
// Statuses: Backlog 100 (default), Doing 101, Done 102 (terminal); transitions 100→101, 100→102.
func driftServer(t *testing.T) string {
	t.Helper()
	items := func(v any) map[string]any { return map[string]any{"items": v} }
	task := map[string]any{"id": 5, "workspaceId": 1, "segmentId": 20, "statusId": 100, "title": "seed", "version": 1}
	write := func(w http.ResponseWriter, v any) { _ = json.NewEncoder(w).Encode(v) }

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(200) })
	mux.HandleFunc("GET /workspaces", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]map[string]any{{"id": 1, "name": "auth"}}))
	})
	mux.HandleFunc("GET /workspaces/1/tracks", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]map[string]any{{"id": 10, "workspaceId": 1, "name": "api"}}))
	})
	mux.HandleFunc("GET /workspaces/1/statuses", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]map[string]any{
			{"id": 100, "name": "Backlog", "kanbanOrder": 0, "isDefault": true},
			{"id": 101, "name": "Doing", "kanbanOrder": 1},
			{"id": 102, "name": "Done", "kanbanOrder": 2, "terminal": true},
		}))
	})
	mux.HandleFunc("GET /workspaces/1/transitions", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]map[string]any{
			{"id": 1, "workspaceId": 1, "fromStatusId": 100, "toStatusId": 101},
			{"id": 2, "workspaceId": 1, "fromStatusId": 100, "toStatusId": 102},
		}))
	})
	mux.HandleFunc("GET /workspaces/1/kinds", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]map[string]any{{"id": 200, "workspaceId": 1, "name": "bug"}}))
	})
	mux.HandleFunc("GET /tracks/10/segments", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]map[string]any{{"id": 20, "workspaceId": 1, "trackId": 10, "isRoot": true, "name": "root"}}))
	})
	mux.HandleFunc("GET /tracks/10/tasks", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]map[string]any{task}))
	})
	mux.HandleFunc("GET /tasks/5", func(w http.ResponseWriter, _ *http.Request) {
		write(w, map[string]any{"task": task, "blocksIn": []any{}, "blocksOut": []any{}, "relates": []any{}})
	})
	mux.HandleFunc("GET /next", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]map[string]any{{"id": 5, "title": "seed", "statusId": 100, "segmentId": 20}}))
	})
	mux.HandleFunc("GET /workspaces/1/relates-kinds", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]string{}))
	})
	mux.HandleFunc("GET /workspaces/1/edges", func(w http.ResponseWriter, _ *http.Request) {
		write(w, map[string]any{"blocks": []any{}, "relates": []any{}})
	})
	// writes: return a plausible entity/edge; the fixture is enough for RunE to complete.
	ws := map[string]any{"id": 1, "name": "auth", "version": 1}
	track := map[string]any{"id": 10, "workspaceId": 1, "name": "api", "version": 1}
	seg := map[string]any{"id": 20, "workspaceId": 1, "trackId": 10, "isRoot": true, "name": "root"}
	status := map[string]any{"id": 103, "workspaceId": 1, "name": "New", "kanbanOrder": 3}
	kind := map[string]any{"id": 201, "workspaceId": 1, "name": "chore"}
	transition := map[string]any{"id": 3, "workspaceId": 1, "fromStatusId": 100, "toStatusId": 100}
	ok := func(v any) http.HandlerFunc {
		return func(w http.ResponseWriter, _ *http.Request) { write(w, v) }
	}
	mux.HandleFunc("POST /tracks/10/tasks", ok(task))
	mux.HandleFunc("POST /tasks/5/status", ok(task))
	mux.HandleFunc("PATCH /tasks/5", ok(task))
	mux.HandleFunc("POST /blocks", ok(map[string]any{}))
	mux.HandleFunc("POST /blocks/archive", ok(map[string]any{}))
	mux.HandleFunc("POST /relates", ok(map[string]any{}))
	mux.HandleFunc("POST /relates/archive", ok(map[string]any{}))
	mux.HandleFunc("POST /tasks/5/archive", ok(map[string]any{}))
	mux.HandleFunc("POST /workspaces", ok(ws))
	mux.HandleFunc("POST /workspaces/1/tracks", ok(track))
	mux.HandleFunc("POST /tracks/10/segments", ok(seg))
	mux.HandleFunc("POST /workspaces/1/statuses", ok(status))
	mux.HandleFunc("POST /workspaces/1/kinds", ok(kind))
	mux.HandleFunc("POST /workspaces/1/transitions", ok(transition))

	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return srv.URL
}
