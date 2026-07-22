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
}

type graphPayload struct {
	Workspace string      `json:"workspace"`
	Nodes     []graphNode `json:"nodes"`
	Blocks    [][]int64   `json:"blocks"`
	Relates   [][]any     `json:"relates"`
}

func newGraphCmd() *cobra.Command {
	var wsFlag, trackFlag, outFlag, formatFlag string
	var blocksOnly, vertical bool
	cmd := &cobra.Command{
		Use:   "graph",
		Short: "emit the task graph as Graphviz DOT (pipe to `dot`, or render with -o)",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
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
			for _, t := range tracks {
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
					nodes[task.ID] = graphNode{ID: task.ID, Title: task.Title, Status: name, Terminal: term}
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
			dotSrc := renderGraphDot(ws.Name, vertical, ordered, blocks, relates)

			// -o renders the DOT to an image file via Graphviz; otherwise emit DOT / JSON.
			if outFlag != "" {
				if flagJSON {
					return errors.New("-o/--out and --json are mutually exclusive")
				}
				format := renderFormat(formatFlag, outFlag)
				if err := renderWithDot(dotSrc, format, outFlag); err != nil {
					return err
				}
				fmt.Fprintf(cmd.OutOrStdout(), "rendered %s (%s)\n", outFlag, format)
				return nil
			}
			if formatFlag != "" {
				return errors.New("--format only applies with -o/--out")
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
	cmd.Flags().StringVarP(&outFlag, "out", "o", "", "render to this file via `dot` (e.g. graph.svg); format inferred from the extension")
	cmd.Flags().StringVar(&formatFlag, "format", "", "output format for -o (svg|png|pdf|…); overrides the file extension")
	return cmd
}

// renderFormat picks the dot -T format: the explicit --format wins, else the file extension,
// else svg.
func renderFormat(explicit, outPath string) string {
	if explicit != "" {
		return strings.ToLower(explicit)
	}
	if ext := strings.TrimPrefix(filepath.Ext(outPath), "."); ext != "" {
		return strings.ToLower(ext)
	}
	return "svg"
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

// renderGraphDot mirrors render.graph_dot: rounded boxes, terminal nodes filled, blocks solid,
// relates dashed+labelled. Layout is left-to-right unless vertical (top-to-bottom). Nodes must
// already be sorted by id.
func renderGraphDot(wsName string, vertical bool, nodes []graphNode, blocks [][]int64, relates [][]any) string {
	rankdir := "LR"
	if vertical {
		rankdir = "TB"
	}
	var b strings.Builder
	fmt.Fprintf(&b, "digraph \"%s\" {\n", dotEscape(wsName))
	fmt.Fprintf(&b, "  rankdir=%s;\n", rankdir)
	b.WriteString("  node [shape=box, style=rounded];\n")
	for _, n := range nodes {
		label := dotEscape(truncRunes(fmt.Sprintf("#%d %s", n.ID, n.Title), 40))
		style := ""
		if n.Terminal {
			style = ` style="rounded,filled" fillcolor="#cde7cd"`
		}
		fmt.Fprintf(&b, "  \"%d\" [label=\"%s\"%s];\n", n.ID, label, style)
	}
	for _, e := range blocks {
		fmt.Fprintf(&b, "  \"%d\" -> \"%d\";\n", e[0], e[1])
	}
	for _, r := range relates {
		fmt.Fprintf(&b, "  \"%d\" -> \"%d\" [style=dashed, label=\"%s\"];\n", r[0], r[1], dotEscape(r[2].(string)))
	}
	b.WriteString("}")
	return b.String()
}
