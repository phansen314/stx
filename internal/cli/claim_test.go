package cli

import (
	"encoding/json"
	"strings"
	"testing"
)

// claim sends the agent id and a TTL in *seconds* — the flag is a Go duration, the wire is not.
func TestClaim_SendsAgentAndTTLSeconds(t *testing.T) {
	base, log := newDriftServer(t)

	out, err := runCLI(t, base, "", "claim", "5", "--as", "agent-1", "--ttl", "15m")
	if err != nil {
		t.Fatalf("claim: %v", err)
	}
	if !strings.Contains(out, "claimed #5 by agent-1") {
		t.Errorf("text = %q, want it to name the holder", strings.TrimSpace(out))
	}
	req, ok := log.find("POST", "/tasks/5/claim")
	if !ok {
		t.Fatalf("no POST /tasks/5/claim recorded: %v", log.all())
	}
	var body map[string]any
	if err := json.Unmarshal([]byte(req.Body), &body); err != nil {
		t.Fatalf("body %q: %v", req.Body, err)
	}
	if body["agentId"] != "agent-1" {
		t.Errorf("agentId = %v, want agent-1", body["agentId"])
	}
	if body["ttlSeconds"] != float64(900) {
		t.Errorf("ttlSeconds = %v, want 900 (15m as seconds)", body["ttlSeconds"])
	}
	// A lease is not a content edit, so no CAS token may ride along.
	if _, ok := body["expectedVersion"]; ok {
		t.Errorf("claim must not send expectedVersion: %q", req.Body)
	}
}

// The default TTL applies when --ttl is omitted, so `stx claim 5 --as x` is a complete call.
func TestClaim_DefaultTTL(t *testing.T) {
	base, log := newDriftServer(t)

	if _, err := runCLI(t, base, "", "claim", "5", "--as", "agent-1"); err != nil {
		t.Fatalf("claim: %v", err)
	}
	req, _ := log.find("POST", "/tasks/5/claim")
	var body map[string]any
	_ = json.Unmarshal([]byte(req.Body), &body)
	if body["ttlSeconds"] != float64(defaultTTL.Seconds()) {
		t.Errorf("ttlSeconds = %v, want the %s default", body["ttlSeconds"], defaultTTL)
	}
}

// A sub-second TTL truncates to zero seconds, which the daemon rejects — catch it client-side with
// a message that names the flag, and never dial.
func TestClaim_RejectsSubSecondTTL(t *testing.T) {
	base, log := newDriftServer(t)

	_, err := runCLI(t, base, "", "claim", "5", "--as", "agent-1", "--ttl", "100ms")
	if err == nil || !strings.Contains(err.Error(), "--ttl") {
		t.Fatalf("err = %v, want a --ttl error", err)
	}
	if _, ok := log.find("POST", "/tasks/5/claim"); ok {
		t.Errorf("must reject before writing, got %v", log.all())
	}
}

// A lease has to belong to someone: --as is required on claim/release, and --claim needs it too.
func TestClaim_RequiresAnAgent(t *testing.T) {
	base, log := newDriftServer(t)

	for _, tc := range []struct {
		name, want string
		args       []string
	}{
		{"claim", "as", []string{"claim", "5"}},
		{"release", "as", []string{"release", "5"}},
		{"next --claim", "--as", []string{"next", "-w", "auth", "--claim"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			log.reset()
			_, err := runCLI(t, base, "", tc.args...)
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("err = %v, want it to name %s", err, tc.want)
			}
			for _, r := range log.all() {
				if r.Method == "POST" {
					t.Errorf("must reject before writing, got %v", log.all())
				}
			}
		})
	}
}

func TestRelease_SendsAgent(t *testing.T) {
	base, log := newDriftServer(t)

	out, err := runCLI(t, base, "", "release", "5", "--as", "agent-1")
	if err != nil {
		t.Fatalf("release: %v", err)
	}
	if strings.TrimSpace(out) != "released #5" {
		t.Errorf("text = %q, want released #5", strings.TrimSpace(out))
	}
	req, ok := log.find("POST", "/tasks/5/release")
	if !ok {
		t.Fatalf("no release recorded: %v", log.all())
	}
	var body map[string]any
	_ = json.Unmarshal([]byte(req.Body), &body)
	if body["agentId"] != "agent-1" {
		t.Errorf("agentId = %v, want agent-1", body["agentId"])
	}
}

// --claim must go through the fused POST, not GET /next — that atomicity is the whole feature.
func TestNextClaim_UsesTheFusedEndpoint(t *testing.T) {
	base, log := newDriftServer(t)

	out, err := runCLI(t, base, "", "next", "-w", "auth", "--claim", "--as", "agent-1", "--ttl", "1h", "-q")
	if err != nil {
		t.Fatalf("next --claim: %v", err)
	}
	if strings.TrimSpace(out) != "5" {
		t.Errorf("-q = %q, want the claimed id", out)
	}
	req, ok := log.find("POST", "/next/claim")
	if !ok {
		t.Fatalf("want POST /next/claim, recorded %v", log.all())
	}
	if _, ok := log.find("GET", "/next"); ok {
		t.Errorf("--claim must not also issue the read-only GET: %v", log.all())
	}
	var body map[string]any
	_ = json.Unmarshal([]byte(req.Body), &body)
	if body["workspaceId"] != float64(1) || body["agentId"] != "agent-1" || body["ttlSeconds"] != float64(3600) {
		t.Errorf("body = %q, want ws 1 / agent-1 / 3600s", req.Body)
	}
}

// Without --claim, --as is just an identity on the read, so it rides the query string.
func TestNextAs_IsAQueryParam(t *testing.T) {
	base, log := newDriftServer(t)

	if _, err := runCLI(t, base, "", "next", "-w", "auth", "--as", "agent-1"); err != nil {
		t.Fatalf("next --as: %v", err)
	}
	req, ok := log.find("GET", "/next")
	if !ok {
		t.Fatalf("no GET /next recorded: %v", log.all())
	}
	if !strings.Contains(req.RawQuery, "as=agent-1") {
		t.Errorf("query = %q, want as=agent-1", req.RawQuery)
	}
	if _, ok := log.find("POST", "/next/claim"); ok {
		t.Errorf("--as alone must not claim anything: %v", log.all())
	}
}

func TestClaims_ListsLiveLeases(t *testing.T) {
	base, log := newDriftServer(t)

	out, code := runCLIExit(t, base, "", "claims", "-w", "auth")
	if code != ExitOK {
		t.Fatalf("exit = %d, want %d", code, ExitOK)
	}
	for _, want := range []string{"agent-1", "seed", "2099-01-01"} {
		if !strings.Contains(out, want) {
			t.Errorf("got %q, want it to contain %q", out, want)
		}
	}
	if _, ok := log.find("GET", "/workspaces/1/claims"); !ok {
		t.Errorf("want GET /workspaces/1/claims, recorded %v", log.all())
	}
	if q, _ := runCLIExit(t, base, "", "claims", "-w", "auth", "-q"); strings.TrimSpace(q) != "5" {
		t.Errorf("-q = %q, want the leased task id", q)
	}
}
