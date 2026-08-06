package cli

import (
	"encoding/json"
	"strings"
	"testing"
)

// refile is `mv` on the filing axis: it must reach POST /tasks/{id}/segment with the CAS token and
// the resolved destination, never PATCH /tasks/{id} (which would make it just another edit).
func TestRefile_SendsSegmentAndVersion(t *testing.T) {
	base, log := newDriftServer(t)

	out, err := runCLI(t, base, "", "refile", "5", "-w", "auth", "-t", "api", "-s", "phase-1")
	if err != nil {
		t.Fatalf("refile: %v", err)
	}
	if want := "refiled #5 → api/phase-1"; strings.TrimSpace(out) != want {
		t.Errorf("text = %q, want %q", strings.TrimSpace(out), want)
	}
	req, ok := log.find("POST", "/tasks/5/segment")
	if !ok {
		t.Fatalf("no POST /tasks/5/segment recorded: %v", log.all())
	}
	var body map[string]any
	if err := json.Unmarshal([]byte(req.Body), &body); err != nil {
		t.Fatalf("body %q: %v", req.Body, err)
	}
	if body["segmentId"] != float64(21) {
		t.Errorf("segmentId = %v, want 21 (the fixture's phase-1)", body["segmentId"])
	}
	if body["expectedVersion"] != float64(1) {
		t.Errorf("expectedVersion = %v, want the task's current version", body["expectedVersion"])
	}
}

// Without -s the destination is the track's root segment — the same thing `add -t` means.
func TestRefile_DefaultsToTheTrackRoot(t *testing.T) {
	base, log := newDriftServer(t)

	out, err := runCLI(t, base, "", "refile", "5", "-w", "auth", "-t", "api")
	if err != nil {
		t.Fatalf("refile: %v", err)
	}
	if want := "refiled #5 → api"; strings.TrimSpace(out) != want {
		t.Errorf("text = %q, want %q (no segment suffix for the root)", strings.TrimSpace(out), want)
	}
	req, _ := log.find("POST", "/tasks/5/segment")
	var body map[string]any
	_ = json.Unmarshal([]byte(req.Body), &body)
	if body["segmentId"] != float64(20) {
		t.Errorf("segmentId = %v, want the root segment 20", body["segmentId"])
	}
}

// An unknown segment names the ones that exist, and nothing is written.
func TestRefile_UnknownSegmentNamesTheTrack(t *testing.T) {
	base, log := newDriftServer(t)

	_, err := runCLI(t, base, "", "refile", "5", "-w", "auth", "-t", "api", "-s", "nope")
	if err == nil || !strings.Contains(err.Error(), "phase-1") {
		t.Fatalf("err = %v, want it to list the track's segments", err)
	}
	if _, ok := log.find("POST", "/tasks/5/segment"); ok {
		t.Errorf("must reject before writing, got %v", log.all())
	}
}

// -t is what makes a destination resolvable, so it is required rather than defaulted.
func TestRefile_RequiresTrack(t *testing.T) {
	base, log := newDriftServer(t)

	_, err := runCLI(t, base, "", "refile", "5", "-w", "auth")
	if err == nil || !strings.Contains(err.Error(), "track") {
		t.Fatalf("err = %v, want a missing-track error", err)
	}
	if _, ok := log.find("POST", "/tasks/5/segment"); ok {
		t.Errorf("must reject before writing, got %v", log.all())
	}
}

// ids from stdin are the pipeline form: `stx next -q | stx refile - -t triage`.
func TestRefile_ReadsIDsFromStdin(t *testing.T) {
	base, log := newDriftServer(t)

	out, err := runCLI(t, base, "5\n", "refile", "-", "-w", "auth", "-t", "api", "-q")
	if err != nil {
		t.Fatalf("refile -: %v", err)
	}
	if strings.TrimSpace(out) != "5" {
		t.Errorf("-q = %q, want the refiled id", out)
	}
	if _, ok := log.find("POST", "/tasks/5/segment"); !ok {
		t.Errorf("want POST /tasks/5/segment, recorded %v", log.all())
	}
}

// segment edit is unversioned: the PATCH carries the changed fields and no expectedVersion.
func TestSegmentEdit_RenameAndReparent(t *testing.T) {
	base, log := newDriftServer(t)

	out, err := runCLI(t, base, "", "segment", "edit", "phase-1", "-w", "auth", "-t", "api",
		"--name", "phase-2", "--under", "root")
	if err != nil {
		t.Fatalf("segment edit: %v", err)
	}
	if want := "segment #21  phase-2"; strings.TrimSpace(out) != want {
		t.Errorf("text = %q, want %q", strings.TrimSpace(out), want)
	}
	req, ok := log.find("PATCH", "/segments/21")
	if !ok {
		t.Fatalf("no PATCH /segments/21 recorded: %v", log.all())
	}
	var body map[string]any
	_ = json.Unmarshal([]byte(req.Body), &body)
	if body["name"] != "phase-2" {
		t.Errorf("name = %v, want phase-2", body["name"])
	}
	if body["parentSegmentId"] != float64(20) {
		t.Errorf("parentSegmentId = %v, want the resolved root id 20", body["parentSegmentId"])
	}
	if _, ok := body["expectedVersion"]; ok {
		t.Errorf("segment rows are unversioned — no CAS token belongs on the wire: %q", req.Body)
	}
}

func TestSegmentEdit_RequiresAField(t *testing.T) {
	base, log := newDriftServer(t)

	_, err := runCLI(t, base, "", "segment", "edit", "phase-1", "-w", "auth", "-t", "api")
	if err == nil || !strings.Contains(err.Error(), "nothing to edit") {
		t.Fatalf("err = %v, want a nothing-to-edit error", err)
	}
	if _, ok := log.find("PATCH", "/segments/21"); ok {
		t.Errorf("must reject before writing, got %v", log.all())
	}
}

// status edit sends only the fields passed; kanbanOrder is an int, not the flag's string.
func TestStatusEdit_SendsOnlyChangedFields(t *testing.T) {
	base, log := newDriftServer(t)

	if _, err := runCLI(t, base, "", "status", "edit", "Backlog", "-w", "auth", "--name", "Todo"); err != nil {
		t.Fatalf("status edit: %v", err)
	}
	req, ok := log.find("PATCH", "/workspaces/1/statuses/100")
	if !ok {
		t.Fatalf("no PATCH recorded: %v", log.all())
	}
	var body map[string]any
	_ = json.Unmarshal([]byte(req.Body), &body)
	if body["name"] != "Todo" {
		t.Errorf("name = %v, want Todo", body["name"])
	}
	if _, ok := body["kanbanOrder"]; ok {
		t.Errorf("--order wasn't passed, so kanbanOrder must be absent: %q", req.Body)
	}

	log.reset()
	if _, err := runCLI(t, base, "", "status", "edit", "Backlog", "-w", "auth", "--order", "7"); err != nil {
		t.Fatalf("status edit --order: %v", err)
	}
	req, _ = log.find("PATCH", "/workspaces/1/statuses/100")
	_ = json.Unmarshal([]byte(req.Body), &body)
	if body["kanbanOrder"] != float64(7) {
		t.Errorf("kanbanOrder = %v, want 7", body["kanbanOrder"])
	}
}

func TestStatusEdit_RequiresAField(t *testing.T) {
	base, log := newDriftServer(t)

	_, err := runCLI(t, base, "", "status", "edit", "Backlog", "-w", "auth")
	if err == nil || !strings.Contains(err.Error(), "nothing to edit") {
		t.Fatalf("err = %v, want a nothing-to-edit error", err)
	}
	if _, ok := log.find("PATCH", "/workspaces/1/statuses/100"); ok {
		t.Errorf("must reject before writing, got %v", log.all())
	}
}

// status order resolves every positional through the registry and sends them as an id list.
func TestStatusOrder_SendsResolvedIDList(t *testing.T) {
	base, log := newDriftServer(t)

	out, err := runCLI(t, base, "", "status", "order", "Done", "Backlog", "-w", "auth")
	if err != nil {
		t.Fatalf("status order: %v", err)
	}
	if !strings.Contains(out, "→") {
		t.Errorf("text = %q, want the new order rendered", out)
	}
	req, ok := log.find("POST", "/workspaces/1/statuses/order")
	if !ok {
		t.Fatalf("no POST recorded: %v", log.all())
	}
	var body struct {
		StatusIDs []int64 `json:"statusIds"`
	}
	_ = json.Unmarshal([]byte(req.Body), &body)
	if len(body.StatusIDs) != 2 || body.StatusIDs[0] != 102 || body.StatusIDs[1] != 100 {
		t.Errorf("statusIds = %v, want [102 100] in the order given", body.StatusIDs)
	}
}

func TestStatusOrder_UnknownStatusNamesTheRegistry(t *testing.T) {
	base, log := newDriftServer(t)

	_, err := runCLI(t, base, "", "status", "order", "Backlog", "Nope", "-w", "auth")
	if err == nil || !strings.Contains(err.Error(), "Doing") {
		t.Fatalf("err = %v, want it to list the live statuses", err)
	}
	if _, ok := log.find("POST", "/workspaces/1/statuses/order"); ok {
		t.Errorf("must reject the whole call before writing, got %v", log.all())
	}
}

// kind rename resolves the old name through the registry and PATCHes by id, so tasks keep their kind.
func TestKindRename_ResolvesThenPatchesByID(t *testing.T) {
	base, log := newDriftServer(t)

	out, err := runCLI(t, base, "", "kind", "rename", "bug", "defect", "-w", "auth")
	if err != nil {
		t.Fatalf("kind rename: %v", err)
	}
	if want := "kind #200  defect"; strings.TrimSpace(out) != want {
		t.Errorf("text = %q, want %q", strings.TrimSpace(out), want)
	}
	req, ok := log.find("PATCH", "/workspaces/1/kinds/200")
	if !ok {
		t.Fatalf("no PATCH recorded: %v", log.all())
	}
	var body map[string]any
	_ = json.Unmarshal([]byte(req.Body), &body)
	if body["name"] != "defect" {
		t.Errorf("name = %v, want defect", body["name"])
	}
}
