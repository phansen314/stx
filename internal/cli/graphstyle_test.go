package cli

import (
	"os"
	"path/filepath"
	"testing"
)

func TestResolveNodeAttrs_Layering(t *testing.T) {
	s := defaultGraphStyle()
	s.Status = map[string]attrs{"Done": {"fillcolor": "#00ff00"}}
	s.Kind = map[string]attrs{"bug": {"color": "red"}}
	s.Priority = []PriorityRule{
		{Min: 3, Style: attrs{"penwidth": "2"}},
		{Min: 7, Style: attrs{"penwidth": "4"}},
	}

	// Done (terminal) + bug + priority 8: status fill overrides terminal fill; kind border and the
	// highest matching priority rule coexist.
	a := s.resolveNodeAttrs("Done", true, "bug", 8)
	if a["fillcolor"] != "#00ff00" {
		t.Errorf("status should override terminal fill, got %q", a["fillcolor"])
	}
	if a["color"] != "red" {
		t.Errorf("kind border missing, got %q", a["color"])
	}
	if a["penwidth"] != "4" {
		t.Errorf("highest priority rule (min 7) should win, got %q", a["penwidth"])
	}

	// Terminal with no status rule → falls back to the green terminal default.
	if a := s.resolveNodeAttrs("Archived", true, "", 0); a["fillcolor"] != "#cde7cd" {
		t.Errorf("terminal fallback missing, got %q", a["fillcolor"])
	}
	// Non-terminal, no rules → just the node defaults.
	if a := s.resolveNodeAttrs("Backlog", false, "", 0); a["fillcolor"] != "" {
		t.Errorf("plain node should have no fill, got %q", a["fillcolor"])
	}
}

func TestLookupCI(t *testing.T) {
	m := map[string]attrs{"In Review": {"x": "1"}}
	if lookupCI(m, "in review")["x"] != "1" {
		t.Fatal("case-insensitive lookup failed")
	}
	if lookupCI(m, "nope") != nil {
		t.Fatal("missing key should be nil")
	}
}

func TestLoadGraphStyle_BaseOverlayPrecedence(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", dir)
	if err := os.MkdirAll(filepath.Join(dir, "stx"), 0o755); err != nil {
		t.Fatal(err)
	}
	base := filepath.Join(dir, "stx", "graph.toml")
	writeFile(t, base, `
[status.Done]
fillcolor = "#aaaaaa"
color = "black"
`)
	overlay := filepath.Join(dir, "overlay.toml")
	writeFile(t, overlay, `
[status.Done]
fillcolor = "#00ff00"
`)

	// base only
	s, err := loadGraphStyle("", false)
	if err != nil {
		t.Fatal(err)
	}
	if s.Status["Done"]["fillcolor"] != "#aaaaaa" || s.Status["Done"]["color"] != "black" {
		t.Fatalf("base not applied: %+v", s.Status["Done"])
	}
	// overlay merges over base: fillcolor overridden, color retained
	s, err = loadGraphStyle(overlay, false)
	if err != nil {
		t.Fatal(err)
	}
	if s.Status["Done"]["fillcolor"] != "#00ff00" {
		t.Errorf("overlay should override fillcolor, got %q", s.Status["Done"]["fillcolor"])
	}
	if s.Status["Done"]["color"] != "black" {
		t.Errorf("overlay should keep base color, got %q", s.Status["Done"]["color"])
	}
	// --no-style ignores the base file → built-in defaults only
	s, err = loadGraphStyle("", true)
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := s.Status["Done"]; ok {
		t.Error("no-style should ignore the base config")
	}
	if s.Terminal["fillcolor"] != "#cde7cd" {
		t.Error("no-style should keep built-in defaults")
	}
}

func TestLoadGraphStyle_MissingBaseOK_MalformedErrors(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", dir) // no stx/graph.toml here
	if _, err := loadGraphStyle("", false); err != nil {
		t.Fatalf("missing base should be fine, got %v", err)
	}
	bad := filepath.Join(dir, "bad.toml")
	writeFile(t, bad, "this is = not = valid toml")
	if _, err := loadGraphStyle(bad, false); err == nil {
		t.Fatal("malformed overlay should error")
	}
}

func writeFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}
