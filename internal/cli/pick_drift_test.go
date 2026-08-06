package cli

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
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

// recordedReq is one request the CLI made against the fixture. Asserting on these is how a test
// checks what a command *sent* — the flag→wire mapping — not merely that RunE returned nil.
type recordedReq struct{ Method, Path, RawQuery, Body string }

// reqLog records every request the fixture served, in order. Mutex-guarded because httptest
// serves each request on its own goroutine.
type reqLog struct {
	mu   sync.Mutex
	reqs []recordedReq
}

func (l *reqLog) add(r recordedReq) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.reqs = append(l.reqs, r)
}

// all returns a snapshot of everything recorded so far.
func (l *reqLog) all() []recordedReq {
	l.mu.Lock()
	defer l.mu.Unlock()
	return append([]recordedReq(nil), l.reqs...)
}

// reset drops the log, so one fixture can be reused across sub-tests that each assert on the
// requests *they* made.
func (l *reqLog) reset() {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.reqs = nil
}

// find returns the first recorded request matching method+path.
func (l *reqLog) find(method, path string) (recordedReq, bool) {
	for _, r := range l.all() {
		if r.Method == method && r.Path == path {
			return r, true
		}
	}
	return recordedReq{}, false
}

// record wraps a handler so every request lands in the log before being served.
func record(l *reqLog, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		r.Body = io.NopCloser(bytes.NewReader(body)) // hand the handler an unread body
		l.add(recordedReq{Method: r.Method, Path: r.URL.Path, RawQuery: r.URL.RawQuery, Body: string(body)})
		next.ServeHTTP(w, r)
	})
}

// driftServer is newDriftServer for callers that only need the base URL.
func driftServer(t *testing.T) string {
	t.Helper()
	base, _ := newDriftServer(t)
	return base
}

// newDriftServer serves every read+write the builders' commands touch, from one fixture:
// workspace auth(1) → track api(10) → root segment(20) → task #5 (status Backlog 100).
// Statuses: Backlog 100 (default), Doing 101, Done 102 (terminal); transitions 100→101, 100→102.
// Kinds: bug(200). Task #5 is unblocked, so it is what `next` returns and what `blockers` finds
// nothing for — the fixture stays internally consistent with the next ⟺ blockers identity. Tests
// that need a populated blocker graph build their own server.
//
// The returned *reqLog holds every request served, so a test can assert the wire form of what a
// command sent (query params, JSON bodies) rather than just that it succeeded.
func newDriftServer(t *testing.T) (string, *reqLog) {
	t.Helper()
	items := func(v any) map[string]any { return map[string]any{"items": v} }
	task := map[string]any{"id": 5, "workspaceId": 1, "segmentId": 20, "statusId": 100, "title": "seed", "version": 1}
	write := func(w http.ResponseWriter, v any) { _ = json.NewEncoder(w).Encode(v) }

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(200) })
	// versions match the write entities below, so a read-modify-write CAS round-trips coherently.
	mux.HandleFunc("GET /workspaces", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]map[string]any{{"id": 1, "name": "auth", "version": 1}}))
	})
	mux.HandleFunc("GET /workspaces/1/tracks", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]map[string]any{{"id": 10, "workspaceId": 1, "name": "api", "version": 1}}))
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
	// root(20) plus one nested segment(21) — enough for the refile/reparent paths to have a
	// non-root destination to name. Pickers take the first line, so builders still land on root.
	mux.HandleFunc("GET /tracks/10/segments", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]map[string]any{
			{"id": 20, "workspaceId": 1, "trackId": 10, "isRoot": true, "name": "root"},
			{"id": 21, "workspaceId": 1, "trackId": 10, "parentSegmentId": 20, "name": "phase-1"},
		}))
	})
	// honors ?status= (the kanban read) — #5 sits in Backlog(100), so any other filter is empty.
	mux.HandleFunc("GET /tracks/10/tasks", func(w http.ResponseWriter, r *http.Request) {
		if s := r.URL.Query().Get("status"); s != "" && s != "100" {
			write(w, items([]map[string]any{}))
			return
		}
		write(w, items([]map[string]any{task}))
	})
	mux.HandleFunc("GET /tasks/5", func(w http.ResponseWriter, _ *http.Request) {
		write(w, map[string]any{"task": task, "blocksIn": []any{}, "blocksOut": []any{}, "relates": []any{}})
	})
	// #5 is in `next`, so nothing blocks it — the inverse read is empty here by construction.
	mux.HandleFunc("GET /tasks/5/blockers", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]map[string]any{}))
	})
	mux.HandleFunc("GET /changes", func(w http.ResponseWriter, _ *http.Request) {
		write(w, map[string]any{"seq": 7, "schema": 1})
	})
	// honors the scope filters against the single seeded task, so a test can tell a filter that
	// reached the daemon from one the CLI dropped.
	mux.HandleFunc("GET /next", func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		for param, seeded := range map[string]string{"track": "10", "segment": "20", "kind": "200"} {
			if v := q.Get(param); v != "" && v != seeded {
				write(w, items([]map[string]any{}))
				return
			}
		}
		write(w, items([]map[string]any{{"id": 5, "title": "seed", "statusId": 100, "segmentId": 20}}))
	})
	mux.HandleFunc("GET /workspaces/1/relates-kinds", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]string{}))
	})
	mux.HandleFunc("GET /workspaces/1/edges", func(w http.ResponseWriter, _ *http.Request) {
		write(w, map[string]any{"blocks": []any{}, "relates": []any{}})
	})
	// one live lease, so `release`'s builder (which picks from real claims) has something to pick
	mux.HandleFunc("GET /workspaces/1/claims", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]map[string]any{
			{"id": 5, "title": "seed", "claimedBy": "agent-1", "claimedUntil": "2099-01-01 00:00:00"},
		}))
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
	mux.HandleFunc("POST /tasks/5/segment", ok(task))
	leased := map[string]any{
		"id": 5, "workspaceId": 1, "segmentId": 20, "statusId": 100, "title": "seed", "version": 1,
		"claimedBy": "agent-1", "claimedUntil": "2099-01-01 00:00:00",
	}
	mux.HandleFunc("POST /tasks/5/claim", ok(leased))
	mux.HandleFunc("POST /tasks/5/release", ok(task))
	mux.HandleFunc("POST /next/claim", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]map[string]any{
			{"id": 5, "title": "seed", "statusId": 100, "segmentId": 20, "claimedBy": "agent-1", "claimedUntil": "2099-01-01 00:00:00"},
		}))
	})
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
	mux.HandleFunc("POST /workspaces/1/statuses/100/default", ok(map[string]any{"id": 100, "workspaceId": 1, "name": "Backlog", "isDefault": true}))
	mux.HandleFunc("POST /workspaces/1/statuses/100/archive", ok(map[string]any{}))
	mux.HandleFunc("POST /workspaces/1/kinds/200/archive", ok(map[string]any{}))
	mux.HandleFunc("POST /segments/20/archive", ok(map[string]any{}))
	mux.HandleFunc("POST /tracks/10/archive", ok(map[string]any{}))
	mux.HandleFunc("POST /workspaces/1/archive", ok(map[string]any{}))
	// the CAS PATCHes echo the merged entity with a bumped version, so a rename test can assert
	// on the rendered name rather than on the request alone.
	mux.HandleFunc("PATCH /workspaces/1", patched(ws))
	mux.HandleFunc("PATCH /tracks/10", patched(track))
	// the unversioned edits (segment/status/kind) PATCH the same way, minus the CAS token.
	mux.HandleFunc("PATCH /segments/20", patched(seg))
	mux.HandleFunc("PATCH /segments/21", patched(map[string]any{"id": 21, "workspaceId": 1, "trackId": 10, "name": "phase-1"}))
	mux.HandleFunc("PATCH /workspaces/1/statuses/100", patched(map[string]any{"id": 100, "workspaceId": 1, "name": "Backlog", "kanbanOrder": 0, "isDefault": true}))
	mux.HandleFunc("PATCH /workspaces/1/kinds/200", patched(map[string]any{"id": 200, "workspaceId": 1, "name": "bug"}))
	mux.HandleFunc("POST /workspaces/1/statuses/order", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]map[string]any{
			{"id": 100, "name": "Backlog", "kanbanOrder": 0, "isDefault": true},
			{"id": 101, "name": "Doing", "kanbanOrder": 1},
			{"id": 102, "name": "Done", "kanbanOrder": 2, "terminal": true},
		}))
	})

	log := &reqLog{}
	srv := httptest.NewServer(record(log, mux))
	t.Cleanup(srv.Close)
	return srv.URL, log
}

// patched returns a handler that merges the request's name/description over `base` and bumps
// version — enough for the client's read-modify-write + render path to behave like the daemon's.
func patched(base map[string]any) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		out := make(map[string]any, len(base)+2)
		for k, v := range base {
			out[k] = v
		}
		for _, k := range []string{"name", "description", "metadataJson"} {
			if v, ok := body[k]; ok {
				out[k] = v
			}
		}
		if v, ok := base["version"].(int); ok {
			out["version"] = v + 1
		}
		_ = json.NewEncoder(w).Encode(out)
	}
}
