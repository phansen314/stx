package cli

import (
	"fmt"

	"github.com/spf13/cobra"
)

func newShowCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "show <id>",
		Short: "task detail + edges",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id, err := parseID(args[0])
			if err != nil {
				return err
			}
			c, err := dial()
			if err != nil {
				return err
			}
			detail, err := c.TaskDetail(id)
			if err != nil {
				return err
			}
			if flagJSON {
				return printJSON(cmd, detail) // verbatim daemon shape {task, blocksIn, blocksOut, relates}
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
			fmt.Fprintln(cmd.OutOrStdout(), renderTaskDetail(detail, sn, kn))
			return nil
		},
	}
}
