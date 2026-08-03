package client

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

// readServer records the path+query of each request and replies with `body`, so a test can assert
// the URL a read method built. client_test.go covers the writes and the error envelope; the reads
// had no coverage at all.
func readServer(t *testing.T, body any) (*Client, *string) {
	t.Helper()
	var got string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = r.URL.RequestURI()
		_ = json.NewEncoder(w).Encode(body)
	}))
	t.Cleanup(srv.Close)
	return New(srv.URL), &got
}

func TestReads_URLConstruction(t *testing.T) {
	cases := map[string]struct {
		call func(*Client) error
		want string
	}{
		"ListWorkspaces": {func(c *Client) error { _, e := c.ListWorkspaces(); return e }, "/workspaces"},
		"Tracks":         {func(c *Client) error { _, e := c.Tracks(1); return e }, "/workspaces/1/tracks"},
		"Statuses":       {func(c *Client) error { _, e := c.Statuses(1); return e }, "/workspaces/1/statuses"},
		"Kinds":          {func(c *Client) error { _, e := c.Kinds(1); return e }, "/workspaces/1/kinds"},
		"Transitions":    {func(c *Client) error { _, e := c.Transitions(1); return e }, "/workspaces/1/transitions"},
		"RelatesKinds":   {func(c *Client) error { _, e := c.RelatesKinds(1); return e }, "/workspaces/1/relates-kinds"},
		"Edges":          {func(c *Client) error { _, e := c.Edges(1); return e }, "/workspaces/1/edges"},
		"Segments":       {func(c *Client) error { _, e := c.Segments(10); return e }, "/tracks/10/segments"},
		"TrackTasks":     {func(c *Client) error { _, e := c.TrackTasks(10); return e }, "/tracks/10/tasks"},
		"TaskDetail":     {func(c *Client) error { _, e := c.TaskDetail(5); return e }, "/tasks/5"},
		"Changes":        {func(c *Client) error { _, e := c.Changes(); return e }, "/changes"},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			c, got := readServer(t, map[string]any{"items": []any{}})
			if err := tc.call(c); err != nil {
				t.Fatalf("%s: %v", name, err)
			}
			if *got != tc.want {
				t.Errorf("requested %q, want %q", *got, tc.want)
			}
		})
	}
}

// A nil NextParams field omits its query param entirely — the daemon distinguishes absent from
// zero, so sending `limit=0` would be a different (and wrong) query.
func TestNext_OmitsNilParams(t *testing.T) {
	id := func(v int64) *int64 { return &v }
	cases := map[string]struct {
		p    NextParams
		want string
	}{
		"workspace only":     {NextParams{Workspace: 1}, "/next?workspace=1"},
		"track":              {NextParams{Workspace: 1, Track: id(10)}, "/next?track=10&workspace=1"},
		"segment":            {NextParams{Workspace: 1, Segment: id(20)}, "/next?segment=20&workspace=1"},
		"kind":               {NextParams{Workspace: 1, Kind: id(200)}, "/next?kind=200&workspace=1"},
		"limit":              {NextParams{Workspace: 1, Limit: id(3)}, "/next?limit=3&workspace=1"},
		"zero is not absent": {NextParams{Workspace: 1, Limit: id(0)}, "/next?limit=0&workspace=1"},
		"all": {
			NextParams{Workspace: 1, Track: id(10), Segment: id(20), Kind: id(200), Limit: id(3)},
			"/next?kind=200&limit=3&segment=20&track=10&workspace=1",
		},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			c, got := readServer(t, map[string]any{"items": []any{}})
			if _, err := c.Next(tc.p); err != nil {
				t.Fatalf("Next: %v", err)
			}
			if *got != tc.want {
				t.Errorf("requested %q, want %q", *got, tc.want)
			}
		})
	}
}

// Statuses sorts by (kanbanOrder, id) regardless of the daemon's row order. `done` picks the first
// terminal status off this list, so an unsorted read would silently pick the wrong one.
func TestStatuses_SortedByKanbanOrderThenID(t *testing.T) {
	c, _ := readServer(t, map[string]any{"items": []map[string]any{
		{"id": 102, "name": "Done", "kanbanOrder": 2, "terminal": true},
		{"id": 100, "name": "Backlog", "kanbanOrder": 0},
		{"id": 104, "name": "Blocked", "kanbanOrder": 1},
		{"id": 101, "name": "Doing", "kanbanOrder": 1},
	}})
	got, err := c.Statuses(1)
	if err != nil {
		t.Fatalf("Statuses: %v", err)
	}
	want := []string{"Backlog", "Doing", "Blocked", "Done"} // order 1 ties break by id: 101 < 104
	for i, name := range want {
		if got[i].Name != name {
			t.Errorf("position %d = %s, want %s (full: %v)", i, got[i].Name, name, got)
		}
	}
}

// The {"items":[…]} envelope is unwrapped; a non-list read is decoded whole.
func TestReads_UnwrapAndDecode(t *testing.T) {
	c, _ := readServer(t, map[string]any{"items": []map[string]any{{"id": 7, "name": "auth"}}})
	wss, err := c.ListWorkspaces()
	if err != nil {
		t.Fatalf("ListWorkspaces: %v", err)
	}
	if len(wss) != 1 || wss[0].ID != 7 || wss[0].Name != "auth" {
		t.Errorf("got %+v, want one workspace #7 auth", wss)
	}

	c2, _ := readServer(t, map[string]any{"seq": 42, "schema": 3})
	ch, err := c2.Changes()
	if err != nil {
		t.Fatalf("Changes: %v", err)
	}
	if ch.Seq != 42 || ch.Schema != 3 {
		t.Errorf("got %+v, want seq 42 / schema 3", ch)
	}
}
