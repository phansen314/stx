package cli

import (
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
	byName := map[string]*cobra.Command{}
	for _, c := range root.Commands() {
		byName[c.Name()] = c
	}

	// first positional = a task id, on the id-taking commands.
	for _, n := range []string{"show", "edit", "done"} {
		if c := byName[n]; c != nil {
			c.ValidArgsFunction = completeTaskArg
		}
	}
	// mv <id> <status>: id first, then the legal transitions from that task's current status.
	if c := byName["mv"]; c != nil {
		c.ValidArgsFunction = completeMvArgs
	}

	// flag values.
	if c := byName["add"]; c != nil {
		_ = c.RegisterFlagCompletionFunc("workspace", completeWorkspaceFlag)
		_ = c.RegisterFlagCompletionFunc("track", completeTrackFlag)
		_ = c.RegisterFlagCompletionFunc("status", completeStatusFlag)
		_ = c.RegisterFlagCompletionFunc("kind", completeKindFlag)
	}
	for _, n := range []string{"next", "tree"} {
		if c := byName[n]; c != nil {
			_ = c.RegisterFlagCompletionFunc("workspace", completeWorkspaceFlag)
		}
	}
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
	ref := cmd.Flag("workspace").Value.String()
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
