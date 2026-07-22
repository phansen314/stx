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
	want := `digraph "ws" {
  rankdir=LR;
  node [shape=box, style=rounded];
  "16" [label="#16 schema"];
  "17" [label="#17 done thing" style="rounded,filled" fillcolor="#cde7cd"];
  "16" -> "17";
  "17" -> "16" [style=dashed, label="relates_to"];
}`
	if got := renderGraphDot("ws", false, nodes, blocks, relates); got != want {
		t.Fatalf("dot mismatch:\n--want--\n%s\n--got--\n%s", want, got)
	}
}

func TestRenderGraphDotVertical(t *testing.T) {
	nodes := []graphNode{{ID: 1, Title: "a", Status: "Backlog"}}
	if got := renderGraphDot("ws", false, nodes, nil, nil); !strings.Contains(got, "rankdir=LR;") {
		t.Fatalf("default should be LR:\n%s", got)
	}
	if got := renderGraphDot("ws", true, nodes, nil, nil); !strings.Contains(got, "rankdir=TB;") {
		t.Fatalf("--vertical should be TB:\n%s", got)
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
