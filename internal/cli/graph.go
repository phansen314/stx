package cli

import (
	"bytes"
	"errors"
	"fmt"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"github.com/phansen314/stx/internal/api"
	"github.com/spf13/cobra"
)

type graphNode struct {
	ID       int64  `json:"id"`
	Title    string `json:"title"`
	Status   string `json:"status"`
	Terminal bool   `json:"terminal"`
	// styling/clustering inputs — excluded from --json so the wire payload is unchanged.
	Kind      string `json:"-"`
	Priority  int    `json:"-"`
	SegmentID int64  `json:"-"`
	TrackID   int64  `json:"-"`
	TrackName string `json:"-"`
}

type graphPayload struct {
	Workspace string      `json:"workspace"`
	Nodes     []graphNode `json:"nodes"`
	Blocks    [][]int64   `json:"blocks"`
	Relates   [][]any     `json:"relates"`
}

func newGraphCmd() *cobra.Command {
	var wsFlag, trackFlag, outFlag, styleFlag, clusterFlag string
	var blocksOnly, vertical, svg, png, pdf, noStyle bool
	cmd := &cobra.Command{
		Use:   "graph",
		Short: "emit the task graph as Graphviz DOT (pipe to `dot`, or render with -o)",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			cluster := strings.ToLower(clusterFlag)
			switch cluster {
			case "", "none", "track", "segment":
			default:
				return fmt.Errorf("--cluster must be none|track|segment, got %q", clusterFlag)
			}
			style, err := loadGraphStyle(styleFlag, noStyle)
			if err != nil {
				return err
			}
			c, err := dial()
			if err != nil {
				return err
			}
			ws, err := resolveWorkspace(c, wsFlag)
			if err != nil {
				return err
			}
			statuses, err := c.Statuses(ws.ID)
			if err != nil {
				return err
			}
			stByID := map[int64]int{} // id → index into statuses
			for i, s := range statuses {
				stByID[s.ID] = i
			}
			knByID, err := kindNames(c, ws.ID) // kind id → name for styling
			if err != nil {
				return err
			}
			tracks, err := c.Tracks(ws.ID)
			if err != nil {
				return err
			}
			if trackFlag != "" {
				tr, err := resolveTrack(c, ws.ID, trackFlag)
				if err != nil {
					return err
				}
				var filtered []api.Track
				for _, t := range tracks {
					if t.ID == tr.ID {
						filtered = append(filtered, t)
					}
				}
				tracks = filtered
			}
			nodes := map[int64]graphNode{}
			var segments []api.Segment // populated only when clustering by segment
			for _, t := range tracks {
				if cluster == "segment" {
					segs, err := c.Segments(t.ID)
					if err != nil {
						return err
					}
					segments = append(segments, segs...)
				}
				tasks, err := c.TrackTasks(t.ID)
				if err != nil {
					return err
				}
				for _, task := range tasks {
					name := strconv.FormatInt(task.StatusID, 10)
					term := false
					if idx, ok := stByID[task.StatusID]; ok {
						name = statuses[idx].Name
						term = statuses[idx].Terminal
					}
					kindName := ""
					if task.KindID != nil {
						kindName = knByID[*task.KindID]
					}
					nodes[task.ID] = graphNode{
						ID: task.ID, Title: task.Title, Status: name, Terminal: term,
						Kind: kindName, Priority: task.Priority, SegmentID: task.SegmentID,
						TrackID: t.ID, TrackName: t.Name,
					}
				}
			}
			edges, err := c.Edges(ws.ID)
			if err != nil {
				return err
			}
			blocks := [][]int64{}
			for _, e := range edges.Blocks {
				if _, ok := nodes[e.SourceTaskID]; !ok {
					continue
				}
				if _, ok := nodes[e.TargetTaskID]; !ok {
					continue
				}
				blocks = append(blocks, []int64{e.SourceTaskID, e.TargetTaskID})
			}
			relates := [][]any{}
			if !blocksOnly {
				for _, e := range edges.Relates {
					if _, ok := nodes[e.SourceTaskID]; !ok {
						continue
					}
					if _, ok := nodes[e.TargetTaskID]; !ok {
						continue
					}
					relates = append(relates, []any{e.SourceTaskID, e.TargetTaskID, e.Kind})
				}
			}
			ids := make([]int64, 0, len(nodes))
			for id := range nodes {
				ids = append(ids, id)
			}
			sort.Slice(ids, func(i, j int) bool { return ids[i] < ids[j] })
			ordered := make([]graphNode, 0, len(ids))
			for _, id := range ids {
				ordered = append(ordered, nodes[id])
			}
			if len(ordered) == 0 {
				markEmpty() // a graph with no nodes is an empty result (exit 1); the DOT still prints
			}
			dotSrc := renderGraphDot(ws.Name, vertical, cluster, ordered, blocks, relates, style, segments)

			// -o renders the DOT to an image file via Graphviz; otherwise emit DOT / JSON.
			if outFlag != "" {
				if flagJSON {
					return errors.New("-o/--out and --json are mutually exclusive")
				}
				outPath, format, err := resolveGraphOutput(outFlag, svg, png, pdf)
				if err != nil {
					return err
				}
				if err := renderWithDot(dotSrc, format, outPath); err != nil {
					return err
				}
				fmt.Fprintf(cmd.OutOrStdout(), "rendered %s (%s)\n", outPath, format)
				return nil
			}
			if svg || png || pdf {
				return errors.New("--svg/--png/--pdf apply only with -o/--out")
			}
			if flagJSON {
				return printJSON(cmd, graphPayload{Workspace: ws.Name, Nodes: ordered, Blocks: blocks, Relates: relates})
			}
			fmt.Fprintln(cmd.OutOrStdout(), dotSrc)
			return nil
		},
	}
	cmd.Flags().StringVarP(&wsFlag, "workspace", "w", "", "workspace name or id (required)")
	cmd.Flags().StringVarP(&trackFlag, "track", "t", "", "scope to a track (name or id)")
	cmd.Flags().BoolVar(&blocksOnly, "blocks-only", false, "omit relates_to edges")
	cmd.Flags().BoolVar(&vertical, "vertical", false, "top-to-bottom layout (default is left-to-right)")
	cmd.Flags().StringVarP(&outFlag, "out", "o", "", "render to this file via `dot`; give a bare name (e.g. graph) and pick a format flag")
	cmd.Flags().BoolVar(&svg, "svg", false, "render -o as SVG (default)")
	cmd.Flags().BoolVar(&png, "png", false, "render -o as PNG")
	cmd.Flags().BoolVar(&pdf, "pdf", false, "render -o as PDF")
	cmd.MarkFlagsMutuallyExclusive("svg", "png", "pdf")
	cmd.Flags().StringVar(&clusterFlag, "cluster", "none", "group nodes into clusters: none|track|segment")
	cmd.Flags().StringVar(&styleFlag, "style", "", "overlay style file (TOML) merged over ~/.config/stx/graph.toml")
	cmd.Flags().BoolVar(&noStyle, "no-style", false, "ignore config files; use built-in default styling")
	return cmd
}

// graphFormats are the formats the --svg/--png/--pdf flags cover — and the only extensions
// accepted on a bare `-o` path (dot supports more, but keeping the set tight avoids surprises).
var graphFormats = map[string]bool{"svg": true, "png": true, "pdf": true}

// resolveGraphOutput decides the dot -T format and the final output path. A format flag always
// wins: it sets the format and its extension replaces whatever the user typed on -o (so the file
// is never mislabeled and nobody has to remember extensions). With no flag, a typed extension is
// used but must be one we support; an unsupported extension is a clean error, and no extension
// defaults to svg. The flags are mutually exclusive (enforced by cobra), so at most one is set.
func resolveGraphOutput(out string, svg, png, pdf bool) (outPath, format string, err error) {
	flag := ""
	switch {
	case svg:
		flag = "svg"
	case png:
		flag = "png"
	case pdf:
		flag = "pdf"
	}
	ext := strings.ToLower(strings.TrimPrefix(filepath.Ext(out), "."))
	if flag != "" {
		base := strings.TrimSuffix(out, filepath.Ext(out)) // drop whatever extension was typed
		return base + "." + flag, flag, nil
	}
	switch {
	case ext == "":
		return out + ".svg", "svg", nil
	case graphFormats[ext]:
		return out, ext, nil
	default:
		return "", "", fmt.Errorf("unsupported output extension %q — use .svg/.png/.pdf, or pass --svg/--png/--pdf", "."+ext)
	}
}

// renderWithDot pipes DOT source through Graphviz `dot -T<format> -o <outPath>`.
func renderWithDot(dotSrc, format, outPath string) error {
	if _, err := exec.LookPath("dot"); err != nil {
		return errors.New("rendering needs Graphviz `dot` on PATH — install graphviz (e.g. apt install graphviz)")
	}
	c := exec.Command("dot", "-T"+format, "-o", outPath)
	c.Stdin = strings.NewReader(dotSrc)
	var stderr bytes.Buffer
	c.Stderr = &stderr
	if err := c.Run(); err != nil {
		msg := strings.TrimSpace(stderr.String())
		if msg == "" {
			msg = err.Error()
		}
		return fmt.Errorf("dot failed: %s", msg)
	}
	return nil
}

func dotEscape(s string) string {
	s = strings.ReplaceAll(s, "\\", "\\\\")
	s = strings.ReplaceAll(s, "\"", "\\\"")
	s = strings.ReplaceAll(s, "\n", " ")
	return s
}

func truncRunes(s string, n int) string {
	r := []rune(s)
	if len(r) > n {
		return string(r[:n])
	}
	return s
}

// renderGraphDot emits the task graph as DOT, applying the resolved style and optional clustering.
// Layout is left-to-right unless vertical (top-to-bottom). Nodes must already be sorted by id. When
// cluster is "segment", segments carries the segment rows for the included tracks (for names/tree).
func renderGraphDot(wsName string, vertical bool, cluster string, nodes []graphNode, blocks [][]int64, relates [][]any, style *GraphStyle, segments []api.Segment) string {
	rankdir := "LR"
	if vertical {
		rankdir = "TB"
	}
	var b strings.Builder
	fmt.Fprintf(&b, "digraph \"%s\" {\n", dotEscape(wsName))
	fmt.Fprintf(&b, "  rankdir=%s;\n", rankdir)
	if a := emitAttrs(style.Workspace); a != "" {
		fmt.Fprintf(&b, "  graph [%s];\n", a)
	}
	if a := emitAttrs(style.Node); a != "" {
		fmt.Fprintf(&b, "  node [%s];\n", a)
	}
	if a := emitAttrs(style.Edge); a != "" {
		fmt.Fprintf(&b, "  edge [%s];\n", a)
	}

	switch cluster {
	case "track":
		emitTrackClusters(&b, nodes, style)
	case "segment":
		emitSegmentClusters(&b, nodes, style, segments)
	default:
		for _, n := range nodes {
			emitNode(&b, "  ", n, style)
		}
	}

	for _, e := range blocks {
		emitEdge(&b, e[0], e[1], style.resolveBlockAttrs())
	}
	for _, r := range relates {
		a := style.resolveRelateAttrs(r[2].(string))
		a = cloneAttrs(a)
		a["label"] = r[2].(string)
		emitEdge(&b, r[0].(int64), r[1].(int64), a)
	}
	b.WriteString("}")
	return b.String()
}

// emitNode writes one task node line with its label plus the delta of its resolved style over the
// graph-level node default (so an un-styled node carries only its label).
func emitNode(b *strings.Builder, indent string, n graphNode, style *GraphStyle) {
	label := dotEscape(truncRunes(fmt.Sprintf("#%d %s", n.ID, n.Title), 40))
	a := deltaAttrs(style.resolveNodeAttrs(n.Status, n.Terminal, n.Kind, n.Priority), style.Node)
	a["label"] = label
	fmt.Fprintf(b, "%s\"%d\" [%s];\n", indent, n.ID, emitAttrs(a))
}

// emitEdge writes one edge; the delta over the graph-level edge default keeps un-styled edges bare.
func emitEdge(b *strings.Builder, src, tgt int64, a attrs) {
	if s := emitAttrs(a); s != "" {
		fmt.Fprintf(b, "  \"%d\" -> \"%d\" [%s];\n", src, tgt, s)
	} else {
		fmt.Fprintf(b, "  \"%d\" -> \"%d\";\n", src, tgt)
	}
}

// emitTrackClusters wraps each track's nodes in a labelled subgraph cluster (nodes keep source order).
func emitTrackClusters(b *strings.Builder, nodes []graphNode, style *GraphStyle) {
	var order []int64
	byTrack := map[int64][]graphNode{}
	name := map[int64]string{}
	for _, n := range nodes {
		if _, seen := byTrack[n.TrackID]; !seen {
			order = append(order, n.TrackID)
		}
		byTrack[n.TrackID] = append(byTrack[n.TrackID], n)
		name[n.TrackID] = n.TrackName
	}
	for _, tid := range order {
		a := cloneAttrs(style.Track)
		mergeAttrs(&a, lookupCI(style.TrackName, name[tid]))
		fmt.Fprintf(b, "  subgraph cluster_track_%d {\n", tid)
		fmt.Fprintf(b, "    label=\"%s\";\n", dotEscape(name[tid]))
		emitClusterAttrs(b, "    ", a)
		for _, n := range byTrack[tid] {
			emitNode(b, "    ", n, style)
		}
		b.WriteString("  }\n")
	}
}

// emitSegmentClusters nests segment subclusters within each track cluster, following the segment
// tree. Tasks in a track's root segment sit directly in the track cluster; deeper segments nest.
func emitSegmentClusters(b *strings.Builder, nodes []graphNode, style *GraphStyle, segments []api.Segment) {
	segByID := map[int64]api.Segment{}
	children := map[int64][]int64{} // parent segment id → child segment ids (0 = track root level)
	var roots []api.Segment
	for _, s := range segments {
		segByID[s.ID] = s
		if s.IsRoot {
			roots = append(roots, s)
		} else if s.ParentSegmentID != nil {
			children[*s.ParentSegmentID] = append(children[*s.ParentSegmentID], s.ID)
		}
	}
	nodesBySeg := map[int64][]graphNode{}
	var trackOrder []int64
	rootBySeenTrack := map[int64]bool{}
	trackName := map[int64]string{}
	for _, n := range nodes {
		nodesBySeg[n.SegmentID] = append(nodesBySeg[n.SegmentID], n)
		if !rootBySeenTrack[n.TrackID] {
			rootBySeenTrack[n.TrackID] = true
			trackOrder = append(trackOrder, n.TrackID)
		}
		trackName[n.TrackID] = n.TrackName
	}
	rootByTrack := map[int64]api.Segment{}
	for _, r := range roots {
		rootByTrack[r.TrackID] = r
	}

	var emitSeg func(segID int64)
	emitSeg = func(segID int64) {
		seg := segByID[segID]
		a := cloneAttrs(style.Segment)
		mergeAttrs(&a, lookupCI(style.SegmentName, seg.Name))
		fmt.Fprintf(b, "    subgraph cluster_seg_%d {\n", segID)
		fmt.Fprintf(b, "      label=\"%s\";\n", dotEscape(seg.Name))
		emitClusterAttrs(b, "      ", a)
		for _, n := range nodesBySeg[segID] {
			emitNode(b, "      ", n, style)
		}
		for _, child := range children[segID] {
			emitSeg(child)
		}
		b.WriteString("    }\n")
	}

	for _, tid := range trackOrder {
		a := cloneAttrs(style.Track)
		mergeAttrs(&a, lookupCI(style.TrackName, trackName[tid]))
		fmt.Fprintf(b, "  subgraph cluster_track_%d {\n", tid)
		fmt.Fprintf(b, "    label=\"%s\";\n", dotEscape(trackName[tid]))
		emitClusterAttrs(b, "    ", a)
		root, ok := rootByTrack[tid]
		if ok {
			for _, n := range nodesBySeg[root.ID] { // root-segment tasks sit at track level
				emitNode(b, "    ", n, style)
			}
			for _, child := range children[root.ID] {
				emitSeg(child)
			}
		}
		b.WriteString("  }\n")
	}
}

// emitClusterAttrs writes each cluster attribute as its own `key="value";` statement.
func emitClusterAttrs(b *strings.Builder, indent string, a attrs) {
	keys := make([]string, 0, len(a))
	for k := range a {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		fmt.Fprintf(b, "%s%s=\"%s\";\n", indent, k, dotEscape(a[k]))
	}
}
