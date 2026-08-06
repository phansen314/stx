package cli

import (
	"errors"
	"fmt"
	"time"

	"github.com/phansen314/stx/internal/api"
	"github.com/phansen314/stx/internal/client"
	"github.com/spf13/cobra"
)

// wsRow is the ls --json element — a custom {id,name,tracks} shape (not a raw DTO), matching
// Python's cmd_ls payload exactly so the parity harness diffs clean.
type wsRow struct {
	ID     int64  `json:"id"`
	Name   string `json:"name"`
	Tracks int    `json:"tracks"`
}

func newLsCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "ls",
		Short: "list workspaces",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			c, err := dial()
			if err != nil {
				return err
			}
			wss, err := c.ListWorkspaces()
			if err != nil {
				return err
			}
			rows := make([]wsRow, 0, len(wss))
			for _, w := range wss {
				tr, err := c.Tracks(w.ID)
				if err != nil {
					return err
				}
				rows = append(rows, wsRow{ID: w.ID, Name: w.Name, Tracks: len(tr)})
			}
			if len(rows) == 0 {
				markEmpty()
				return emit(cmd, nil, rows, "(no workspaces)")
			}
			ids := make([]int64, 0, len(rows))
			lines := make([]string, 0, len(rows))
			for _, r := range rows {
				plural := "s"
				if r.Tracks == 1 {
					plural = ""
				}
				ids = append(ids, r.ID)
				lines = append(lines, fmt.Sprintf("%4d  %s  (%d track%s)", r.ID, r.Name, r.Tracks, plural))
			}
			return emit(cmd, ids, rows, joinLines(lines))
		},
	}
}

func newNextCmd() *cobra.Command {
	var wsFlag, trackFlag, kindFlag, agentFlag string
	var segFlag, limitFlag int64
	var claimFlag bool
	var ttlFlag time.Duration
	cmd := &cobra.Command{
		Use:   "next",
		Short: "ready tasks (frontier); --claim reserves them for an agent",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			// A lease needs a holder: claiming anonymously would reserve work nobody could release.
			if claimFlag && agentFlag == "" {
				return errors.New("--claim needs --as <agent> — a lease has to belong to someone")
			}
			c, err := dial()
			if err != nil {
				return err
			}
			ws, err := resolveWorkspace(c, wsFlag)
			if err != nil {
				return err
			}
			p := client.NextParams{Workspace: ws.ID, As: agentFlag}
			if trackFlag != "" {
				tr, err := resolveTrack(c, ws.ID, trackFlag)
				if err != nil {
					return err
				}
				id := tr.ID
				p.Track = &id
			}
			// The kind filter is orthogonal to scope: "what impl work is ready here". Resolved
			// through the registry the same way `add --kind` does, so a typo is an error with the
			// live kinds listed, not a silently empty frontier.
			if kindFlag != "" {
				kinds, err := c.Kinds(ws.ID)
				if err != nil {
					return err
				}
				k, err := resolveKindIn(kinds, kindFlag)
				if err != nil {
					return err
				}
				p.Kind = &k.ID
			}
			if cmd.Flags().Changed("segment") {
				s := segFlag
				p.Segment = &s
			}
			if cmd.Flags().Changed("limit") {
				l := limitFlag
				p.Limit = &l
			}
			// --claim goes through the fused POST so the select and the reservation share one
			// transaction; without it two agents reading the same frontier both start the same task.
			var items []api.FrontierItem
			if claimFlag {
				secs, err := ttlSeconds(ttlFlag)
				if err != nil {
					return err
				}
				items, err = c.NextAndClaim(p, agentFlag, secs)
				if err != nil {
					return err
				}
			} else if items, err = c.Next(p); err != nil {
				return err
			}
			if len(items) == 0 {
				markEmpty()
				return emit(cmd, nil, items, renderFrontier(items, nil))
			}
			ids := make([]int64, 0, len(items))
			for _, i := range items {
				ids = append(ids, i.ID)
			}
			if flagQuiet { // skip the status lookup nobody's going to see
				return emit(cmd, ids, items, "")
			}
			sn, err := statusNames(c, ws.ID)
			if err != nil {
				return err
			}
			// --json stays a bare array of verbatim wire items
			return emit(cmd, ids, items, renderFrontier(items, sn))
		},
	}
	cmd.Flags().StringVarP(&wsFlag, "workspace", "w", "", "workspace name or id (required)")
	cmd.Flags().StringVarP(&trackFlag, "track", "t", "", "scope to a track (name or id)")
	cmd.Flags().Int64VarP(&segFlag, "segment", "s", 0, "scope to a segment subtree (id)")
	cmd.Flags().StringVar(&kindFlag, "kind", "", "restrict to a kind (name or id)")
	cmd.Flags().Int64Var(&limitFlag, "limit", 0, "max rows")
	cmd.Flags().StringVar(&agentFlag, "as", "", "agent id — keeps your own leases visible")
	cmd.Flags().BoolVar(&claimFlag, "claim", false, "reserve what it returns (needs --as)")
	cmd.Flags().DurationVar(&ttlFlag, "ttl", defaultTTL, "lease length for --claim (e.g. 30s, 15m, 2h)")
	return cmd
}

// newClaimsCmd is the human-facing "who is on what". Only live leases are rows — an expired one is
// not a claim, and nothing sweeps them, so listing them would be listing noise.
func newClaimsCmd() *cobra.Command {
	var wsFlag string
	cmd := &cobra.Command{
		Use:   "claims",
		Short: "live agent leases in a workspace",
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
			claims, err := c.Claims(ws.ID)
			if err != nil {
				return err
			}
			if len(claims) == 0 {
				markEmpty()
				return emit(cmd, nil, claims, "(no live claims)")
			}
			ids := make([]int64, 0, len(claims))
			lines := make([]string, 0, len(claims))
			for _, cl := range claims {
				ids = append(ids, cl.ID)
				lines = append(lines, fmt.Sprintf("%4d  %-16s until %s  %s", cl.ID, cl.ClaimedBy, cl.ClaimedUntil, cl.Title))
			}
			return emit(cmd, ids, claims, joinLines(lines))
		},
	}
	cmd.Flags().StringVarP(&wsFlag, "workspace", "w", "", "workspace name or id (required)")
	return cmd
}

// tree --json payload (custom flat-per-track shape, matching Python cmd_tree exactly).
type treeTask struct {
	ID        int64   `json:"id"`
	Title     string  `json:"title"`
	Priority  int     `json:"priority"`
	Status    *string `json:"status"` // resolved name, or null if unresolved (Python sn.get)
	SegmentID int64   `json:"segmentId"`
}

type treeTrack struct {
	Track string     `json:"track"`
	ID    int64      `json:"id"`
	Tasks []treeTask `json:"tasks"`
}

type treePayload struct {
	Workspace string      `json:"workspace"`
	Tracks    []treeTrack `json:"tracks"`
}

func newTreeCmd() *cobra.Command {
	var wsFlag string
	cmd := &cobra.Command{
		Use:   "tree",
		Short: "show a workspace as a tree",
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
			tracks, err := c.Tracks(ws.ID)
			if err != nil {
				return err
			}
			sn, err := statusNames(c, ws.ID)
			if err != nil {
				return err
			}
			blocks := make([]trackBlock, 0, len(tracks))
			payloadTracks := make([]treeTrack, 0, len(tracks))
			for _, t := range tracks {
				segs, err := c.Segments(t.ID)
				if err != nil {
					return err
				}
				tasks, err := c.TrackTasks(t.ID)
				if err != nil {
					return err
				}
				blocks = append(blocks, trackBlock{Track: t, Segments: segs, Tasks: tasks})
				tt := treeTrack{Track: t.Name, ID: t.ID, Tasks: make([]treeTask, 0, len(tasks))}
				for _, x := range tasks {
					var st *string
					if n, ok := sn[x.StatusID]; ok {
						name := n
						st = &name
					}
					tt.Tasks = append(tt.Tasks, treeTask{
						ID: x.ID, Title: x.Title, Priority: x.Priority, Status: st, SegmentID: x.SegmentID,
					})
				}
				payloadTracks = append(payloadTracks, tt)
			}
			ids := treeTaskIDs(blocks)
			if len(blocks) == 0 && len(ids) == 0 {
				markEmpty()
			}
			return emit(cmd, ids, treePayload{Workspace: ws.Name, Tracks: payloadTracks},
				renderTree(ws, blocks, sn))
		},
	}
	cmd.Flags().StringVarP(&wsFlag, "workspace", "w", "", "workspace name or id (required)")
	return cmd
}
