package cli

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"reflect"
	"testing"

	"github.com/phansen314/stx/internal/client"
)

// fakePickClient serves the reads the builders touch (workspaces, tracks, statuses, track tasks)
// from a tiny in-memory fixture: workspace "auth" (id 1), track "api" (id 10), task #5 "Backlog".
func fakePickClient(t *testing.T) *client.Client {
	t.Helper()
	items := func(v any) map[string]any { return map[string]any{"items": v} }
	mux := http.NewServeMux()
	write := func(w http.ResponseWriter, v any) { _ = json.NewEncoder(w).Encode(v) }
	mux.HandleFunc("GET /workspaces", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]map[string]any{{"id": 1, "name": "auth"}}))
	})
	mux.HandleFunc("GET /workspaces/1/tracks", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]map[string]any{{"id": 10, "workspaceId": 1, "name": "api"}}))
	})
	mux.HandleFunc("GET /workspaces/1/statuses", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]map[string]any{{"id": 100, "name": "Backlog", "kanbanOrder": 0}}))
	})
	mux.HandleFunc("GET /tracks/10/tasks", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]map[string]any{{"id": 5, "workspaceId": 1, "statusId": 100, "title": "seed"}}))
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return client.New(srv.URL)
}

// The pure argv assemblers are the contract every builder ends in — assert exact argv.
func TestArgvAssemblers(t *testing.T) {
	tests := []struct {
		name string
		got  []string
		want []string
	}{
		{"mv", argvMv("42", "doing"), []string{"mv", "42", "doing"}},
		{"done", argvDone("7"), []string{"done", "7"}},
		{"show", argvShow("7"), []string{"show", "7"}},
		{"next", argvNext("auth"), []string{"next", "-w", "auth"}},
		{"tree", argvTree("auth"), []string{"tree", "-w", "auth"}},
		{"add-bare", argvAdd("write docs", "auth", "api", nil),
			[]string{"add", "write docs", "-w", "auth", "-t", "api"}},
		{"add-extras", argvAdd("t", "auth", "api", []kv{{"--status", "todo"}, {"--priority", "3"}}),
			[]string{"add", "t", "-w", "auth", "-t", "api", "--status", "todo", "--priority", "3"}},
		{"edit", argvEdit("9", []kv{{"--title", "new"}, {"--priority", "2"}}),
			[]string{"edit", "9", "--title", "new", "--priority", "2"}},

		// archive: --yes is appended only for the cascading types.
		{"archive-task", argvArchive("task", "5"), []string{"archive", "task", "5"}},
		{"archive-segment", argvArchive("segment", "20"), []string{"archive", "segment", "20"}},
		{"archive-track", argvArchive("track", "10"), []string{"archive", "track", "10", "--yes"}},
		{"archive-ws", argvArchive("workspace", "1"), []string{"archive", "workspace", "1", "--yes"}},

		// meta: sub, then key/value, then the target flags.
		{"meta-ls-task", argvMeta("ls", nil, []string{"--task", "5"}),
			[]string{"meta", "ls", "--task", "5"}},
		{"meta-get-ws", argvMeta("get", []string{"k"}, []string{"-w", "auth"}),
			[]string{"meta", "get", "k", "-w", "auth"}},
		{"meta-set-task", argvMeta("set", []string{"k", "v"}, []string{"--task", "5"}),
			[]string{"meta", "set", "k", "v", "--task", "5"}},
		{"meta-del-track", argvMeta("del", []string{"k"}, []string{"-w", "auth", "--track", "api"}),
			[]string{"meta", "del", "k", "-w", "auth", "--track", "api"}},
	}
	for _, tt := range tests {
		if !reflect.DeepEqual(tt.got, tt.want) {
			t.Errorf("%s: got %v, want %v", tt.name, tt.got, tt.want)
		}
	}
}

// buildDone drives the pickers behind stubbed fzf/stdin — asserts the full flow yields the argv.
func TestBuildDone_StubbedPickers(t *testing.T) {
	c := fakePickClient(t)
	restore := stubFzf(func(lines []string, o fzfOpts) ([]string, error) {
		switch o.prompt {
		case "workspace> ":
			return []string{"auth"}, nil // value column = ws name
		case "task> ":
			return []string{"5"}, nil // value column = task id
		default:
			t.Fatalf("unexpected fzf prompt %q", o.prompt)
			return nil, nil
		}
	})
	defer restore()

	argv, err := buildDone(c)
	if err != nil {
		t.Fatalf("buildDone: %v", err)
	}
	if want := []string{"done", "5"}; !reflect.DeepEqual(argv, want) {
		t.Errorf("got %v, want %v", argv, want)
	}
}

// Esc at the workspace pane aborts with errPickCancelled, which runPick swallows to nil.
func TestBuildCancel(t *testing.T) {
	c := fakePickClient(t)
	restore := stubFzf(func([]string, fzfOpts) ([]string, error) { return nil, errPickCancelled })
	defer restore()

	if _, err := buildShow(c); err != errPickCancelled {
		t.Fatalf("want errPickCancelled, got %v", err)
	}
	if swallowCancel(errPickCancelled) != nil {
		t.Errorf("swallowCancel should map cancel to nil")
	}
}

// stubFzf swaps the package fzfRun var and returns a restore func.
func stubFzf(fn func([]string, fzfOpts) ([]string, error)) func() {
	orig := fzfRun
	fzfRun = fn
	return func() { fzfRun = orig }
}
