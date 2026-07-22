package cli

import (
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"strings"

	"github.com/phansen314/stx/internal/api"
	"github.com/phansen314/stx/internal/client"
	"github.com/spf13/cobra"
)

// prio mirrors render._prio: "P<n>" for a set priority, two spaces for zero.
func prio(p int) string {
	if p != 0 {
		return "P" + strconv.Itoa(p)
	}
	return "  "
}

func joinLines(xs []string) string { return strings.Join(xs, "\n") }

func statusName(m map[int64]string, id int64) string {
	if n, ok := m[id]; ok {
		return n
	}
	return strconv.FormatInt(id, 10)
}

// renderFrontier mirrors render.frontier.
func renderFrontier(items []api.FrontierItem, sn map[int64]string) string {
	if len(items) == 0 {
		return "(nothing ready)"
	}
	lines := make([]string, 0, len(items))
	for _, i := range items {
		lines = append(lines, fmt.Sprintf("%4d  %s  [%s]  %s",
			i.ID, prio(i.Priority), statusName(sn, i.StatusID), i.Title))
	}
	return strings.Join(lines, "\n")
}

// renderTaskDetail mirrors render.task_detail.
func renderTaskDetail(d api.TaskDetail, sn, kn map[int64]string) string {
	t := d.Task
	kindStr := "-"
	if t.KindID != nil && *t.KindID != 0 {
		if n, ok := kn[*t.KindID]; ok {
			kindStr = n
		}
	}
	out := []string{
		fmt.Sprintf("#%d  %s", t.ID, t.Title),
		fmt.Sprintf("  status: %s    kind: %s    priority: P%d", statusName(sn, t.StatusID), kindStr, t.Priority) +
			archivedSuffix(t.Archived),
	}
	if t.Description != "" {
		out = append(out, "  description: "+t.Description)
	}
	if len(d.BlocksIn) > 0 {
		out = append(out, "  blocked-by: "+joinIDs(d.BlocksIn))
	}
	if len(d.BlocksOut) > 0 {
		out = append(out, "  blocks: "+joinIDs(d.BlocksOut))
	}
	if len(d.Relates) > 0 {
		parts := make([]string, 0, len(d.Relates))
		for _, e := range d.Relates {
			arrow := "←" // ←  incoming
			if e.Outgoing {
				arrow = "→" // →  outgoing
			}
			parts = append(parts, fmt.Sprintf("%s%s#%d", e.Kind, arrow, e.OtherTaskID))
		}
		out = append(out, "  relates: "+strings.Join(parts, ", "))
	}
	return strings.Join(out, "\n")
}

func archivedSuffix(archived bool) string {
	if archived {
		return "    ARCHIVED"
	}
	return ""
}

func joinIDs(ids []int64) string {
	parts := make([]string, len(ids))
	for i, id := range ids {
		parts[i] = "#" + strconv.FormatInt(id, 10)
	}
	return strings.Join(parts, ", ")
}

// trackBlock groups a track with its segments + tasks for the tree render.
type trackBlock struct {
	Track    api.Track
	Segments []api.Segment
	Tasks    []api.Task
}

// tree-drawing glyphs (linux `tree` style): branch connectors and continuation prefixes.
const (
	treeTee  = "├── " // a non-last child
	treeEll  = "└── " // the last child
	treePipe = "│   " // ancestor that has more siblings below
	treeGap  = "    " // ancestor that was the last child
)

// renderTree draws a workspace as a linux-`tree`-style hierarchy with ├── └── │ connectors.
// Each node's children are its tasks first, then its child segments, so the last of those gets
// └──. The root segment itself is not printed (pure filing anchor): its tasks + child segments
// hang directly under the track. Track/segment labels keep a small ▸/▫ type glyph.
func renderTree(ws api.Workspace, blocks []trackBlock, sn map[int64]string) string {
	lines := []string{fmt.Sprintf("%s (#%d)", ws.Name, ws.ID)}

	taskLabel := func(t api.Task) string {
		return fmt.Sprintf("#%d %s [%s] %s", t.ID, prio(t.Priority), statusName(sn, t.StatusID), t.Title)
	}
	conn := func(last bool) string {
		if last {
			return treeEll
		}
		return treeTee
	}
	cont := func(prefix string, last bool) string {
		if last {
			return prefix + treeGap
		}
		return prefix + treePipe
	}

	for ti, b := range blocks {
		byParent := map[int64][]api.Segment{}
		var root *api.Segment
		for i := range b.Segments {
			s := b.Segments[i]
			if s.ParentSegmentID != nil {
				byParent[*s.ParentSegmentID] = append(byParent[*s.ParentSegmentID], s)
			}
			if s.IsRoot {
				root = &b.Segments[i]
			}
		}
		tasksBySeg := map[int64][]api.Task{}
		for _, t := range b.Tasks {
			tasksBySeg[t.SegmentID] = append(tasksBySeg[t.SegmentID], t)
		}

		// emitChildren draws a node's tasks (first) then child segments (last), under prefix.
		var emitChildren func(segID int64, prefix string)
		emitChildren = func(segID int64, prefix string) {
			tasks := tasksBySeg[segID]
			segs := byParent[segID]
			n := len(tasks) + len(segs)
			for i, t := range tasks {
				lines = append(lines, prefix+conn(i == n-1)+taskLabel(t))
			}
			for j := range segs {
				s := segs[j]
				last := len(tasks)+j == n-1
				lines = append(lines, fmt.Sprintf("%s%s▫ %s (#%d)", prefix, conn(last), s.Name, s.ID))
				emitChildren(s.ID, cont(prefix, last))
			}
		}

		trackLast := ti == len(blocks)-1
		lines = append(lines, fmt.Sprintf("%s▸ %s (#%d)", conn(trackLast), b.Track.Name, b.Track.ID))
		if root != nil {
			emitChildren(root.ID, cont("", trackLast))
		}
	}
	if len(lines) == 1 {
		lines = append(lines, "(empty)")
	}
	return strings.Join(lines, "\n")
}

// treeTaskIDs lists a workspace's task ids in the same order renderTree prints them (per track,
// a segment's own tasks before its child segments, depth-first) — the `-q` view of `tree`.
func treeTaskIDs(blocks []trackBlock) []int64 {
	var ids []int64
	for _, b := range blocks {
		byParent := map[int64][]api.Segment{}
		var rootID int64
		for i := range b.Segments {
			s := b.Segments[i]
			if s.ParentSegmentID != nil {
				byParent[*s.ParentSegmentID] = append(byParent[*s.ParentSegmentID], s)
			}
			if s.IsRoot {
				rootID = s.ID
			}
		}
		tasksBySeg := map[int64][]api.Task{}
		for _, t := range b.Tasks {
			tasksBySeg[t.SegmentID] = append(tasksBySeg[t.SegmentID], t)
		}
		var walk func(segID int64)
		walk = func(segID int64) {
			for _, t := range tasksBySeg[segID] {
				ids = append(ids, t.ID)
			}
			for _, s := range byParent[segID] {
				walk(s.ID)
			}
		}
		walk(rootID)
	}
	return ids
}

// printJSON writes v as indented JSON (the --json escape hatch), matching Python's
// json.dumps(..., indent=2).
func printJSON(cmd *cobra.Command, v any) error {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return err
	}
	_, err = fmt.Fprintln(cmd.OutOrStdout(), string(b))
	return err
}

// emitLines is the single output funnel: -q prints the quiet lines (ids, keys, a bare value),
// --json the raw entity, otherwise the human text. A command with nothing to say quietly passes
// nil and prints nothing under -q (rule of silence).
func emitLines(cmd *cobra.Command, quiet []string, entity any, text string) error {
	out := cmd.OutOrStdout()
	if flagQuiet {
		for _, l := range quiet {
			if _, err := fmt.Fprintln(out, l); err != nil {
				return err
			}
		}
		return nil
	}
	if flagJSON {
		return printJSON(cmd, entity)
	}
	_, err := fmt.Fprintln(out, text)
	return err
}

// unwrapOne keeps single-target --json output identical to before batching existed: one id emits
// the bare entity, a batch emits the array.
func unwrapOne(xs []any) any {
	if len(xs) == 1 {
		return xs[0]
	}
	return xs
}

// emit is emitLines for the common case: the ids this command produced or acted on.
func emit(cmd *cobra.Command, ids []int64, entity any, text string) error {
	return emitLines(cmd, idLines(ids), entity, text)
}

func idLines(ids []int64) []string {
	lines := make([]string, len(ids))
	for i, id := range ids {
		lines[i] = strconv.FormatInt(id, 10)
	}
	return lines
}

// emitBatch closes out a command that ran over ids from `-`: print whatever succeeded (nothing at
// all if every id failed), then surface the batch failure.
func emitBatch(cmd *cobra.Command, ids []int64, res []any, lines []string, runErr error) error {
	if len(ids) > 0 {
		if err := emit(cmd, ids, unwrapOne(res), joinLines(lines)); err != nil {
			return err
		}
	}
	return runErr
}

// parseID turns a positional id argument into an int64 (argparse type=int equivalent).
func parseID(s string) (int64, error) {
	id, err := strconv.ParseInt(s, 10, 64)
	if err != nil {
		return 0, fmt.Errorf("invalid id %q", s)
	}
	return id, nil
}

// FormatError maps a command error to the CLI's stderr line, mirroring Python's main():
// APIError → "error: <Variant>: <msg>", ConnError → "error: daemon request failed: …",
// everything else → "error: <msg>".
func FormatError(err error) string {
	var ae *client.APIError
	var ce *client.ConnError
	switch {
	case errors.As(err, &ae):
		return "error: " + ae.Error()
	case errors.As(err, &ce):
		return "error: " + ce.Error()
	default:
		return fmt.Sprintf("error: %v", err)
	}
}
