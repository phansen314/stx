package cli

import (
	"fmt"

	"github.com/spf13/cobra"
)

// archivePath maps the user-facing entity type to the daemon's plural archive path.
var archivePath = map[string]string{
	"task": "tasks", "segment": "segments", "track": "tracks", "workspace": "workspaces",
}

func newArchiveCmd() *cobra.Command {
	var yes bool
	cmd := &cobra.Command{
		Use:   "archive <task|segment|track|workspace> <id|->",
		Short: "archive an entity (`-` reads ids from stdin)",
		Args:  cobra.ExactArgs(2),
		// completion (types for arg0, live ids-of-type for arg1) is wired in registerCompletions;
		// no static ValidArgs — cobra ignores ValidArgsFunction when ValidArgs is also set.
		RunE: func(cmd *cobra.Command, args []string) error {
			typ := args[0]
			path, ok := archivePath[typ]
			if !ok {
				return fmt.Errorf("invalid type %q — one of task|segment|track|workspace", typ)
			}
			ids, err := readIDs(cmd, args[1])
			if err != nil {
				return err
			}
			if (typ == "track" || typ == "workspace") && !yes {
				return fmt.Errorf("archiving a %s cascades to its children — pass --yes to confirm", typ)
			}
			c, err := dial()
			if err != nil {
				return err
			}
			var archived []int64
			var res []any
			var lines []string
			runErr := runIDs(cmd, ids, func(id int64) error {
				if err := c.Archive(path, id); err != nil {
					return err
				}
				archived = append(archived, id)
				res = append(res, map[string]any{"archived": typ, "id": id})
				lines = append(lines, fmt.Sprintf("archived %s #%d", typ, id))
				return nil
			})
			return emitBatch(cmd, archived, res, lines, runErr)
		},
	}
	cmd.Flags().BoolVar(&yes, "yes", false, "confirm the cascade for track/workspace")
	return cmd
}
