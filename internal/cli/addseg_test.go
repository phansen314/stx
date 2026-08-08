package cli

import (
	"encoding/json"
	"strings"
	"testing"
)

// #93: `add -s` and `refile -s` are the same flag on the same concept, so they resolve the same
// way. -t scopes the name; a bare -s stays an id, since segment ids are global.
func TestAddSegment_ResolvesNameWithinTrack(t *testing.T) {
	base, log := newDriftServer(t)

	if _, err := runCLI(t, base, "", "add", "wired", "-w", "auth", "-t", "api", "-s", "phase-1"); err != nil {
		t.Fatalf("add -t -s <name>: %v", err)
	}
	// resolved to segment 21, so the task is created under the SEGMENT route, not the track's
	if _, ok := log.find("POST", "/segments/21/tasks"); !ok {
		t.Errorf("want POST /segments/21/tasks, recorded %v", log.all())
	}
	if _, ok := log.find("POST", "/tracks/10/tasks"); ok {
		t.Errorf("naming a segment must not fall back to the track root: %v", log.all())
	}
}

// The pre-#93 form — a bare numeric -s with no track — must keep working unchanged.
func TestAddSegment_BareIDStillWorks(t *testing.T) {
	base, log := newDriftServer(t)

	if _, err := runCLI(t, base, "", "add", "wired", "-w", "auth", "-s", "21"); err != nil {
		t.Fatalf("add -s <id>: %v", err)
	}
	if _, ok := log.find("POST", "/segments/21/tasks"); !ok {
		t.Errorf("want POST /segments/21/tasks, recorded %v", log.all())
	}
}

// -t alone still routes to the track, letting the daemon pick its root segment.
func TestAddSegment_TrackAloneUsesTheTrackRoute(t *testing.T) {
	base, log := newDriftServer(t)

	if _, err := runCLI(t, base, "", "add", "wired", "-w", "auth", "-t", "api"); err != nil {
		t.Fatalf("add -t: %v", err)
	}
	if _, ok := log.find("POST", "/tracks/10/tasks"); !ok {
		t.Errorf("want POST /tracks/10/tasks, recorded %v", log.all())
	}
}

// A name with no track has nothing to resolve against; the error says how to fix it rather than
// surfacing strconv's "invalid syntax", which is what #93 was actually reported as.
func TestAddSegment_NameWithoutTrackExplainsItself(t *testing.T) {
	base, log := newDriftServer(t)

	_, err := runCLI(t, base, "", "add", "wired", "-w", "auth", "-s", "phase-1")
	if err == nil {
		t.Fatal("want an error for a segment name with no track")
	}
	for _, want := range []string{"-t", "phase-1"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("err = %v, want it to mention %q", err, want)
		}
	}
	if strings.Contains(err.Error(), "invalid syntax") {
		t.Errorf("err = %v, must not leak strconv's parse error", err)
	}
	for _, r := range log.all() {
		if r.Method == "POST" {
			t.Errorf("must reject before writing, got %v", log.all())
		}
	}
}

func TestAddSegment_UnknownNameListsTheTrackSegments(t *testing.T) {
	base, _ := newDriftServer(t)

	_, err := runCLI(t, base, "", "add", "wired", "-w", "auth", "-t", "api", "-s", "nope")
	if err == nil || !strings.Contains(err.Error(), "phase-1") {
		t.Fatalf("err = %v, want it to list the track's segments", err)
	}
}

// Neither flag is still an error — a task has to be filed somewhere.
func TestAddSegment_RequiresATarget(t *testing.T) {
	base, log := newDriftServer(t)

	_, err := runCLI(t, base, "", "add", "wired", "-w", "auth")
	if err == nil || !strings.Contains(err.Error(), "segment") {
		t.Fatalf("err = %v, want it to name both flags", err)
	}
	if len(log.all()) > 0 {
		t.Errorf("must reject before dialing, got %v", log.all())
	}
}

// The two verbs now agree: the same -w/-t/-s triple lands a new task and moves an existing one
// into the very same segment. That equivalence is the whole point of #93.
func TestAddAndRefile_AgreeOnTheSameFlags(t *testing.T) {
	base, log := newDriftServer(t)

	if _, err := runCLI(t, base, "", "add", "wired", "-w", "auth", "-t", "api", "-s", "phase-1"); err != nil {
		t.Fatalf("add: %v", err)
	}
	addReq, ok := log.find("POST", "/segments/21/tasks")
	if !ok {
		t.Fatalf("add did not reach segment 21: %v", log.all())
	}
	log.reset()
	if _, err := runCLI(t, base, "", "refile", "5", "-w", "auth", "-t", "api", "-s", "phase-1"); err != nil {
		t.Fatalf("refile: %v", err)
	}
	refReq, ok := log.find("POST", "/tasks/5/segment")
	if !ok {
		t.Fatalf("refile did not run: %v", log.all())
	}
	var body map[string]any
	_ = json.Unmarshal([]byte(refReq.Body), &body)
	if body["segmentId"] != float64(21) {
		t.Errorf("refile resolved to %v but add resolved to segment 21 (%s)", body["segmentId"], addReq.Path)
	}
}
