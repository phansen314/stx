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
	var useEditor bool
	cmd := &cobra.Command{
		Use:   "add <title>",
		Short: "create a task (`-e` writes the description in $EDITOR)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			hasTrack := trackFlag != ""
			hasSeg := cmd.Flags().Changed("segment")
			if hasTrack == hasSeg {
				return errors.New("pass exactly one of -t/--track or -s/--segment")
			}
			// Unlike `edit`, the editor is never implied here — `stx add "quick note"` must stay a
			// one-liner, so -e is the only way in.
			if useEditor && cmd.Flags().Changed("desc") {
				return errors.New("--desc and -e/--editor are mutually exclusive")
			}
			c, err := dial()
			if err != nil {
				return err
			}
			ws, err := resolveWorkspace(c, wsFlag)
			if err != nil {
				return err
			}
			desc, err := readValue(cmd, descFlag, "--desc")
			if err != nil {
				return err
			}
			var buf editedBuffer
			if useEditor {
				if buf, err = editBuffer(cmd, "add", ".md", ""); err != nil {
					return err
				}
				desc = buf.text
			}
			p := client.CreateTaskParams{Title: args[0], Description: desc, Priority: prioFlag}
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
				return fmt.Errorf("%w%s", err, buf.keep()) // don't drop a description just written
			}
			buf.discard()
			return emit(cmd, []int64{task.ID}, task,
				fmt.Sprintf("added #%d  %s", task.ID, task.Title))
		},
	}
	cmd.Flags().StringVarP(&wsFlag, "workspace", "w", "", "workspace name or id (required)")
	cmd.Flags().StringVarP(&trackFlag, "track", "t", "", "track name or id")
	cmd.Flags().Int64VarP(&segFlag, "segment", "s", 0, "segment id")
	cmd.Flags().IntVarP(&prioFlag, "priority", "p", 0, "priority")
	cmd.Flags().StringVar(&statusFlag, "status", "", "initial status name or id")
	cmd.Flags().StringVar(&kindFlag, "kind", "", "kind name or id")
	cmd.Flags().StringVar(&descFlag, "desc", "", "description (`-` reads it from stdin)")
	cmd.Flags().BoolVarP(&useEditor, "editor", "e", false, "write the description in $EDITOR")
	return cmd
}

func newMvCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "mv <id|-> <status>",
		Short: "move a task's status (`-` reads ids from stdin)",
		Args:  cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			ids, err := readIDs(cmd, args[0])
			if err != nil {
				return err
			}
			c, err := dial()
			if err != nil {
				return err
			}
			var moved []int64
			var res []any
			var lines []string
			runErr := runIDs(cmd, ids, func(id int64) error {
				detail, err := c.TaskDetail(id)
				if err != nil {
					return err
				}
				wsID := detail.Task.WorkspaceID
				statuses, err := c.Statuses(wsID)
				if err != nil {
					return err
				}
				// resolved per task: ids on stdin may span workspaces, so the status name is what
				// carries across, not its id.
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
				moved = append(moved, task.ID)
				res = append(res, task)
				lines = append(lines, fmt.Sprintf("ok #%d → %s", task.ID, target.Name))
				return nil
			})
			return emitBatch(cmd, moved, res, lines, runErr)
		},
	}
}

func newDoneCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "done <id|->",
		Short: "move a task to the terminal status (`-` reads ids from stdin)",
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
			var finished []int64
			var res []any
			var lines []string
			runErr := runIDs(cmd, ids, func(id int64) error {
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
				finished = append(finished, task.ID)
				res = append(res, task)
				lines = append(lines, fmt.Sprintf("done #%d → %s", task.ID, terminal.Name))
				return nil
			})
			return emitBatch(cmd, finished, res, lines, runErr)
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
	var useEditor bool
	cmd := &cobra.Command{
		Use:   "edit <id|->",
		Short: "edit a task (no field flags opens $EDITOR; `-` reads ids from stdin)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ids, err := readIDs(cmd, args[0])
			if err != nil {
				return err
			}
			// only send fields the user actually passed (mirrors Python's `is not None`)
			changes := map[string]any{}
			if cmd.Flags().Changed("title") {
				changes["title"] = title
			}
			if cmd.Flags().Changed("desc") {
				d, err := readValue(cmd, desc, "--desc")
				if err != nil {
					return err
				}
				changes["description"] = d
			}
			if cmd.Flags().Changed("priority") {
				changes["priority"] = priority
			}
			c, err := dial()
			if err != nil {
				return err
			}
			// No field flags: hand the description to the user's editor when there's a terminal to
			// ask on (or when -e demands it); otherwise keep the old error so scripts never hang.
			var buf editedBuffer
			if len(changes) == 0 {
				if !useEditor && !interactive() {
					return errors.New("nothing to edit — pass --title/--desc/--priority, or -e for $EDITOR")
				}
				if len(ids) != 1 || stdinClaimed != "" {
					return errors.New("editor mode edits one task — pass a single id, not `-`")
				}
				detail, err := c.TaskDetail(ids[0])
				if err != nil {
					return err
				}
				buf, err = editBuffer(cmd, fmt.Sprintf("edit-%d", ids[0]), ".md", detail.Task.Description)
				if err != nil {
					return err
				}
				if !buf.changed {
					return emit(cmd, ids, detail.Task, fmt.Sprintf("unchanged #%d", ids[0]))
				}
				changes["description"] = buf.text
			}
			var edited []int64
			var res []any
			var lines []string
			runErr := runIDs(cmd, ids, func(id int64) error {
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
				edited = append(edited, task.ID)
				res = append(res, task)
				lines = append(lines, fmt.Sprintf("edited #%d  %s", task.ID, task.Title))
				return nil
			})
			if runErr != nil {
				return fmt.Errorf("%w%s", runErr, buf.keep()) // the daemon refused — don't drop the text
			}
			buf.discard()
			return emitBatch(cmd, edited, res, lines, nil)
		},
	}
	cmd.Flags().StringVar(&title, "title", "", "new title")
	cmd.Flags().StringVar(&desc, "desc", "", "new description (`-` reads it from stdin)")
	cmd.Flags().IntVar(&priority, "priority", 0, "new priority")
	cmd.Flags().BoolVarP(&useEditor, "editor", "e", false,
		"edit the description in $EDITOR (implied when no field flag is given on a terminal)")
	return cmd
}
