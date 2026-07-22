package cli

import (
	"encoding/json"
	"fmt"
	"strconv"

	"github.com/phansen314/stx/internal/client"
	"github.com/spf13/cobra"
)

// Dynamic shell completion. Cobra's stock `completion bash|zsh|fish` handles the mechanics; these
// hooks feed it *live* daemon data so `stx show <TAB>` offers real task ids, `stx add -w <TAB>`
// offers workspaces, `stx mv <id> <TAB>` offers the legal next statuses, etc. Every hook dials
// fresh and, on any failure (daemon down included), returns no candidates — completion must never
// block or error. Wired onto commands in registerCompletions, called from NewRootCmd.

const noComp = cobra.ShellCompDirectiveNoFileComp

// completeClient dials without the reachability error dial() raises; nil means "offer nothing".
func completeClient() *client.Client {
	c := client.New(flagBaseURL)
	if !c.Ping() {
		return nil
	}
	return c
}

func registerCompletions(root *cobra.Command) {
	// cmdAt resolves a (possibly nested) command by path, e.g. cmdAt(root,"status","default").
	cmdAt := func(path ...string) *cobra.Command {
		c, _, err := root.Find(path)
		if err != nil || c == nil || c.Name() != path[len(path)-1] {
			return nil
		}
		return c
	}
	posArg := func(fn func(*cobra.Command, []string, string) ([]string, cobra.ShellCompDirective), paths ...[]string) {
		for _, p := range paths {
			if c := cmdAt(p...); c != nil {
				c.ValidArgsFunction = fn
			}
		}
	}
	flagComp := func(flag string, fn func(*cobra.Command, []string, string) ([]string, cobra.ShellCompDirective), paths ...[]string) {
		for _, p := range paths {
			if c := cmdAt(p...); c != nil {
				_ = c.RegisterFlagCompletionFunc(flag, fn)
			}
		}
	}

	// ── first positional = a task id ──
	posArg(completeTaskArg,
		[]string{"show"}, []string{"edit"}, []string{"done"},
		[]string{"block"}, []string{"unblock"}, []string{"relate"}, []string{"unrelate"})
	posArg(completeMvArgs, []string{"mv"})           // id, then legal statuses
	posArg(completeArchiveArgs, []string{"archive"}) // <type> then id-of-type
	posArg(completeStatusArg, []string{"status", "default"}, []string{"status", "archive"})
	posArg(completeKindArg, []string{"kind", "archive"})
	posArg(completeMetaKeyArg, []string{"meta", "get"}, []string{"meta", "set"}, []string{"meta", "del"})

	// ── task-id flags: block/unblock --on, relate/unrelate --to ──
	flagComp("on", completeTaskFlag, []string{"block"}, []string{"unblock"})
	flagComp("to", completeTaskFlag, []string{"relate"}, []string{"unrelate"})
	flagComp("kind", completeRelateKindFlag, []string{"relate"}, []string{"unrelate"})

	// ── -w / --workspace on every workspace-scoped command ──
	flagComp("workspace", completeWorkspaceFlag,
		[]string{"add"}, []string{"next"}, []string{"tree"}, []string{"relate-kinds"}, []string{"graph"},
		[]string{"meta"}, []string{"track", "new"}, []string{"segment", "new"},
		[]string{"status", "new"}, []string{"status", "ls"}, []string{"status", "default"}, []string{"status", "archive"},
		[]string{"kind", "new"}, []string{"kind", "archive"}, []string{"transition"})

	// ── --track (ws-scoped) ──
	flagComp("track", completeTrackFlag, []string{"add"}, []string{"graph"}, []string{"segment", "new"}, []string{"meta"})

	// ── enum flags ──
	flagComp("status", completeStatusFlag, []string{"add"})
	flagComp("kind", completeKindFlag, []string{"add"})
	flagComp("task", completeTaskFlag, []string{"meta"})
	flagComp("from", completeStatusFlag, []string{"transition"})
	flagComp("to", completeStatusFlag, []string{"transition"})
	flagComp("format", completeGraphFormat, []string{"graph"})
}

// completeGraphFormat offers the render formats for `graph --format` (a fixed set dot supports).
func completeGraphFormat(_ *cobra.Command, _ []string, _ string) ([]string, cobra.ShellCompDirective) {
	return []string{"svg", "png", "pdf"}, noComp
}

// ── positional completions ────────────────────────────────────────────────────

// completeTaskArg offers task ids (with titles) for the first positional only.
func completeTaskArg(_ *cobra.Command, args []string, _ string) ([]string, cobra.ShellCompDirective) {
	if len(args) != 0 {
		return nil, noComp
	}
	return allTaskCandidates(), noComp
}

// completeMvArgs: arg0 → task ids; arg1 → legal target statuses for the chosen task.
func completeMvArgs(_ *cobra.Command, args []string, _ string) ([]string, cobra.ShellCompDirective) {
	switch len(args) {
	case 0:
		return allTaskCandidates(), noComp
	case 1:
		return legalStatusCandidates(args[0]), noComp
	default:
		return nil, noComp
	}
}

// allTaskCandidates lists every task across every workspace as "id\ttitle" (there is no single
// ws-wide task read, and mv/show/done/edit resolve by global id, so scope is all workspaces).
func allTaskCandidates() []string {
	c := completeClient()
	if c == nil {
		return nil
	}
	wss, err := c.ListWorkspaces()
	if err != nil {
		return nil
	}
	var out []string
	for _, w := range wss {
		tracks, err := c.Tracks(w.ID)
		if err != nil {
			continue
		}
		for _, tr := range tracks {
			tasks, err := c.TrackTasks(tr.ID)
			if err != nil {
				continue
			}
			for _, t := range tasks {
				out = append(out, fmt.Sprintf("%d\t%s", t.ID, t.Title))
			}
		}
	}
	return out
}

// legalStatusCandidates returns the status names reachable from the task's current status.
func legalStatusCandidates(idStr string) []string {
	id, err := strconv.ParseInt(idStr, 10, 64)
	if err != nil {
		return nil
	}
	c := completeClient()
	if c == nil {
		return nil
	}
	detail, err := c.TaskDetail(id)
	if err != nil {
		return nil
	}
	ws := detail.Task.WorkspaceID
	statuses, err := c.Statuses(ws)
	if err != nil {
		return nil
	}
	trs, err := c.Transitions(ws)
	if err != nil {
		return nil
	}
	sn := map[int64]string{}
	for _, s := range statuses {
		sn[s.ID] = s.Name
	}
	var out []string
	for _, tr := range trs {
		if tr.FromStatusID == detail.Task.StatusID {
			out = append(out, sn[tr.ToStatusID])
		}
	}
	return out
}

// ── flag completions (scope from the -w flag already on the line) ─────────────

func completeWorkspaceFlag(_ *cobra.Command, _ []string, _ string) ([]string, cobra.ShellCompDirective) {
	c := completeClient()
	if c == nil {
		return nil, noComp
	}
	wss, err := c.ListWorkspaces()
	if err != nil {
		return nil, noComp
	}
	var out []string
	for _, w := range wss {
		out = append(out, w.Name)
	}
	return out, noComp
}

// wsFromFlag resolves the workspace named by the command's --workspace flag, or nil.
func wsFromFlag(cmd *cobra.Command, c *client.Client) *int64 {
	f := cmd.Flag("workspace")
	if f == nil {
		return nil
	}
	ref := f.Value.String()
	if ref == "" {
		return nil
	}
	ws, err := resolveWorkspace(c, ref)
	if err != nil {
		return nil
	}
	return &ws.ID
}

func completeTrackFlag(cmd *cobra.Command, _ []string, _ string) ([]string, cobra.ShellCompDirective) {
	c := completeClient()
	if c == nil {
		return nil, noComp
	}
	ws := wsFromFlag(cmd, c)
	if ws == nil {
		return nil, noComp
	}
	tracks, err := c.Tracks(*ws)
	if err != nil {
		return nil, noComp
	}
	var out []string
	for _, t := range tracks {
		out = append(out, t.Name)
	}
	return out, noComp
}

func completeStatusFlag(cmd *cobra.Command, _ []string, _ string) ([]string, cobra.ShellCompDirective) {
	c := completeClient()
	if c == nil {
		return nil, noComp
	}
	ws := wsFromFlag(cmd, c)
	if ws == nil {
		return nil, noComp
	}
	statuses, err := c.Statuses(*ws)
	if err != nil {
		return nil, noComp
	}
	var out []string
	for _, s := range statuses {
		out = append(out, s.Name)
	}
	return out, noComp
}

func completeKindFlag(cmd *cobra.Command, _ []string, _ string) ([]string, cobra.ShellCompDirective) {
	c := completeClient()
	if c == nil {
		return nil, noComp
	}
	ws := wsFromFlag(cmd, c)
	if ws == nil {
		return nil, noComp
	}
	kinds, err := c.Kinds(*ws)
	if err != nil {
		return nil, noComp
	}
	var out []string
	for _, k := range kinds {
		out = append(out, k.Name)
	}
	return out, noComp
}

// ── additions: task/relate-kind flags, archive/status/kind/meta positionals ───

// completeTaskFlag offers task ids for int flags that name another task (block --on, relate --to).
func completeTaskFlag(_ *cobra.Command, _ []string, _ string) ([]string, cobra.ShellCompDirective) {
	return allTaskCandidates(), noComp
}

// completeRelateKindFlag offers the relation kinds already in use in the workspace of the task
// named by the first positional (relate/unrelate --kind). Free text is still allowed.
func completeRelateKindFlag(_ *cobra.Command, args []string, _ string) ([]string, cobra.ShellCompDirective) {
	if len(args) == 0 {
		return nil, noComp
	}
	id, err := strconv.ParseInt(args[0], 10, 64)
	if err != nil {
		return nil, noComp
	}
	c := completeClient()
	if c == nil {
		return nil, noComp
	}
	detail, err := c.TaskDetail(id)
	if err != nil {
		return nil, noComp
	}
	kinds, err := c.RelatesKinds(detail.Task.WorkspaceID)
	if err != nil {
		return nil, noComp
	}
	return kinds, noComp
}

// completeArchiveArgs: arg0 → the entity type; arg1 → ids of that type (global, across workspaces).
func completeArchiveArgs(_ *cobra.Command, args []string, _ string) ([]string, cobra.ShellCompDirective) {
	switch len(args) {
	case 0:
		return []string{"task", "segment", "track", "workspace"}, noComp
	case 1:
		switch args[0] {
		case "task":
			return allTaskCandidates(), noComp
		case "workspace":
			return allWorkspaceCandidates(), noComp
		case "track":
			return allTrackCandidates(), noComp
		case "segment":
			return allSegmentCandidates(), noComp
		}
	}
	return nil, noComp
}

func allWorkspaceCandidates() []string {
	c := completeClient()
	if c == nil {
		return nil
	}
	wss, err := c.ListWorkspaces()
	if err != nil {
		return nil
	}
	var out []string
	for _, w := range wss {
		out = append(out, fmt.Sprintf("%d\t%s", w.ID, w.Name))
	}
	return out
}

func allTrackCandidates() []string {
	c := completeClient()
	if c == nil {
		return nil
	}
	wss, err := c.ListWorkspaces()
	if err != nil {
		return nil
	}
	var out []string
	for _, w := range wss {
		tracks, err := c.Tracks(w.ID)
		if err != nil {
			continue
		}
		for _, t := range tracks {
			out = append(out, fmt.Sprintf("%d\t%s / %s", t.ID, w.Name, t.Name))
		}
	}
	return out
}

func allSegmentCandidates() []string {
	c := completeClient()
	if c == nil {
		return nil
	}
	wss, err := c.ListWorkspaces()
	if err != nil {
		return nil
	}
	var out []string
	for _, w := range wss {
		tracks, err := c.Tracks(w.ID)
		if err != nil {
			continue
		}
		for _, t := range tracks {
			segs, err := c.Segments(t.ID)
			if err != nil {
				continue
			}
			for _, s := range segs {
				out = append(out, fmt.Sprintf("%d\t%s / %s / %s", s.ID, w.Name, t.Name, s.Name))
			}
		}
	}
	return out
}

// completeStatusArg / completeKindArg complete the first positional of a status/kind admin command
// (status default|archive, kind archive), scoped by the command's -w flag.
func completeStatusArg(cmd *cobra.Command, args []string, _ string) ([]string, cobra.ShellCompDirective) {
	if len(args) != 0 {
		return nil, noComp
	}
	c := completeClient()
	if c == nil {
		return nil, noComp
	}
	ws := wsFromFlag(cmd, c)
	if ws == nil {
		return nil, noComp
	}
	statuses, err := c.Statuses(*ws)
	if err != nil {
		return nil, noComp
	}
	var out []string
	for _, s := range statuses {
		out = append(out, s.Name)
	}
	return out, noComp
}

func completeKindArg(cmd *cobra.Command, args []string, _ string) ([]string, cobra.ShellCompDirective) {
	if len(args) != 0 {
		return nil, noComp
	}
	c := completeClient()
	if c == nil {
		return nil, noComp
	}
	ws := wsFromFlag(cmd, c)
	if ws == nil {
		return nil, noComp
	}
	kinds, err := c.Kinds(*ws)
	if err != nil {
		return nil, noComp
	}
	var out []string
	for _, k := range kinds {
		out = append(out, k.Name)
	}
	return out, noComp
}

// completeMetaKeyArg offers the metadata keys already set on the target entity (meta get/set/del),
// derived from whichever of --task / -w [--track] is on the line. New keys are still free text.
func completeMetaKeyArg(cmd *cobra.Command, args []string, _ string) ([]string, cobra.ShellCompDirective) {
	if len(args) != 0 {
		return nil, noComp
	}
	c := completeClient()
	if c == nil {
		return nil, noComp
	}
	if f := cmd.Flag("task"); f != nil && f.Changed {
		if id, err := strconv.ParseInt(f.Value.String(), 10, 64); err == nil {
			if d, err := c.TaskDetail(id); err == nil {
				return metaKeysFromJSON(d.Task.MetadataJSON), noComp
			}
		}
		return nil, noComp
	}
	wf := cmd.Flag("workspace")
	if wf == nil || wf.Value.String() == "" {
		return nil, noComp
	}
	ws, err := resolveWorkspace(c, wf.Value.String())
	if err != nil {
		return nil, noComp
	}
	if tf := cmd.Flag("track"); tf != nil && tf.Value.String() != "" {
		tr, err := resolveTrack(c, ws.ID, tf.Value.String())
		if err != nil {
			return nil, noComp
		}
		return metaKeysFromJSON(tr.MetadataJSON), noComp
	}
	return metaKeysFromJSON(ws.MetadataJSON), noComp
}

func metaKeysFromJSON(s string) []string {
	if s == "" {
		return nil
	}
	var m map[string]json.RawMessage
	if json.Unmarshal([]byte(s), &m) != nil {
		return nil
	}
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}
