package cli

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"reflect"
	"sort"
	"testing"
)

// daemon down (unreachable base-url) → every completion func yields no candidates, never errors.
func TestCompletion_DaemonDownDegradesToNoOp(t *testing.T) {
	defer setBaseURL("http://127.0.0.1:1")() // nothing listening → Ping fails

	if got := allTaskCandidates(); got != nil {
		t.Errorf("allTaskCandidates want nil, got %v", got)
	}
	if got := legalStatusCandidates("5"); got != nil {
		t.Errorf("legalStatusCandidates want nil, got %v", got)
	}
	if got, dir := completeWorkspaceFlag(nil, nil, ""); got != nil || dir != noComp {
		t.Errorf("completeWorkspaceFlag want (nil, noComp), got (%v, %v)", got, dir)
	}
	if got := allWorkspaceCandidates(); got != nil {
		t.Errorf("allWorkspaceCandidates want nil, got %v", got)
	}
	if got := allTrackCandidates(); got != nil {
		t.Errorf("allTrackCandidates want nil, got %v", got)
	}
	if got := allSegmentCandidates(); got != nil {
		t.Errorf("allSegmentCandidates want nil, got %v", got)
	}
}

// archive: arg0 → the four entity types; arg1 → live ids of the chosen type.
func TestCompleteArchiveArgs(t *testing.T) {
	defer setBaseURL(completionServer(t))()

	types, _ := completeArchiveArgs(nil, nil, "")
	if want := []string{"task", "segment", "track", "workspace"}; !reflect.DeepEqual(types, want) {
		t.Fatalf("arg0 types: got %v, want %v", types, want)
	}
	tracks, _ := completeArchiveArgs(nil, []string{"track"}, "")
	if want := []string{"10\tauth / api"}; !reflect.DeepEqual(tracks, want) {
		t.Fatalf("arg1 track ids: got %v, want %v", tracks, want)
	}
	if got, _ := completeArchiveArgs(nil, []string{"task", "5"}, ""); got != nil {
		t.Fatalf("arg2 offers nothing, got %v", got)
	}
}

func TestMetaKeysFromJSON(t *testing.T) {
	got := metaKeysFromJSON(`{"owner":"alice","prio":3}`)
	sort.Strings(got)
	if want := []string{"owner", "prio"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("keys: got %v, want %v", got, want)
	}
	if got := metaKeysFromJSON(""); got != nil {
		t.Fatalf("empty metadata → nil, got %v", got)
	}
	if got := metaKeysFromJSON("not json"); got != nil {
		t.Fatalf("bad json → nil, got %v", got)
	}
}

// mv's second positional offers only the legal target statuses for the chosen task.
func TestCompleteMvArgs_LegalStatuses(t *testing.T) {
	defer setBaseURL(completionServer(t))()

	// arg0 present → complete arg1 = legal transitions from task #5's status (100 → 101 "Doing").
	got, dir := completeMvArgs(nil, []string{"5"}, "")
	if dir != noComp {
		t.Fatalf("directive: %v", dir)
	}
	if want := []string{"Doing"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("legal statuses: got %v, want %v", got, want)
	}
}

func TestCompleteTaskArg_FirstPositionalOnly(t *testing.T) {
	defer setBaseURL(completionServer(t))()

	got, _ := completeTaskArg(nil, nil, "")
	if want := []string{"5\tseed"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("task candidates: got %v, want %v", got, want)
	}
	// a second positional offers nothing (id already chosen).
	if got, _ := completeTaskArg(nil, []string{"5"}, ""); got != nil {
		t.Fatalf("want nil for 2nd positional, got %v", got)
	}
}

// setBaseURL swaps the package flagBaseURL and returns a restore func.
func setBaseURL(u string) func() {
	orig := flagBaseURL
	flagBaseURL = u
	return func() { flagBaseURL = orig }
}

// completionServer serves /health plus the reads the completion funcs touch, and returns its URL.
func completionServer(t *testing.T) string {
	t.Helper()
	items := func(v any) map[string]any { return map[string]any{"items": v} }
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
			{"id": 100, "name": "Backlog", "kanbanOrder": 0},
			{"id": 101, "name": "Doing", "kanbanOrder": 1},
		}))
	})
	mux.HandleFunc("GET /workspaces/1/transitions", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]map[string]any{{"id": 1, "workspaceId": 1, "fromStatusId": 100, "toStatusId": 101}}))
	})
	mux.HandleFunc("GET /tracks/10/tasks", func(w http.ResponseWriter, _ *http.Request) {
		write(w, items([]map[string]any{{"id": 5, "workspaceId": 1, "statusId": 100, "title": "seed"}}))
	})
	mux.HandleFunc("GET /tasks/5", func(w http.ResponseWriter, _ *http.Request) {
		write(w, map[string]any{"task": map[string]any{"id": 5, "workspaceId": 1, "statusId": 100, "title": "seed"}})
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return srv.URL
}
