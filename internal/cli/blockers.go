package cli

import (
	"github.com/spf13/cobra"
)

// newBlockersCmd is the inverse of `next`: `next` says what you can work on, `blockers` says
// what is in the way of something you can't. Structurally `show` — readIDs → dial → runIDs.
func newBlockersCmd() *cobra.Command {
	var depth int64
	cmd := &cobra.Command{
		Use:   "blockers <id|->",
		Short: "what unfinished work is blocking a task (`-` reads ids from stdin)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ids, err := readIDs(cmd, args[0])
			if err != nil {
				return err
			}
			var depthPtr *int64
			if cmd.Flags().Changed("depth") {
				d := depth
				depthPtr = &d
			}
			c, err := dial()
			if err != nil {
				return err
			}
			// -q emits the BLOCKER ids, not the queried id — a deliberate divergence from `show -q`
			// and the whole point of the command: `stx blockers 42 -q | stx done -` clears the path.
			var blockers []int64
			var res []any
			var lines []string
			runErr := runIDs(cmd, ids, func(id int64) error {
				items, err := c.Blockers(id, depthPtr)
				if err != nil {
					return err
				}
				res = append(res, items)
				for _, b := range items {
					blockers = append(blockers, b.ID)
				}
				if flagJSON || flagQuiet {
					return nil // the status registry is only needed for the text render
				}
				detail, err := c.TaskDetail(id)
				if err != nil {
					return err
				}
				sn, err := statusNames(c, detail.Task.WorkspaceID)
				if err != nil {
					return err
				}
				lines = append(lines, renderBlockers(id, items, sn))
				return nil
			})
			if runErr != nil {
				return runErr
			}
			// Nothing blocking is a legitimate empty result set — exit 1, per the grep convention,
			// so `if stx blockers 42 -q >/dev/null` reads as "is it blocked?".
			if len(blockers) == 0 {
				markEmpty()
			}
			// Not emitBatch: it prints nothing when the id list is empty, and "nothing is blocking
			// this" is exactly the answer worth printing. The quiet lines are the blockers'.
			return emitLines(cmd, idLines(blockers), unwrapOne(res), joinLines(lines))
		},
	}
	// The 0 is "flag not given" (the param is then omitted and the daemon's own default applies),
	// not a usable value — the daemon rejects depth < 1, so say what the real default is.
	cmd.Flags().Int64Var(&depth, "depth", 0, "stop the walk after N hops (default 64)")
	return cmd
}
