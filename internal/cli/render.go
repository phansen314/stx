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

// renderTree mirrors render.tree: root-segment tasks hang directly under the track (depth 2),
// nested segments recurse. The root segment itself is not printed (pure filing anchor).
func renderTree(ws api.Workspace, blocks []trackBlock, sn map[int64]string) string {
	lines := []string{fmt.Sprintf("%s (#%d)", ws.Name, ws.ID)}

	taskLine := func(t api.Task, depth int) string {
		return fmt.Sprintf("%s- #%d %s [%s] %s",
			strings.Repeat("  ", depth), t.ID, prio(t.Priority), statusName(sn, t.StatusID), t.Title)
	}

	for _, b := range blocks {
		lines = append(lines, fmt.Sprintf("  ▸ %s (#%d)", b.Track.Name, b.Track.ID))
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

		var emitSeg func(seg api.Segment, depth int)
		emitSeg = func(seg api.Segment, depth int) {
			lines = append(lines, fmt.Sprintf("%s▫ %s (#%d)", strings.Repeat("  ", depth), seg.Name, seg.ID))
			for _, child := range byParent[seg.ID] {
				emitSeg(child, depth+1)
			}
			for _, t := range tasksBySeg[seg.ID] {
				lines = append(lines, taskLine(t, depth+1))
			}
		}

		if root != nil {
			for _, t := range tasksBySeg[root.ID] {
				lines = append(lines, taskLine(t, 2))
			}
			for _, child := range byParent[root.ID] {
				emitSeg(child, 2)
			}
		}
	}
	if len(lines) == 1 {
		lines = append(lines, "  (empty)")
	}
	return strings.Join(lines, "\n")
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
