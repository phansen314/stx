package cli

import "testing"

func TestRenderMeta(t *testing.T) {
	d := map[string]any{
		"s": "hello", "n": float64(42), "flag": true,
		"obj": map[string]any{"x": float64(1)},
	}
	// sorted keys; values rendered as compact JSON (containers stay compact — intentional)
	want := "flag = true\nn = 42\nobj = {\"x\":1}\ns = \"hello\""
	if got := renderMeta(d); got != want {
		t.Fatalf("renderMeta:\n--want--\n%q\n--got--\n%q", want, got)
	}
	if got := renderMeta(map[string]any{}); got != "(no metadata)" {
		t.Fatalf("empty: %q", got)
	}
}

func TestParseMetaValue(t *testing.T) {
	if v := parseMetaValue("42", false); v != float64(42) {
		t.Fatalf("number: %#v", v)
	}
	if v := parseMetaValue("true", false); v != true {
		t.Fatalf("bool: %#v", v)
	}
	if v := parseMetaValue("hello", false); v != "hello" {
		t.Fatalf("bareword→string: %#v", v)
	}
	if v := parseMetaValue(`"q"`, false); v != "q" {
		t.Fatalf("json string: %#v", v)
	}
	if v := parseMetaValue("42", true); v != "42" { // --string forces literal
		t.Fatalf("forceString: %#v", v)
	}
}

func TestMetaLoad(t *testing.T) {
	for _, blob := range []string{"", "{}"} {
		if m, err := metaLoad(blob); err != nil || len(m) != 0 {
			t.Fatalf("empty %q: %v %v", blob, m, err)
		}
	}
	if m, err := metaLoad(`{"a":1}`); err != nil || m["a"] != float64(1) {
		t.Fatalf("object: %v %v", m, err)
	}
	for _, bad := range []string{"[1,2]", "notjson", "5"} {
		if _, err := metaLoad(bad); err == nil {
			t.Fatalf("expected error for %q", bad)
		}
	}
}
