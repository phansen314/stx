package cli

import "testing"

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
	if got := renderGraphDot("ws", nodes, blocks, relates); got != want {
		t.Fatalf("dot mismatch:\n--want--\n%s\n--got--\n%s", want, got)
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
