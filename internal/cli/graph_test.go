package cli

import (
	"strings"
	"testing"
)

func TestRenderGraphDot(t *testing.T) {
	nodes := []graphNode{
		{ID: 16, Title: "schema", Status: "Backlog", Terminal: false},
		{ID: 17, Title: "done thing", Status: "Done", Terminal: true},
	}
	blocks := [][]int64{{16, 17}}
	relates := [][]any{{int64(17), int64(16), "relates_to"}}
	// Default style: terminal node filled green, relates dashed. Attribute formatting is normalized
	// to key="value" (deterministic order), so this differs cosmetically from the pre-config render
	// but is semantically identical (dot parses both the same).
	want := `digraph "ws" {
  rankdir=LR;
  node [style="rounded" shape="box"];
  "16" [label="#16 schema"];
  "17" [label="#17 done thing" style="rounded,filled" fillcolor="#cde7cd"];
  "16" -> "17";
  "17" -> "16" [label="relates_to" style="dashed"];
}`
	if got := renderGraphDot("ws", false, "none", nodes, blocks, relates, defaultGraphStyle(), nil); got != want {
		t.Fatalf("dot mismatch:\n--want--\n%s\n--got--\n%s", want, got)
	}
}

func TestRenderGraphDotVertical(t *testing.T) {
	nodes := []graphNode{{ID: 1, Title: "a", Status: "Backlog"}}
	d := defaultGraphStyle()
	if got := renderGraphDot("ws", false, "none", nodes, nil, nil, d, nil); !strings.Contains(got, "rankdir=LR;") {
		t.Fatalf("default should be LR:\n%s", got)
	}
	if got := renderGraphDot("ws", true, "none", nodes, nil, nil, d, nil); !strings.Contains(got, "rankdir=TB;") {
		t.Fatalf("--vertical should be TB:\n%s", got)
	}
}

func TestRenderGraphDotStyled(t *testing.T) {
	style := defaultGraphStyle()
	style.Status = map[string]attrs{"done": {"fillcolor": "#00ff00"}} // case-insensitive match
	style.Kind = map[string]attrs{"bug": {"color": "red"}}
	nodes := []graphNode{
		{ID: 1, Title: "fix", Status: "Done", Terminal: true, Kind: "bug"},
	}
	got := renderGraphDot("ws", false, "none", nodes, nil, nil, style, nil)
	// status fill overrides the terminal default; kind adds a border; both coexist.
	if !strings.Contains(got, `fillcolor="#00ff00"`) {
		t.Fatalf("status color not applied:\n%s", got)
	}
	if !strings.Contains(got, `color="red"`) {
		t.Fatalf("kind color not applied:\n%s", got)
	}
}

func TestRenderGraphDotClusterTrack(t *testing.T) {
	nodes := []graphNode{
		{ID: 1, Title: "a", Status: "Backlog", TrackID: 10, TrackName: "auth"},
		{ID: 2, Title: "b", Status: "Backlog", TrackID: 20, TrackName: "billing"},
	}
	got := renderGraphDot("ws", false, "track", nodes, nil, nil, defaultGraphStyle(), nil)
	for _, want := range []string{"subgraph cluster_track_10 {", `label="auth";`, "subgraph cluster_track_20 {", `label="billing";`} {
		if !strings.Contains(got, want) {
			t.Fatalf("missing %q in:\n%s", want, got)
		}
	}
}

func TestResolveGraphOutput(t *testing.T) {
	cases := []struct {
		name              string
		out               string
		svg, png, pdf     bool
		wantPath, wantFmt string
		wantErr           bool
	}{
		{name: "flag appends", out: "report", png: true, wantPath: "report.png", wantFmt: "png"},
		{name: "no flag defaults svg", out: "report", wantPath: "report.svg", wantFmt: "svg"},
		{name: "extension used", out: "report.png", wantPath: "report.png", wantFmt: "png"},
		{name: "flag overrides extension", out: "report.svg", png: true, wantPath: "report.png", wantFmt: "png"},
		{name: "flag discards bogus ext", out: "report.jpeg", png: true, wantPath: "report.png", wantFmt: "png"},
		{name: "unsupported ext no flag", out: "report.jpeg", wantErr: true},
		{name: "PNG ext lower-cased", out: "report.PNG", wantPath: "report.PNG", wantFmt: "png"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			path, format, err := resolveGraphOutput(c.out, c.svg, c.png, c.pdf)
			if c.wantErr {
				if err == nil {
					t.Fatalf("expected error, got (%q,%q)", path, format)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if path != c.wantPath || format != c.wantFmt {
				t.Fatalf("got (%q,%q) want (%q,%q)", path, format, c.wantPath, c.wantFmt)
			}
		})
	}
}

func TestDotEscapeAndTrunc(t *testing.T) {
	if got := dotEscape(`a"b\c` + "\n" + "d"); got != `a\"b\\c d` {
		t.Fatalf("escape: %q", got)
	}
	if got := truncRunes("abcdef", 3); got != "abc" {
		t.Fatalf("trunc: %q", got)
	}
	if got := truncRunes("ab", 5); got != "ab" {
		t.Fatalf("no-trunc: %q", got)
	}
}
