package cli

import "github.com/spf13/cobra"

func newShowCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "show <id|->",
		Short: "task detail + edges (`-` reads ids from stdin)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ids, err := readIDs(cmd, args[0])
			if err != nil {
				return err
			}
			c, err := dial()
			if err != nil {
				return err
			}
			var shown []int64
			var res []any
			var lines []string
			runErr := runIDs(cmd, ids, func(id int64) error {
				detail, err := c.TaskDetail(id)
				if err != nil {
					return err
				}
				shown = append(shown, detail.Task.ID)
				res = append(res, detail) // verbatim daemon shape {task, blocksIn, blocksOut, relates}
				if flagJSON || flagQuiet {
					return nil // the status/kind registries are only needed for the text render
				}
				ws := detail.Task.WorkspaceID
				sn, err := statusNames(c, ws)
				if err != nil {
					return err
				}
				kn, err := kindNames(c, ws)
				if err != nil {
					return err
				}
				lines = append(lines, renderTaskDetail(detail, sn, kn))
				return nil
			})
			return emitBatch(cmd, shown, res, lines, runErr)
		},
	}
}
