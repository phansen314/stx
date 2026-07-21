package cli

import (
	"fmt"

	"github.com/spf13/cobra"
)

// addWsFlag adds the shared -w/--workspace flag to a leaf admin command.
func addWsFlag(cmd *cobra.Command, dst *string) {
	cmd.Flags().StringVarP(dst, "workspace", "w", "", "workspace name or id (required)")
}

func newWsCmd() *cobra.Command {
	ws := &cobra.Command{Use: "ws", Short: "workspace admin"}
	create := &cobra.Command{
		Use: "new <name>", Short: "create a workspace", Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			c, err := dial()
			if err != nil {
				return err
			}
			w, err := c.CreateWorkspace(args[0])
			if err != nil {
				return err
			}
			return emitEntity(cmd, fmt.Sprintf("workspace #%d  %s", w.ID, w.Name), w)
		},
	}
	ws.AddCommand(create)
	return ws
}

func newTrackCmd() *cobra.Command {
	track := &cobra.Command{Use: "track", Short: "track admin"}
	var wsFlag, desc string
	create := &cobra.Command{
		Use: "new <name>", Short: "create a track", Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			c, err := dial()
			if err != nil {
				return err
			}
			ws, err := resolveWorkspace(c, wsFlag)
			if err != nil {
				return err
			}
			tr, err := c.CreateTrack(ws.ID, args[0], desc)
			if err != nil {
				return err
			}
			return emitEntity(cmd, fmt.Sprintf("track #%d  %s", tr.ID, tr.Name), tr)
		},
	}
	addWsFlag(create, &wsFlag)
	create.Flags().StringVar(&desc, "desc", "", "description")
	track.AddCommand(create)
	return track
}

func newSegmentCmd() *cobra.Command {
	segment := &cobra.Command{Use: "segment", Short: "segment admin"}
	var wsFlag, trackFlag string
	var parent int64
	create := &cobra.Command{
		Use: "new <name>", Short: "create a segment", Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			c, err := dial()
			if err != nil {
				return err
			}
			ws, err := resolveWorkspace(c, wsFlag)
			if err != nil {
				return err
			}
			tr, err := resolveTrack(c, ws.ID, trackFlag)
			if err != nil {
				return err
			}
			var parentPtr *int64
			if cmd.Flags().Changed("parent") {
				p := parent
				parentPtr = &p
			}
			seg, err := c.CreateSegment(tr.ID, args[0], parentPtr)
			if err != nil {
				return err
			}
			return emitEntity(cmd, fmt.Sprintf("segment #%d  %s", seg.ID, seg.Name), seg)
		},
	}
	addWsFlag(create, &wsFlag)
	create.Flags().StringVarP(&trackFlag, "track", "t", "", "track name or id (required)")
	_ = create.MarkFlagRequired("track")
	create.Flags().Int64Var(&parent, "parent", 0, "parent segment id")
	segment.AddCommand(create)
	return segment
}

func newStatusCmd() *cobra.Command {
	status := &cobra.Command{Use: "status", Short: "status admin"}

	var lsWs string
	list := &cobra.Command{
		Use: "ls", Short: "list statuses (kanban order)", Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			c, err := dial()
			if err != nil {
				return err
			}
			ws, err := resolveWorkspace(c, lsWs)
			if err != nil {
				return err
			}
			statuses, err := c.Statuses(ws.ID)
			if err != nil {
				return err
			}
			if flagJSON {
				return printJSON(cmd, statuses)
			}
			out := cmd.OutOrStdout()
			for _, s := range statuses {
				tag := ""
				if s.IsDefault {
					tag += " (default)"
				}
				if s.Terminal {
					tag += " (terminal)"
				}
				fmt.Fprintf(out, "%4d  %s%s\n", s.ID, s.Name, tag)
			}
			return nil
		},
	}
	addWsFlag(list, &lsWs)

	var newWs string
	var order int
	var terminal bool
	create := &cobra.Command{
		Use: "new <name>", Short: "create a status", Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			c, err := dial()
			if err != nil {
				return err
			}
			ws, err := resolveWorkspace(c, newWs)
			if err != nil {
				return err
			}
			s, err := c.CreateStatus(ws.ID, args[0], order, terminal)
			if err != nil {
				return err
			}
			return emitEntity(cmd, fmt.Sprintf("status #%d  %s", s.ID, s.Name), s)
		},
	}
	addWsFlag(create, &newWs)
	create.Flags().IntVar(&order, "order", 0, "kanban order (required)")
	_ = create.MarkFlagRequired("order")
	create.Flags().BoolVar(&terminal, "terminal", false, "this status means done")

	var defWs string
	setDefault := &cobra.Command{
		Use: "default <status>", Short: "set the default status", Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			c, err := dial()
			if err != nil {
				return err
			}
			ws, err := resolveWorkspace(c, defWs)
			if err != nil {
				return err
			}
			statuses, err := c.Statuses(ws.ID)
			if err != nil {
				return err
			}
			s, err := resolveStatusIn(statuses, args[0])
			if err != nil {
				return err
			}
			if err := c.SetDefaultStatus(ws.ID, s.ID); err != nil {
				return err
			}
			return emitEntity(cmd, fmt.Sprintf("default status → %s", s.Name), map[string]any{"default": s.Name})
		},
	}
	addWsFlag(setDefault, &defWs)

	var arcWs string
	archive := &cobra.Command{
		Use: "archive <status>", Short: "archive a status", Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			c, err := dial()
			if err != nil {
				return err
			}
			ws, err := resolveWorkspace(c, arcWs)
			if err != nil {
				return err
			}
			statuses, err := c.Statuses(ws.ID)
			if err != nil {
				return err
			}
			s, err := resolveStatusIn(statuses, args[0])
			if err != nil {
				return err
			}
			if err := c.ArchiveStatus(ws.ID, s.ID); err != nil {
				return err
			}
			return emitEntity(cmd, fmt.Sprintf("archived status %s", s.Name),
				map[string]any{"archived": "status", "id": s.ID})
		},
	}
	addWsFlag(archive, &arcWs)

	status.AddCommand(list, create, setDefault, archive)
	return status
}

func newKindCmd() *cobra.Command {
	kind := &cobra.Command{Use: "kind", Short: "kind admin"}

	var newWs string
	create := &cobra.Command{
		Use: "new <name>", Short: "create a kind", Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			c, err := dial()
			if err != nil {
				return err
			}
			ws, err := resolveWorkspace(c, newWs)
			if err != nil {
				return err
			}
			k, err := c.CreateKind(ws.ID, args[0])
			if err != nil {
				return err
			}
			return emitEntity(cmd, fmt.Sprintf("kind #%d  %s", k.ID, k.Name), k)
		},
	}
	addWsFlag(create, &newWs)

	var arcWs string
	archive := &cobra.Command{
		Use: "archive <name>", Short: "archive a kind", Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			c, err := dial()
			if err != nil {
				return err
			}
			ws, err := resolveWorkspace(c, arcWs)
			if err != nil {
				return err
			}
			kinds, err := c.Kinds(ws.ID)
			if err != nil {
				return err
			}
			k, err := resolveKindIn(kinds, args[0])
			if err != nil {
				return err
			}
			if err := c.ArchiveKind(ws.ID, k.ID); err != nil {
				return err
			}
			return emitEntity(cmd, fmt.Sprintf("archived kind %s", k.Name),
				map[string]any{"archived": "kind", "id": k.ID})
		},
	}
	addWsFlag(archive, &arcWs)

	kind.AddCommand(create, archive)
	return kind
}

func newTransitionCmd() *cobra.Command {
	var wsFlag, from, to string
	cmd := &cobra.Command{
		Use:   "transition",
		Short: "add a status transition",
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
			statuses, err := c.Statuses(ws.ID)
			if err != nil {
				return err
			}
			f, err := resolveStatusIn(statuses, from)
			if err != nil {
				return err
			}
			t, err := resolveStatusIn(statuses, to)
			if err != nil {
				return err
			}
			tr, err := c.CreateTransition(ws.ID, f.ID, t.ID)
			if err != nil {
				return err
			}
			return emitEntity(cmd, fmt.Sprintf("transition %s → %s", f.Name, t.Name), tr)
		},
	}
	addWsFlag(cmd, &wsFlag)
	cmd.Flags().StringVar(&from, "from", "", "from status name or id")
	cmd.Flags().StringVar(&to, "to", "", "to status name or id")
	_ = cmd.MarkFlagRequired("from")
	_ = cmd.MarkFlagRequired("to")
	return cmd
}
