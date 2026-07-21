package cli

import (
	"fmt"

	"github.com/phansen314/stx/internal/client"
	"github.com/spf13/cobra"
)

// edgeRun parses the task id, dials, runs op, then emits the raw daemon response (--json) or the
// fixed status line. op returns (rawResponse, textLine, err).
func edgeRun(cmd *cobra.Command, idArg string, op func(*client.Client, int64) (any, string, error)) error {
	id, err := parseID(idArg)
	if err != nil {
		return err
	}
	c, err := dial()
	if err != nil {
		return err
	}
	res, text, err := op(c, id)
	if err != nil {
		return err
	}
	if flagJSON {
		return printJSON(cmd, res)
	}
	fmt.Fprintln(cmd.OutOrStdout(), text)
	return nil
}

func newBlockCmd() *cobra.Command {
	var on int64
	cmd := &cobra.Command{
		Use:   "block <id> --on <blocker-id>",
		Short: "mark a task blocked by another",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			return edgeRun(cmd, args[0], func(c *client.Client, id int64) (any, string, error) {
				res, err := c.AddBlocks(on, id)
				return res, fmt.Sprintf("#%d now blocked by #%d", id, on), err
			})
		},
	}
	cmd.Flags().Int64Var(&on, "on", 0, "the blocker task id")
	_ = cmd.MarkFlagRequired("on")
	return cmd
}

func newUnblockCmd() *cobra.Command {
	var on int64
	cmd := &cobra.Command{
		Use:   "unblock <id> --on <blocker-id>",
		Short: "remove a blocks edge (mirror of `block`)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			return edgeRun(cmd, args[0], func(c *client.Client, id int64) (any, string, error) {
				res, err := c.RemoveBlocks(on, id)
				return res, fmt.Sprintf("#%d no longer blocked by #%d", id, on), err
			})
		},
	}
	cmd.Flags().Int64Var(&on, "on", 0, "the blocker task id")
	_ = cmd.MarkFlagRequired("on")
	return cmd
}

func newRelateCmd() *cobra.Command {
	var to int64
	var kind string
	cmd := &cobra.Command{
		Use:   "relate <id> --to <id> --kind <k>",
		Short: "add a relation between tasks",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			return edgeRun(cmd, args[0], func(c *client.Client, id int64) (any, string, error) {
				res, err := c.AddRelates(kind, id, to)
				return res, fmt.Sprintf("#%d %s #%d", id, kind, to), err
			})
		},
	}
	cmd.Flags().Int64Var(&to, "to", 0, "the other task id")
	cmd.Flags().StringVar(&kind, "kind", "", "relation kind (e.g. relates_to, spawns)")
	_ = cmd.MarkFlagRequired("to")
	_ = cmd.MarkFlagRequired("kind")
	return cmd
}

func newUnrelateCmd() *cobra.Command {
	var to int64
	var kind string
	cmd := &cobra.Command{
		Use:   "unrelate <id> --to <id> --kind <k>",
		Short: "remove a relation (mirror of `relate`)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			return edgeRun(cmd, args[0], func(c *client.Client, id int64) (any, string, error) {
				res, err := c.RemoveRelates(kind, id, to)
				return res, fmt.Sprintf("#%d no longer %s #%d", id, kind, to), err
			})
		},
	}
	cmd.Flags().Int64Var(&to, "to", 0, "the other task id")
	cmd.Flags().StringVar(&kind, "kind", "", "relation kind to remove")
	_ = cmd.MarkFlagRequired("to")
	_ = cmd.MarkFlagRequired("kind")
	return cmd
}

func newRelateKindsCmd() *cobra.Command {
	var wsFlag string
	cmd := &cobra.Command{
		Use:   "relate-kinds",
		Short: "list relation kinds currently in use",
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
			kinds, err := c.RelatesKinds(ws.ID)
			if err != nil {
				return err
			}
			if flagJSON {
				return printJSON(cmd, map[string]any{"items": kinds})
			}
			out := "(no relation kinds in use)"
			if len(kinds) > 0 {
				out = joinLines(kinds)
			}
			fmt.Fprintln(cmd.OutOrStdout(), out)
			return nil
		},
	}
	cmd.Flags().StringVarP(&wsFlag, "workspace", "w", "", "workspace name or id (required)")
	return cmd
}
