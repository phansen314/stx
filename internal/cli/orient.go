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
