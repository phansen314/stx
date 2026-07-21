package cli

import (
	"errors"
	"fmt"

	"github.com/phansen314/stx/internal/api"
	"github.com/spf13/cobra"
)

func newEditCmd() *cobra.Command {
	var title, desc string
	var priority int
	cmd := &cobra.Command{
		Use:   "edit <id>",
		Short: "edit a task",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id, err := parseID(args[0])
			if err != nil {
				return err
			}
			// only send fields the user actually passed (mirrors Python's `is not None`)
			changes := map[string]any{}
			if cmd.Flags().Changed("title") {
				changes["title"] = title
			}
			if cmd.Flags().Changed("desc") {
				changes["description"] = desc
			}
			if cmd.Flags().Changed("priority") {
				changes["priority"] = priority
			}
			if len(changes) == 0 {
				return errors.New("nothing to edit — pass --title/--desc/--priority")
			}
			c, err := dial()
			if err != nil {
				return err
			}
			task, err := retryConflict(
				func() (int, error) {
					d, e := c.TaskDetail(id)
					return d.Task.Version, e
				},
				func(v int) (api.Task, error) {
					return c.EditTask(id, v, changes)
				},
			)
			if err != nil {
				return err
			}
			if flagJSON {
				return printJSON(cmd, task)
			}
			fmt.Fprintf(cmd.OutOrStdout(), "edited #%d  %s\n", task.ID, task.Title)
			return nil
		},
	}
	cmd.Flags().StringVar(&title, "title", "", "new title")
	cmd.Flags().StringVar(&desc, "desc", "", "new description")
	cmd.Flags().IntVar(&priority, "priority", 0, "new priority")
	return cmd
}
