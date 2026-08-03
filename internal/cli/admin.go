package cli

import (
	"errors"
	"fmt"
	"strconv"

	"github.com/phansen314/stx/internal/api"
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
			return emit(cmd, []int64{w.ID}, w, fmt.Sprintf("workspace #%d  %s", w.ID, w.Name))
		},
	}
	var renameWs string
	rename := &cobra.Command{
		Use: "rename <new-name>", Short: "rename a workspace", Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			c, err := dial()
			if err != nil {
				return err
			}
			ws, err := resolveWorkspace(c, renameWs)
			if err != nil {
				return err
			}
			// The CAS re-read resolves by *id*, never by the name the user typed: on a retry the
			// old name may already be gone (that's what the conflict means).
			byID := strconv.FormatInt(ws.ID, 10)
			w, err := retryConflict(
				func() (int, error) { x, e := resolveWorkspace(c, byID); return x.Version, e },
				func(v int) (api.Workspace, error) {
					return c.EditWorkspace(ws.ID, v, map[string]any{"name": args[0]})
				},
			)
			if err != nil {
				return err
			}
			return emit(cmd, []int64{w.ID}, w, fmt.Sprintf("renamed #%d  %s", w.ID, w.Name))
		},
	}
	addWsFlag(rename, &renameWs)
	ws.AddCommand(create, rename)
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
			return emit(cmd, []int64{tr.ID}, tr, fmt.Sprintf("track #%d  %s", tr.ID, tr.Name))
		},
	}
	addWsFlag(create, &wsFlag)
	create.Flags().StringVar(&desc, "desc", "", "description")

	var editWs, editName, editDesc string
	edit := &cobra.Command{
		Use: "edit <track>", Short: "rename a track or change its description", Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			// No $EDITOR implication here: that rule is task-specific (see `stx edit`), and
			// widening it to containers is a separate decision.
			changes := map[string]any{}
			if cmd.Flags().Changed("name") {
				changes["name"] = editName
			}
			if cmd.Flags().Changed("desc") {
				d, err := readValue(cmd, editDesc, "--desc")
				if err != nil {
					return err
				}
				changes["description"] = d
			}
			if len(changes) == 0 {
				return errors.New("nothing to edit — pass --name and/or --desc")
			}
			c, err := dial()
			if err != nil {
				return err
			}
			ws, err := resolveWorkspace(c, editWs)
			if err != nil {
				return err
			}
			tr, err := resolveTrack(c, ws.ID, args[0])
			if err != nil {
				return err
			}
			byID := strconv.FormatInt(tr.ID, 10) // re-read by id — see ws rename
			out, err := retryConflict(
				func() (int, error) { x, e := resolveTrack(c, ws.ID, byID); return x.Version, e },
				func(v int) (api.Track, error) { return c.EditTrack(tr.ID, v, changes) },
			)
			if err != nil {
				return err
			}
			return emit(cmd, []int64{out.ID}, out, fmt.Sprintf("edited track #%d  %s", out.ID, out.Name))
		},
	}
	addWsFlag(edit, &editWs)
	edit.Flags().StringVar(&editName, "name", "", "new name")
	edit.Flags().StringVar(&editDesc, "desc", "", "new description (`-` reads it from stdin)")

	track.AddCommand(create, edit)
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
			return emit(cmd, []int64{seg.ID}, seg, fmt.Sprintf("segment #%d  %s", seg.ID, seg.Name))
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
			if len(statuses) == 0 {
				markEmpty()
			}
			ids := make([]int64, 0, len(statuses))
			lines := make([]string, 0, len(statuses))
			for _, s := range statuses {
				tag := ""
				if s.IsDefault {
					tag += " (default)"
				}
				if s.Terminal {
					tag += " (terminal)"
				}
				ids = append(ids, s.ID)
				lines = append(lines, fmt.Sprintf("%4d  %s%s", s.ID, s.Name, tag))
			}
			return emit(cmd, ids, statuses, joinLines(lines))
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
			return emit(cmd, []int64{s.ID}, s, fmt.Sprintf("status #%d  %s", s.ID, s.Name))
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
			return emit(cmd, []int64{s.ID}, map[string]any{"default": s.Name},
				fmt.Sprintf("default status → %s", s.Name))
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
			return emit(cmd, []int64{s.ID}, map[string]any{"archived": "status", "id": s.ID},
				fmt.Sprintf("archived status %s", s.Name))
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
			return emit(cmd, []int64{k.ID}, k, fmt.Sprintf("kind #%d  %s", k.ID, k.Name))
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
			return emit(cmd, []int64{k.ID}, map[string]any{"archived": "kind", "id": k.ID},
				fmt.Sprintf("archived kind %s", k.Name))
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
			return emit(cmd, []int64{tr.ID}, tr, fmt.Sprintf("transition %s → %s", f.Name, t.Name))
		},
	}
	addWsFlag(cmd, &wsFlag)
	cmd.Flags().StringVar(&from, "from", "", "from status name or id")
	cmd.Flags().StringVar(&to, "to", "", "to status name or id")
	_ = cmd.MarkFlagRequired("from")
	_ = cmd.MarkFlagRequired("to")
	return cmd
}
