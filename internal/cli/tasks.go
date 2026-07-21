package cli

import (
	"errors"
	"fmt"
	"strconv"
	"strings"

	"github.com/phansen314/stx/internal/api"
	"github.com/phansen314/stx/internal/client"
	"github.com/spf13/cobra"
)

func newAddCmd() *cobra.Command {
	var wsFlag, trackFlag, statusFlag, kindFlag, descFlag string
	var segFlag int64
	var prioFlag int
	cmd := &cobra.Command{
		Use:   "add <title>",
		Short: "create a task",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			hasTrack := trackFlag != ""
			hasSeg := cmd.Flags().Changed("segment")
			if hasTrack == hasSeg {
				return errors.New("pass exactly one of -t/--track or -s/--segment")
			}
			c, err := dial()
			if err != nil {
				return err
			}
			ws, err := resolveWorkspace(c, wsFlag)
			if err != nil {
				return err
			}
			p := client.CreateTaskParams{Title: args[0], Description: descFlag, Priority: prioFlag}
			if statusFlag != "" {
				statuses, err := c.Statuses(ws.ID)
				if err != nil {
					return err
				}
				s, err := resolveStatusIn(statuses, statusFlag)
				if err != nil {
					return err
				}
				p.StatusID = &s.ID
			}
			if kindFlag != "" {
				kinds, err := c.Kinds(ws.ID)
				if err != nil {
					return err
				}
				k, err := resolveKindIn(kinds, kindFlag)
				if err != nil {
					return err
				}
				p.KindID = &k.ID
			}
			if hasTrack {
				tr, err := resolveTrack(c, ws.ID, trackFlag)
				if err != nil {
					return err
				}
				p.Track = &tr.ID
			} else {
				s := segFlag
				p.Segment = &s
			}
			task, err := c.CreateTask(p)
			if err != nil {
				return err
			}
			if flagJSON {
				return printJSON(cmd, task)
			}
			fmt.Fprintf(cmd.OutOrStdout(), "added #%d  %s\n", task.ID, task.Title)
			return nil
		},
	}
	cmd.Flags().StringVarP(&wsFlag, "workspace", "w", "", "workspace name or id (required)")
	cmd.Flags().StringVarP(&trackFlag, "track", "t", "", "track name or id")
	cmd.Flags().Int64VarP(&segFlag, "segment", "s", 0, "segment id")
	cmd.Flags().IntVarP(&prioFlag, "priority", "p", 0, "priority")
	cmd.Flags().StringVar(&statusFlag, "status", "", "initial status name or id")
	cmd.Flags().StringVar(&kindFlag, "kind", "", "kind name or id")
	cmd.Flags().StringVar(&descFlag, "desc", "", "description")
	return cmd
}

func newMvCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "mv <id> <status>",
		Short: "move a task's status",
		Args:  cobra.ExactArgs(2),
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
			wsID := detail.Task.WorkspaceID
			statuses, err := c.Statuses(wsID)
			if err != nil {
				return err
			}
			target, err := resolveStatusIn(statuses, args[1])
			if err != nil {
				return err
			}
			task, err := retryConflict(
				func() (int, error) { d, e := c.TaskDetail(id); return d.Task.Version, e },
				func(v int) (api.Task, error) { return c.MoveStatus(id, target.ID, v) },
			)
			if err != nil {
				if isIllegalTransition(err) {
					return illegalTransitionErr(c, wsID, detail.Task.StatusID, statuses,
						fmt.Sprintf("illegal transition to '%s'", target.Name))
				}
				return err
			}
			if flagJSON {
				return printJSON(cmd, task)
			}
			fmt.Fprintf(cmd.OutOrStdout(), "ok #%d → %s\n", task.ID, target.Name)
			return nil
		},
	}
}

func newDoneCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "done <id>",
		Short: "move a task to the terminal status",
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
			wsID := detail.Task.WorkspaceID
			statuses, err := c.Statuses(wsID)
			if err != nil {
				return err
			}
			var terminal *api.Status
			for i := range statuses {
				if statuses[i].Terminal {
					terminal = &statuses[i]
					break
				}
			}
			if terminal == nil {
				return errors.New("no terminal status defined in this workspace")
			}
			task, err := retryConflict(
				func() (int, error) { d, e := c.TaskDetail(id); return d.Task.Version, e },
				func(v int) (api.Task, error) { return c.MoveStatus(id, terminal.ID, v) },
			)
			if err != nil {
				if isIllegalTransition(err) {
					return illegalTransitionErr(c, wsID, detail.Task.StatusID, statuses,
						fmt.Sprintf("can't reach terminal '%s' directly", terminal.Name))
				}
				return err
			}
			if flagJSON {
				return printJSON(cmd, task)
			}
			fmt.Fprintf(cmd.OutOrStdout(), "done #%d → %s\n", task.ID, terminal.Name)
			return nil
		},
	}
}

func isIllegalTransition(err error) bool {
	var ae *client.APIError
	return errors.As(err, &ae) && ae.Variant == "IllegalTransition"
}

// illegalTransitionErr builds the CLI's "…. legal from '<cur>': <targets>" message (mirrors mv/done).
func illegalTransitionErr(c *client.Client, wsID, curStatusID int64, statuses []api.Status, prefix string) error {
	sn := map[int64]string{}
	for _, s := range statuses {
		sn[s.ID] = s.Name
	}
	trs, err := c.Transitions(wsID)
	if err != nil {
		return err
	}
	var legal []string
	for _, tr := range trs {
		if tr.FromStatusID == curStatusID {
			legal = append(legal, sn[tr.ToStatusID])
		}
	}
	cur := sn[curStatusID]
	if cur == "" {
		cur = strconv.FormatInt(curStatusID, 10)
	}
	legalStr := "(none)"
	if len(legal) > 0 {
		legalStr = strings.Join(legal, ", ")
	}
	return fmt.Errorf("%s. legal from '%s': %s", prefix, cur, legalStr)
}

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
