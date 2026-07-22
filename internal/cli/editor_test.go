package cli

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/spf13/cobra"
)

// fakeBin creates an executable stub named `name` in a fresh dir and points PATH at it, so the
// no-env PATH probe is deterministic instead of depending on what's installed here.
func fakeBin(t *testing.T, names ...string) {
	t.Helper()
	dir := t.TempDir()
	for _, n := range names {
		if err := os.WriteFile(filepath.Join(dir, n), []byte("#!/bin/sh\n"), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("PATH", dir)
}

// The wait flag is the whole ballgame for GUI editors: without it they fork, stx reads the buffer
// back instantly and every edit looks "unchanged".
func TestEditorCommand_Resolution(t *testing.T) {
	cases := map[string]struct {
		env      map[string]string
		onPath   []string
		wantArgv []string
		wantGUI  bool
	}{
		"probes zed when nothing is set": {
			onPath: []string{"zed", "vi"}, wantArgv: []string{"zed", "-n", "-w", "/tmp/b.md"}, wantGUI: true,
		},
		"bare code gets new-window + wait": {
			env: map[string]string{"EDITOR": "code"}, onPath: []string{"code"},
			wantArgv: []string{"code", "-n", "-w", "/tmp/b.md"}, wantGUI: true,
		},
		"user flags are never rewritten": {
			env: map[string]string{"EDITOR": "code --wait"}, onPath: []string{"code"},
			wantArgv: []string{"code", "--wait", "/tmp/b.md"}, wantGUI: true,
		},
		"missing wait is added to user flags": {
			env: map[string]string{"EDITOR": "zed -n"}, onPath: []string{"zed"},
			wantArgv: []string{"zed", "-n", "-w", "/tmp/b.md"}, wantGUI: true,
		},
		"STX_EDITOR wins over EDITOR": {
			env:      map[string]string{"STX_EDITOR": "zed -w", "EDITOR": "vim"},
			wantArgv: []string{"zed", "-w", "/tmp/b.md"}, wantGUI: true,
		},
		"terminal editors are left alone": {
			env: map[string]string{"EDITOR": "vim"}, wantArgv: []string{"vim", "/tmp/b.md"},
		},
		"absolute path still matches the table": {
			env:      map[string]string{"EDITOR": "/usr/bin/code"},
			wantArgv: []string{"/usr/bin/code", "-n", "-w", "/tmp/b.md"}, wantGUI: true,
		},
		"shell metacharacters go through sh -c": {
			env:      map[string]string{"EDITOR": `code --wait "$FOO"`},
			wantArgv: []string{"sh", "-c", `code --wait "$FOO" "$1"`, "sh", "/tmp/b.md"},
		},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			for _, k := range []string{"STX_EDITOR", "VISUAL", "EDITOR"} {
				t.Setenv(k, "")
			}
			for k, v := range tc.env {
				t.Setenv(k, v)
			}
			if tc.onPath != nil {
				fakeBin(t, tc.onPath...)
			}
			argv, gui, err := editorCommand("/tmp/b.md")
			if err != nil {
				t.Fatalf("editorCommand: %v", err)
			}
			if strings.Join(argv, " ") != strings.Join(tc.wantArgv, " ") {
				t.Fatalf("want %v, got %v", tc.wantArgv, argv)
			}
			if gui != tc.wantGUI {
				t.Fatalf("gui: want %v, got %v", tc.wantGUI, gui)
			}
		})
	}
}

func TestEditorCommand_NoneFound(t *testing.T) {
	for _, k := range []string{"STX_EDITOR", "VISUAL", "EDITOR"} {
		t.Setenv(k, "")
	}
	fakeBin(t) // empty PATH dir
	if _, _, err := editorCommand("/tmp/b.md"); err == nil || !strings.Contains(err.Error(), "no editor") {
		t.Fatalf("want a no-editor error, got %v", err)
	}
}

// editServer serves the one task the editor tests touch and records every PATCH body.
func editServer(t *testing.T) (base string, patches *[]map[string]any) {
	t.Helper()
	recorded := []map[string]any{}
	task := map[string]any{
		"id": 5, "workspaceId": 1, "segmentId": 20, "statusId": 100,
		"title": "seed", "description": "before\n", "version": 1,
	}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(200) })
	mux.HandleFunc("GET /tasks/5", func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{
			"task": task, "blocksIn": []any{}, "blocksOut": []any{}, "relates": []any{},
		})
	})
	mux.HandleFunc("PATCH /tasks/5", func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		b, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(b, &body)
		recorded = append(recorded, body)
		_ = json.NewEncoder(w).Encode(task)
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return srv.URL, &recorded
}

// stubEditor replaces the launch with a callback that gets the buffer path.
func stubEditor(fn func(path string) error) func() {
	orig := runEditor
	runEditor = func(_ *cobra.Command, path string) error { return fn(path) }
	return func() { runEditor = orig }
}

// The round trip: whatever the editor left in the file becomes the description, verbatim.
func TestEdit_EditorWritesDescription(t *testing.T) {
	base, patches := editServer(t)
	body := "rewritten\n\n## notes\n- markdown survives\n"
	defer stubEditor(func(path string) error {
		seed, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		if string(seed) != "before\n" {
			t.Fatalf("buffer should be seeded with the current description, got %q", seed)
		}
		return os.WriteFile(path, []byte(body), 0o600)
	})()

	out, err := runCLI(t, base, "", "edit", "5", "-e", "-q")
	if err != nil {
		t.Fatalf("edit -e: %v", err)
	}
	if out != "5\n" {
		t.Fatalf("-q should print just the id, got %q", out)
	}
	if len(*patches) != 1 {
		t.Fatalf("want one PATCH, got %d", len(*patches))
	}
	// one trailing newline trimmed, everything else byte-for-byte
	if got := (*patches)[0]["description"]; got != strings.TrimSuffix(body, "\n") {
		t.Fatalf("description round-tripped as %q", got)
	}
}

// Closing the editor without touching anything must not write — and must not look like a failure.
func TestEdit_EditorUnchangedDoesNotWrite(t *testing.T) {
	base, patches := editServer(t)
	defer stubEditor(func(string) error { return nil })()

	out, err := runCLI(t, base, "", "edit", "5", "-e")
	if err != nil {
		t.Fatalf("edit -e: %v", err)
	}
	if !strings.Contains(out, "unchanged #5") {
		t.Fatalf("want an unchanged line, got %q", out)
	}
	if len(*patches) != 0 {
		t.Fatalf("nothing changed — no PATCH should have been sent, got %d", len(*patches))
	}
}

// A non-zero editor exit aborts: no write, and the error surfaces (exit 2 via Run).
func TestEdit_EditorFailureAborts(t *testing.T) {
	base, patches := editServer(t)
	defer stubEditor(func(string) error { return errors.New("editor zed -n -w: exit status 1") })()

	_, err := runCLI(t, base, "", "edit", "5", "-e")
	if err == nil || !strings.Contains(err.Error(), "exit status 1") {
		t.Fatalf("want the editor failure, got %v", err)
	}
	if len(*patches) != 0 {
		t.Fatalf("aborted edit must not write, got %d PATCHes", len(*patches))
	}
}

// An editor that dies *after* the user saved must leave the text on disk.
func TestEdit_EditorCrashAfterSaveKeepsBuffer(t *testing.T) {
	base, _ := editServer(t)
	var buf string
	defer stubEditor(func(path string) error {
		buf = path
		if err := os.WriteFile(path, []byte("typed before the crash\n"), 0o600); err != nil {
			return err
		}
		return errors.New("editor zed -n -w: signal: killed")
	})()

	_, err := runCLI(t, base, "", "edit", "5", "-e")
	if err == nil || !strings.Contains(err.Error(), buf) {
		t.Fatalf("the error should name the retained buffer %q, got %v", buf, err)
	}
	raw, statErr := os.ReadFile(buf)
	if statErr != nil || string(raw) != "typed before the crash\n" {
		t.Fatalf("saved text should survive the crash: %v / %q", statErr, raw)
	}
	os.Remove(buf)
}

// The buffer is left on disk only when the daemon rejects the write, and the path is named.
func TestEdit_KeepsBufferWhenTheWriteFails(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(200) })
	mux.HandleFunc("GET /tasks/5", func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{
			"task": map[string]any{"id": 5, "workspaceId": 1, "title": "seed", "version": 1},
		})
	})
	mux.HandleFunc("PATCH /tasks/5", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(409)
		_, _ = w.Write([]byte(`{"error":"VersionConflict","entity":"task","id":5}`))
	})
	srv := httptest.NewServer(mux)
	defer srv.Close()

	var buf string
	defer stubEditor(func(path string) error {
		buf = path
		return os.WriteFile(path, []byte("worth keeping\n"), 0o600)
	})()

	_, err := runCLI(t, srv.URL, "", "edit", "5", "-e")
	if err == nil || !strings.Contains(err.Error(), buf) {
		t.Fatalf("the error should name the retained buffer %q, got %v", buf, err)
	}
	if _, statErr := os.Stat(buf); statErr != nil {
		t.Fatalf("buffer should still exist after a failed write: %v", statErr)
	}
	os.Remove(buf)
}

// Guard rails: ids from stdin and explicit field flags both keep the editor out of the way.
func TestEdit_EditorGuardRails(t *testing.T) {
	base, patches := editServer(t)
	defer stubEditor(func(string) error { t.Fatal("editor must not open here"); return nil })()

	if _, err := runCLI(t, base, "5\n", "edit", "-", "-e"); err == nil ||
		!strings.Contains(err.Error(), "one task") {
		t.Fatalf("want a single-id error for `edit - -e`, got %v", err)
	}
	if _, err := runCLI(t, base, "", "edit", "5", "--desc", "flags win", "-e"); err != nil {
		t.Fatalf("field flags should take the normal path: %v", err)
	}
	if len(*patches) != 1 || (*patches)[0]["description"] != "flags win" {
		t.Fatalf("want the flag value written, got %v", *patches)
	}
	// non-tty, no -e: the old error, never a hang
	if _, err := runCLI(t, base, "", "edit", "5"); err == nil ||
		!strings.Contains(err.Error(), "nothing to edit") {
		t.Fatalf("want the nothing-to-edit error, got %v", err)
	}
}

// ── add -e ───────────────────────────────────────────────────────────────────

// addServer records the created task's body.
func addServer(t *testing.T) (base string, posts *[]map[string]any) {
	t.Helper()
	recorded := []map[string]any{}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(200) })
	mux.HandleFunc("GET /workspaces", func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{"items": []map[string]any{{"id": 1, "name": "auth"}}})
	})
	mux.HandleFunc("GET /workspaces/1/tracks", func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{
			"items": []map[string]any{{"id": 10, "workspaceId": 1, "name": "api"}}})
	})
	mux.HandleFunc("POST /tracks/10/tasks", func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		b, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(b, &body)
		recorded = append(recorded, body)
		_ = json.NewEncoder(w).Encode(map[string]any{"id": 7, "workspaceId": 1, "title": "seed", "version": 1})
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return srv.URL, &recorded
}

func TestAdd_EditorWritesDescription(t *testing.T) {
	base, posts := addServer(t)
	defer stubEditor(func(path string) error {
		seed, _ := os.ReadFile(path)
		if len(seed) != 0 {
			t.Fatalf("a new task's buffer starts empty, got %q", seed)
		}
		return os.WriteFile(path, []byte("written in the editor\n"), 0o600)
	})()

	out, err := runCLI(t, base, "", "add", "seed", "-w", "auth", "-t", "api", "-e", "-q")
	if err != nil {
		t.Fatalf("add -e: %v", err)
	}
	if out != "7\n" {
		t.Fatalf("want the new id, got %q", out)
	}
	if len(*posts) != 1 || (*posts)[0]["description"] != "written in the editor" {
		t.Fatalf("description not carried into the create: %v", *posts)
	}
}

// Unlike edit, add never implies the editor — a bare `stx add "x"` must stay a one-liner.
func TestAdd_EditorNotImplied(t *testing.T) {
	base, posts := addServer(t)
	defer stubEditor(func(string) error { t.Fatal("editor must not open for a bare add"); return nil })()

	if _, err := runCLI(t, base, "", "add", "seed", "-w", "auth", "-t", "api"); err != nil {
		t.Fatalf("bare add: %v", err)
	}
	if len(*posts) != 1 {
		t.Fatalf("want one create, got %d", len(*posts))
	}
	_, err := runCLI(t, base, "", "add", "seed", "-w", "auth", "-t", "api", "-e", "--desc", "x")
	if err == nil || !strings.Contains(err.Error(), "mutually exclusive") {
		t.Fatalf("--desc with -e should error, got %v", err)
	}
}

// ── meta set -e ──────────────────────────────────────────────────────────────

// metaServer serves a task carrying metadata and records the blobs written back.
func metaServer(t *testing.T, metadata string) (base string, patches *[]map[string]any) {
	t.Helper()
	recorded := []map[string]any{}
	task := map[string]any{"id": 5, "workspaceId": 1, "title": "seed", "version": 1, "metadataJson": metadata}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(200) })
	mux.HandleFunc("GET /tasks/5", func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{
			"task": task, "blocksIn": []any{}, "blocksOut": []any{}, "relates": []any{}})
	})
	mux.HandleFunc("PATCH /tasks/5", func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		b, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(b, &body)
		recorded = append(recorded, body)
		_ = json.NewEncoder(w).Encode(task)
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return srv.URL, &recorded
}

// Without --string the buffer is JSON: seeded pretty-printed, parsed strictly on the way back.
func TestMetaSet_EditorJSON(t *testing.T) {
	base, patches := metaServer(t, `{"config":{"n":1}}`)
	defer stubEditor(func(path string) error {
		seed, _ := os.ReadFile(path)
		if !strings.Contains(string(seed), "\"n\": 1") {
			t.Fatalf("buffer should be seeded with pretty JSON, got %q", seed)
		}
		if !strings.HasSuffix(path, ".json") {
			t.Fatalf("JSON mode should use a .json buffer, got %q", path)
		}
		return os.WriteFile(path, []byte("{\"n\": 2, \"deep\": [1,2]}\n"), 0o600)
	})()

	if _, err := runCLI(t, base, "", "meta", "set", "--task", "5", "config", "-e"); err != nil {
		t.Fatalf("meta set -e: %v", err)
	}
	if len(*patches) != 1 {
		t.Fatalf("want one PATCH, got %d", len(*patches))
	}
	var blob map[string]any
	if err := json.Unmarshal([]byte((*patches)[0]["metadataJson"].(string)), &blob); err != nil {
		t.Fatalf("blob: %v", err)
	}
	cfg, ok := blob["config"].(map[string]any)
	if !ok || cfg["n"] != float64(2) {
		t.Fatalf("value not stored as JSON: %v", blob)
	}
}

// A JSON typo must not silently become one long string — the buffer is kept and named.
func TestMetaSet_EditorRejectsBadJSON(t *testing.T) {
	base, patches := metaServer(t, `{}`)
	var buf string
	defer stubEditor(func(path string) error {
		buf = path
		return os.WriteFile(path, []byte("{oops\n"), 0o600)
	})()

	_, err := runCLI(t, base, "", "meta", "set", "--task", "5", "config", "-e")
	if err == nil || !strings.Contains(err.Error(), "not valid JSON") || !strings.Contains(err.Error(), buf) {
		t.Fatalf("want a JSON error naming the buffer, got %v", err)
	}
	if len(*patches) != 0 {
		t.Fatalf("nothing should have been written, got %d", len(*patches))
	}
	os.Remove(buf)
}

// --string edits the raw text — the sane way to write a long note — and stores it verbatim.
func TestMetaSet_EditorString(t *testing.T) {
	base, patches := metaServer(t, `{"note":"old text"}`)
	defer stubEditor(func(path string) error {
		seed, _ := os.ReadFile(path)
		if string(seed) != "old text\n" {
			t.Fatalf("--string should seed the raw value, got %q", seed)
		}
		if !strings.HasSuffix(path, ".md") {
			t.Fatalf("--string should use a .md buffer, got %q", path)
		}
		return os.WriteFile(path, []byte("# heading\n\nnot JSON at all\n"), 0o600)
	})()

	if _, err := runCLI(t, base, "", "meta", "set", "--task", "5", "note", "-e", "--string"); err != nil {
		t.Fatalf("meta set -e --string: %v", err)
	}
	var blob map[string]any
	_ = json.Unmarshal([]byte((*patches)[0]["metadataJson"].(string)), &blob)
	if blob["note"] != "# heading\n\nnot JSON at all" {
		t.Fatalf("raw text not stored verbatim: %q", blob["note"])
	}
}

func TestMetaSet_EditorGuardRails(t *testing.T) {
	base, patches := metaServer(t, `{"k":"v"}`)
	// closing untouched writes nothing
	restore := stubEditor(func(string) error { return nil })
	out, err := runCLI(t, base, "", "meta", "set", "--task", "5", "k", "-e")
	restore()
	if err != nil || !strings.Contains(out, "unchanged k") {
		t.Fatalf("want an unchanged line, got %q / %v", out, err)
	}
	if len(*patches) != 0 {
		t.Fatalf("unchanged must not write, got %d", len(*patches))
	}
	// a value AND -e is ambiguous; neither is incomplete
	defer stubEditor(func(string) error { t.Fatal("editor must not open"); return nil })()
	if _, err := runCLI(t, base, "", "meta", "set", "--task", "5", "k", "v", "-e"); err == nil {
		t.Fatal("value + -e should error")
	}
	if _, err := runCLI(t, base, "", "meta", "set", "--task", "5", "k"); err == nil {
		t.Fatal("no value and no -e should error")
	}
}
