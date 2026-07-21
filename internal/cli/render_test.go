package cli

import (
	"testing"

	"github.com/phansen314/stx/internal/api"
)

func TestRenderFrontier(t *testing.T) {
	sn := map[int64]string{1: "Backlog"}
	items := []api.FrontierItem{
		{ID: 2, Title: "design schema", Priority: 2, StatusID: 1},
		{ID: 3, Title: "x", Priority: 0, StatusID: 1},
	}
	want := "   2  P2  [Backlog]  design schema\n" +
		"   3      [Backlog]  x"
	if got := renderFrontier(items, sn); got != want {
		t.Fatalf("frontier mismatch:\n--want--\n%q\n--got--\n%q", want, got)
	}
	if got := renderFrontier(nil, sn); got != "(nothing ready)" {
		t.Fatalf("empty frontier: %q", got)
	}
}

func TestRenderTaskDetail(t *testing.T) {
	d := api.TaskDetail{
		Task:      api.Task{ID: 2, Title: "design schema", StatusID: 1, Priority: 2, Description: "do it"},
		BlocksOut: []int64{3},
		Relates:   []api.RelatesEdge{{Kind: "relates_to", OtherTaskID: 3, Outgoing: false}},
	}
	sn := map[int64]string{1: "Backlog"}
	want := "#2  design schema\n" +
		"  status: Backlog    kind: -    priority: P2\n" +
		"  description: do it\n" +
		"  blocks: #3\n" +
		"  relates: relates_to←#3"
	if got := renderTaskDetail(d, sn, map[int64]string{}); got != want {
		t.Fatalf("detail mismatch:\n--want--\n%q\n--got--\n%q", want, got)
	}
}

func TestRenderTree(t *testing.T) {
	root := int64(1)
	ws := api.Workspace{ID: 2, Name: "gophase1"}
	blocks := []trackBlock{{
		Track: api.Track{ID: 3, Name: "build"},
		Segments: []api.Segment{
			{ID: 1, IsRoot: true},
			{ID: 4, Name: "api", ParentSegmentID: &root},
		},
		Tasks: []api.Task{
			{ID: 2, Title: "design schema", SegmentID: 1, StatusID: 1, Priority: 2},
			{ID: 5, Title: "api handler", SegmentID: 4, StatusID: 1, Priority: 0},
		},
	}}
	sn := map[int64]string{1: "Backlog"}
	want := "gophase1 (#2)\n" +
		"  ▸ build (#3)\n" +
		"    - #2 P2 [Backlog] design schema\n" +
		"    ▫ api (#4)\n" +
		"      - #5    [Backlog] api handler"
	if got := renderTree(ws, blocks, sn); got != want {
		t.Fatalf("tree mismatch:\n--want--\n%q\n--got--\n%q", want, got)
	}
}

func TestRenderTreeEmpty(t *testing.T) {
	got := renderTree(api.Workspace{ID: 9, Name: "empty"}, nil, nil)
	if got != "empty (#9)\n  (empty)" {
		t.Fatalf("empty tree: %q", got)
	}
}
