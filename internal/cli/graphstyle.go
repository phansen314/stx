package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/BurntSushi/toml"
)

// Graph styling. A base config at $XDG_CONFIG_HOME/stx/graph.toml (fallback ~/.config/stx/graph.toml)
// plus an optional per-invocation overlay (--style) deep-merge over built-in defaults. Every style
// value is an open DOT-attribute map passed through verbatim, so new attributes need no code change.
// With no config and no --cluster, the render is unchanged from the built-in defaults.

// attrs is a bag of Graphviz attributes (key -> value), emitted as key="value".
type attrs map[string]string

// PriorityRule styles a task whose priority is >= Min (the highest matching Min wins).
type PriorityRule struct {
	Min   int   `toml:"min"`
	Style attrs `toml:"style"`
}

// GraphStyle is the whole config surface. Section names match the TOML tables.
type GraphStyle struct {
	Workspace   attrs            `toml:"workspace"` // graph-level attrs (bgcolor, label…)
	Node        attrs            `toml:"node"`      // default node attrs
	Edge        attrs            `toml:"edge"`      // default edge attrs
	Terminal    attrs            `toml:"terminal"`  // fallback for any terminal status
	Blocks      attrs            `toml:"blocks"`    // blocks edge attrs
	Relates     attrs            `toml:"relates"`   // relates edge attrs
	Status      map[string]attrs `toml:"status"`    // by status name (case-insensitive)
	Kind        map[string]attrs `toml:"kind"`      // by kind name
	RelatesKind map[string]attrs `toml:"relates_kind"`
	Track       attrs            `toml:"track"`        // default track-cluster attrs
	TrackName   map[string]attrs `toml:"track_name"`   // per-track override
	Segment     attrs            `toml:"segment"`      // default segment-cluster attrs
	SegmentName map[string]attrs `toml:"segment_name"` // per-segment override
	Priority    []PriorityRule   `toml:"priority"`
}

// defaultGraphStyle reproduces the historical render exactly: rounded boxes, terminal nodes filled
// light green, relates dashed.
func defaultGraphStyle() *GraphStyle {
	return &GraphStyle{
		Node:     attrs{"shape": "box", "style": "rounded"},
		Terminal: attrs{"style": "rounded,filled", "fillcolor": "#cde7cd"},
		Relates:  attrs{"style": "dashed"},
	}
}

// graphConfigPath mirrors tui/config.py: $XDG_CONFIG_HOME/stx/graph.toml, else ~/.config/stx/graph.toml.
func graphConfigPath() string {
	base := os.Getenv("XDG_CONFIG_HOME")
	if base == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return ""
		}
		base = filepath.Join(home, ".config")
	}
	return filepath.Join(base, "stx", "graph.toml")
}

// loadGraphStyle resolves the effective style: built-in defaults, then the base graph.toml (if it
// exists), then the --style overlay (if given). noStyle skips both files. A missing base file is
// fine; a malformed file or a missing/unreadable overlay is a hard error naming the path.
func loadGraphStyle(overlay string, noStyle bool) (*GraphStyle, error) {
	style := defaultGraphStyle()
	if !noStyle {
		if base := graphConfigPath(); base != "" {
			if _, err := os.Stat(base); err == nil {
				if err := decodeStyleInto(base, style); err != nil {
					return nil, err
				}
			}
		}
	}
	if overlay != "" {
		if err := decodeStyleInto(overlay, style); err != nil {
			return nil, err
		}
	}
	return style, nil
}

// decodeStyleInto decodes one TOML file and deep-merges it over dst.
func decodeStyleInto(path string, dst *GraphStyle) error {
	var s GraphStyle
	if _, err := toml.DecodeFile(path, &s); err != nil {
		return fmt.Errorf("graph style %s: %w", path, err)
	}
	mergeStyle(dst, &s)
	return nil
}

// mergeStyle deep-merges src over dst: per-section attr maps merge key-by-key; Priority replaces
// wholesale when the overlay defines any rules (thresholds aren't sensibly merged).
func mergeStyle(dst, src *GraphStyle) {
	mergeAttrs(&dst.Workspace, src.Workspace)
	mergeAttrs(&dst.Node, src.Node)
	mergeAttrs(&dst.Edge, src.Edge)
	mergeAttrs(&dst.Terminal, src.Terminal)
	mergeAttrs(&dst.Blocks, src.Blocks)
	mergeAttrs(&dst.Relates, src.Relates)
	mergeAttrs(&dst.Track, src.Track)
	mergeAttrs(&dst.Segment, src.Segment)
	mergeAttrMap(&dst.Status, src.Status)
	mergeAttrMap(&dst.Kind, src.Kind)
	mergeAttrMap(&dst.RelatesKind, src.RelatesKind)
	mergeAttrMap(&dst.TrackName, src.TrackName)
	mergeAttrMap(&dst.SegmentName, src.SegmentName)
	if len(src.Priority) > 0 {
		dst.Priority = src.Priority
	}
}

func mergeAttrs(dst *attrs, src attrs) {
	if len(src) == 0 {
		return
	}
	if *dst == nil {
		*dst = attrs{}
	}
	for k, v := range src {
		(*dst)[k] = v
	}
}

func mergeAttrMap(dst *map[string]attrs, src map[string]attrs) {
	if len(src) == 0 {
		return
	}
	if *dst == nil {
		*dst = map[string]attrs{}
	}
	for name, a := range src {
		cur := (*dst)[name]
		mergeAttrs(&cur, a)
		(*dst)[name] = cur
	}
}

// ── resolution ────────────────────────────────────────────────────────────────

// resolveNodeAttrs layers styles for one task (later overrides earlier, attrs coexist):
// node → kind → priority → terminal → status.
func (s *GraphStyle) resolveNodeAttrs(status string, terminal bool, kind string, priority int) attrs {
	out := cloneAttrs(s.Node)
	if kind != "" {
		mergeAttrs(&out, lookupCI(s.Kind, kind))
	}
	mergeAttrs(&out, priorityStyle(s.Priority, priority))
	if terminal {
		mergeAttrs(&out, s.Terminal)
	}
	mergeAttrs(&out, lookupCI(s.Status, status))
	return out
}

func (s *GraphStyle) resolveBlockAttrs() attrs {
	out := cloneAttrs(s.Edge)
	mergeAttrs(&out, s.Blocks)
	return out
}

func (s *GraphStyle) resolveRelateAttrs(kind string) attrs {
	out := cloneAttrs(s.Edge)
	mergeAttrs(&out, s.Relates)
	if kind != "" {
		mergeAttrs(&out, lookupCI(s.RelatesKind, kind))
	}
	return out
}

// priorityStyle returns the Style of the rule with the highest Min <= priority, or nil.
func priorityStyle(rules []PriorityRule, priority int) attrs {
	best := -1
	var out attrs
	for _, r := range rules {
		if priority >= r.Min && r.Min > best {
			best = r.Min
			out = r.Style
		}
	}
	return out
}

// lookupCI does a case-insensitive lookup (status/kind names vary in case across installs).
func lookupCI(m map[string]attrs, key string) attrs {
	if a, ok := m[key]; ok {
		return a
	}
	lk := strings.ToLower(key)
	for k, a := range m {
		if strings.ToLower(k) == lk {
			return a
		}
	}
	return nil
}

func cloneAttrs(a attrs) attrs {
	out := attrs{}
	for k, v := range a {
		out[k] = v
	}
	return out
}

// deltaAttrs returns the entries of a whose value differs from base (base being the graph-level
// default emitted separately), so an un-styled element carries no inline attrs.
func deltaAttrs(a, base attrs) attrs {
	out := attrs{}
	for k, v := range a {
		if base[k] != v {
			out[k] = v
		}
	}
	return out
}

// attrOrder is the leading emission order (then remaining keys alphabetically) so output is
// deterministic and reads naturally. "label" is always emitted first by emitAttrs.
var attrOrder = []string{"style", "fillcolor", "color", "penwidth", "fontcolor", "fontname", "shape"}

// emitAttrs renders an attr bag as `key="value" …` in the deterministic order above.
func emitAttrs(a attrs) string {
	if len(a) == 0 {
		return ""
	}
	seen := map[string]bool{}
	var order []string
	if _, ok := a["label"]; ok {
		order, seen["label"] = append(order, "label"), true
	}
	for _, k := range attrOrder {
		if _, ok := a[k]; ok && !seen[k] {
			order, seen[k] = append(order, k), true
		}
	}
	var rest []string
	for k := range a {
		if !seen[k] {
			rest = append(rest, k)
		}
	}
	sort.Strings(rest)
	order = append(order, rest...)
	parts := make([]string, 0, len(order))
	for _, k := range order {
		parts = append(parts, fmt.Sprintf("%s=\"%s\"", k, dotEscape(a[k])))
	}
	return strings.Join(parts, " ")
}
