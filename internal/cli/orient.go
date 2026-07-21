package cli

import (
	"fmt"

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
			if flagJSON {
				return printJSON(cmd, rows)
			}
			out := cmd.OutOrStdout()
			if len(rows) == 0 {
				fmt.Fprintln(out, "(no workspaces)")
				return nil
			}
			for _, r := range rows {
				plural := "s"
				if r.Tracks == 1 {
					plural = ""
				}
				fmt.Fprintf(out, "%4d  %s  (%d track%s)\n", r.ID, r.Name, r.Tracks, plural)
			}
			return nil
		},
	}
}

func newNextCmd() *cobra.Command {
	var wsFlag, trackFlag string
	var segFlag, limitFlag int64
	cmd := &cobra.Command{
		Use:   "next",
		Short: "ready tasks (frontier)",
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
			var trackPtr, segPtr, limitPtr *int64
			if trackFlag != "" {
				tr, err := resolveTrack(c, ws.ID, trackFlag)
				if err != nil {
					return err
				}
				id := tr.ID
				trackPtr = &id
			}
			if cmd.Flags().Changed("segment") {
				s := segFlag
				segPtr = &s
			}
			if cmd.Flags().Changed("limit") {
				l := limitFlag
				limitPtr = &l
			}
			items, err := c.Next(ws.ID, trackPtr, segPtr, limitPtr)
			if err != nil {
				return err
			}
			if flagJSON {
				return printJSON(cmd, items) // bare array, verbatim wire items
			}
			sn, err := statusNames(c, ws.ID)
			if err != nil {
				return err
			}
			fmt.Fprintln(cmd.OutOrStdout(), renderFrontier(items, sn))
			return nil
		},
	}
	cmd.Flags().StringVarP(&wsFlag, "workspace", "w", "", "workspace name or id (required)")
	cmd.Flags().StringVarP(&trackFlag, "track", "t", "", "scope to a track (name or id)")
	cmd.Flags().Int64VarP(&segFlag, "segment", "s", 0, "scope to a segment subtree (id)")
	cmd.Flags().Int64Var(&limitFlag, "limit", 0, "max rows")
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
			if flagJSON {
				return printJSON(cmd, treePayload{Workspace: ws.Name, Tracks: payloadTracks})
			}
			fmt.Fprintln(cmd.OutOrStdout(), renderTree(ws, blocks, sn))
			return nil
		},
	}
	cmd.Flags().StringVarP(&wsFlag, "workspace", "w", "", "workspace name or id (required)")
	return cmd
}
