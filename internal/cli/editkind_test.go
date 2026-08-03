package cli

import (
	"encoding/json"
	"strings"
	"testing"
)

// --kind resolves through the workspace registry and lands on the wire as kindId.
func TestEditKind_ResolvesToKindID(t *testing.T) {
	base, log := newDriftServer(t)

	if _, err := runCLI(t, base, "", "edit", "5", "--kind", "bug"); err != nil {
		t.Fatalf("edit --kind: %v", err)
	}
	req, ok := log.find("PATCH", "/tasks/5")
	if !ok {
		t.Fatalf("no PATCH /tasks/5 recorded: %v", log.all())
	}
	var body map[string]any
	if err := json.Unmarshal([]byte(req.Body), &body); err != nil {
		t.Fatalf("body %q: %v", req.Body, err)
	}
	if got := body["kindId"]; got != float64(200) {
		t.Errorf("kindId = %v, want 200 (the fixture's `bug`)", got)
	}
	if _, ok := body["clearKind"]; ok {
		t.Errorf("--kind must not send clearKind, got %q", req.Body)
	}
}

// --no-kind sends clearKind, which is the only way to unset a kind (nothing else clears it).
func TestEditNoKind_SendsClearKind(t *testing.T) {
	base, log := newDriftServer(t)

	if _, err := runCLI(t, base, "", "edit", "5", "--no-kind"); err != nil {
		t.Fatalf("edit --no-kind: %v", err)
	}
	req, _ := log.find("PATCH", "/tasks/5")
	var body map[string]any
	_ = json.Unmarshal([]byte(req.Body), &body)
	if body["clearKind"] != true {
		t.Errorf("clearKind = %v, want true (body %q)", body["clearKind"], req.Body)
	}
	if _, ok := body["kindId"]; ok {
		t.Errorf("--no-kind must not send kindId, got %q", req.Body)
	}
}

func TestEditKind_MutuallyExclusiveWithNoKind(t *testing.T) {
	base, log := newDriftServer(t)

	_, err := runCLI(t, base, "", "edit", "5", "--kind", "bug", "--no-kind")
	if err == nil || !strings.Contains(err.Error(), "mutually exclusive") {
		t.Fatalf("err = %v, want a mutual-exclusion error", err)
	}
	if _, ok := log.find("PATCH", "/tasks/5"); ok {
		t.Errorf("must reject before writing, got %v", log.all())
	}
}

// An unknown kind is an error naming the live kinds — not a silent no-op edit.
func TestEditKind_UnknownNamesTheRegistry(t *testing.T) {
	base, _ := newDriftServer(t)

	_, err := runCLI(t, base, "", "edit", "5", "--kind", "nope")
	if err == nil || !strings.Contains(err.Error(), "bug") {
		t.Fatalf("err = %v, want it to list the available kinds", err)
	}
}

// The regression this whole refactor guards: `--kind`/`--no-kind` count as field flags, so they
// must NOT fall through to the $EDITOR branch (which, non-interactive, is the "nothing to edit"
// error). Before hasField existed, the predicate was len(changes)==0 and --kind would have.
func TestEditKind_CountsAsAFieldFlag(t *testing.T) {
	base, _ := newDriftServer(t)

	for _, args := range [][]string{
		{"edit", "5", "--kind", "bug"},
		{"edit", "5", "--no-kind"},
	} {
		if _, err := runCLI(t, base, "", args...); err != nil {
			t.Errorf("%v: %v", args, err)
		}
	}
	// and the inverse still holds: no field flag at all, non-interactive → the old error
	_, err := runCLI(t, base, "", "edit", "5")
	if err == nil || !strings.Contains(err.Error(), "nothing to edit") {
		t.Errorf("err = %v, want the nothing-to-edit error", err)
	}
}

// Ids from stdin may span workspaces, so the kind name is resolved per task — a TaskDetail and a
// Kinds read for each id, not one lookup reused.
func TestEditKind_ResolvesPerID(t *testing.T) {
	base, log := newDriftServer(t)

	if _, err := runCLI(t, base, "5\n5\n", "edit", "-", "--kind", "bug"); err != nil {
		t.Fatalf("edit - --kind: %v", err)
	}
	var kinds, patches int
	for _, r := range log.all() {
		switch {
		case r.Method == "GET" && r.Path == "/workspaces/1/kinds":
			kinds++
		case r.Method == "PATCH" && r.Path == "/tasks/5":
			patches++
		}
	}
	if patches != 2 {
		t.Errorf("PATCH count = %d, want 2", patches)
	}
	if kinds != 2 {
		t.Errorf("kind lookups = %d, want 2 (one per id — they may span workspaces)", kinds)
	}
}
