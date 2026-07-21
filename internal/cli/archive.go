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
		Use:       "archive <task|segment|track|workspace> <id>",
		Short:     "archive an entity",
		Args:      cobra.ExactArgs(2),
		ValidArgs: []string{"task", "segment", "track", "workspace"},
		RunE: func(cmd *cobra.Command, args []string) error {
			typ := args[0]
			path, ok := archivePath[typ]
			if !ok {
				return fmt.Errorf("invalid type %q — one of task|segment|track|workspace", typ)
			}
			id, err := parseID(args[1])
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
			if err := c.Archive(path, id); err != nil {
				return err
			}
			if flagJSON {
				return printJSON(cmd, map[string]any{"archived": typ, "id": id})
			}
			fmt.Fprintf(cmd.OutOrStdout(), "archived %s #%d\n", typ, id)
			return nil
		},
	}
	cmd.Flags().BoolVar(&yes, "yes", false, "confirm the cascade for track/workspace")
	return cmd
}
