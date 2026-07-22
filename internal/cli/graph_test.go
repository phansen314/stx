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

func TestRenderFormat(t *testing.T) {
	cases := []struct {
		explicit, out, want string
		wantErr             bool
	}{
		{explicit: "svg", out: "g.svg", want: "svg"}, // agree
		{out: "g.svg", want: "svg"},
		{out: "g.PNG", want: "png"},                    // extension lower-cased
		{out: "noext", want: "svg"},                    // no extension → default
		{explicit: "png", out: "g", want: "png"},       // no extension → --format used
		{explicit: "svg", out: "g.png", wantErr: true}, // conflict
	}
	for _, c := range cases {
		got, err := renderFormat(c.explicit, c.out)
		if c.wantErr {
			if err == nil {
				t.Errorf("renderFormat(%q,%q) expected conflict error, got %q", c.explicit, c.out, got)
			}
			continue
		}
		if err != nil || got != c.want {
			t.Errorf("renderFormat(%q,%q)=(%q,%v) want %q", c.explicit, c.out, got, err, c.want)
		}
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
