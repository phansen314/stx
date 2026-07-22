package cli

import (
	"bufio"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"

	"github.com/phansen314/stx/internal/api"
	"github.com/phansen314/stx/internal/client"
	"github.com/spf13/cobra"
)

// pick is the interactive fzf command builder (issue #54). Unlike the two prior attempts (removed
// in 5196fed), fzf is driven from *here* via os/exec — not from a fragile bash wrapper. The user
// chooses a command, then live daemon data (workspaces, tasks, legal statuses, kinds) fills each
// argument, and the assembled `stx …` is confirmed and re-run in-process.

// errPickCancelled is returned by every picker when the user hits Esc/Ctrl-C or selects nothing.
// runPick treats it as a clean abort (no error surfaced).
var errPickCancelled = errors.New("pick cancelled")

// pickCommands is the v1 "daily loop" catalog. Each entry has a builder in `builders`.
var pickCommands = []struct{ name, help string }{
	{"add", "create a task"},
	{"mv", "move a task's status"},
	{"done", "move a task to the terminal status"},
	{"edit", "edit a task"},
	{"show", "task detail + edges"},
	{"next", "ready frontier"},
	{"tree", "workspace tree"},
}

var builders = map[string]func(*client.Client) ([]string, error){
	"add":  buildAdd,
	"mv":   buildMv,
	"done": buildDone,
	"edit": buildEdit,
	"show": buildShow,
	"next": buildNext,
	"tree": buildTree,
}

func newPickCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "pick",
		Short: "interactive fzf command builder (surfaces live IDs, no memorizing)",
		Args:  cobra.NoArgs,
		RunE:  func(cmd *cobra.Command, _ []string) error { return runPick(cmd) },
	}
}

func runPick(cmd *cobra.Command) error {
	if _, err := exec.LookPath("fzf"); err != nil {
		fmt.Fprintln(cmd.OutOrStdout(),
			"stx pick needs fzf on PATH — install it: https://github.com/junegunn/fzf")
		return nil
	}

	name, err := pickCommand()
	if err != nil {
		return swallowCancel(err)
	}
	c, err := dial()
	if err != nil {
		return err
	}
	build, ok := builders[name]
	if !ok {
		return fmt.Errorf("pick: no builder for %q", name)
	}
	argv, err := build(c)
	if err != nil {
		return swallowCancel(err)
	}

	if !confirm("stx " + strings.Join(argv, " ")) {
		return nil
	}
	root := NewRootCmd()
	root.SetArgs(argv)
	return root.Execute()
}

// swallowCancel maps a user abort to a clean nil; anything else propagates.
func swallowCancel(err error) error {
	if errors.Is(err, errPickCancelled) {
		return nil
	}
	return err
}

// ── command picker ───────────────────────────────────────────────────────────

func pickCommand() (string, error) {
	lines := make([]string, len(pickCommands))
	for i, pc := range pickCommands {
		lines[i] = fmt.Sprintf("%s\t%-5s  %s", pc.name, pc.name, pc.help)
	}
	return fzfOne(lines, fzfOpts{
		prompt:  "stx> ",
		header:  "building:  stx …",
		preview: self() + " {1} -h",
	})
}

// ── builders (I/O: run pickers, then delegate to a pure argv assembler) ───────

func buildAdd(c *client.Client) ([]string, error) {
	ws, err := pickWorkspace(c, "building:  stx add …")
	if err != nil {
		return nil, err
	}
	tr, err := pickTrack(c, ws.ID, "building:  stx add -w "+ws.Name+" …")
	if err != nil {
		return nil, err
	}
	title, err := promptLine("title> ")
	if err != nil {
		return nil, err
	}
	if title == "" {
		return nil, errPickCancelled
	}
	// optional extras: status, kind, priority — multi-select then collect each.
	extras, err := collectFields(c, ws.ID, []fieldSpec{
		{flag: "--status", kind: "status"},
		{flag: "--kind", kind: "kind"},
		{flag: "--priority", kind: "int"},
	}, fmt.Sprintf("building:  stx add %q -w %s -t %s …", title, ws.Name, tr.Name), false)
	if err != nil {
		return nil, err
	}
	return argvAdd(title, ws.Name, tr.Name, extras), nil
}

func buildMv(c *client.Client) ([]string, error) {
	ws, err := pickWorkspace(c, "building:  stx mv …")
	if err != nil {
		return nil, err
	}
	task, err := pickTask(c, ws.ID, "building:  stx mv …   (workspace: "+ws.Name+")")
	if err != nil {
		return nil, err
	}
	// only legal transitions from the task's current status (mirrors illegalTransitionErr).
	statuses, err := c.Statuses(ws.ID)
	if err != nil {
		return nil, err
	}
	trs, err := c.Transitions(ws.ID)
	if err != nil {
		return nil, err
	}
	sn := map[int64]string{}
	for _, s := range statuses {
		sn[s.ID] = s.Name
	}
	var lines []string
	for _, tr := range trs {
		if tr.FromStatusID == task.StatusID {
			n := sn[tr.ToStatusID]
			lines = append(lines, n+"\t"+n)
		}
	}
	if len(lines) == 0 {
		return nil, fmt.Errorf("no legal transitions from the task's current status")
	}
	st, err := fzfOne(lines, fzfOpts{
		prompt: "status> ",
		header: fmt.Sprintf("building:  stx mv %d …", task.ID),
	})
	if err != nil {
		return nil, err
	}
	return argvMv(strconv.FormatInt(task.ID, 10), st), nil
}

func buildDone(c *client.Client) ([]string, error) {
	ws, err := pickWorkspace(c, "building:  stx done …")
	if err != nil {
		return nil, err
	}
	task, err := pickTask(c, ws.ID, "building:  stx done …   (workspace: "+ws.Name+")")
	if err != nil {
		return nil, err
	}
	return argvDone(strconv.FormatInt(task.ID, 10)), nil
}

func buildShow(c *client.Client) ([]string, error) {
	ws, err := pickWorkspace(c, "building:  stx show …")
	if err != nil {
		return nil, err
	}
	task, err := pickTask(c, ws.ID, "building:  stx show …   (workspace: "+ws.Name+")")
	if err != nil {
		return nil, err
	}
	return argvShow(strconv.FormatInt(task.ID, 10)), nil
}

func buildEdit(c *client.Client) ([]string, error) {
	ws, err := pickWorkspace(c, "building:  stx edit …")
	if err != nil {
		return nil, err
	}
	task, err := pickTask(c, ws.ID, "building:  stx edit …   (workspace: "+ws.Name+")")
	if err != nil {
		return nil, err
	}
	id := strconv.FormatInt(task.ID, 10)
	fields, err := collectFields(c, ws.ID, []fieldSpec{
		{flag: "--title", kind: "text"},
		{flag: "--desc", kind: "text"},
		{flag: "--priority", kind: "int"},
	}, "building:  stx edit "+id+" …", true)
	if err != nil {
		return nil, err
	}
	if len(fields) == 0 {
		return nil, errPickCancelled
	}
	return argvEdit(id, fields), nil
}

func buildNext(c *client.Client) ([]string, error) {
	ws, err := pickWorkspace(c, "building:  stx next …")
	if err != nil {
		return nil, err
	}
	return argvNext(ws.Name), nil
}

func buildTree(c *client.Client) ([]string, error) {
	ws, err := pickWorkspace(c, "building:  stx tree …")
	if err != nil {
		return nil, err
	}
	return argvTree(ws.Name), nil
}

// ── pure argv assemblers (no I/O — unit-tested directly) ──────────────────────

// kv is a resolved flag/value pair collected from an optional-field pass.
type kv struct{ flag, value string }

func argvAdd(title, ws, track string, extras []kv) []string {
	argv := []string{"add", title, "-w", ws, "-t", track}
	for _, e := range extras {
		argv = append(argv, e.flag, e.value)
	}
	return argv
}

func argvMv(id, status string) []string { return []string{"mv", id, status} }
func argvDone(id string) []string       { return []string{"done", id} }
func argvShow(id string) []string       { return []string{"show", id} }
func argvNext(ws string) []string       { return []string{"next", "-w", ws} }
func argvTree(ws string) []string       { return []string{"tree", "-w", ws} }

func argvEdit(id string, fields []kv) []string {
	argv := []string{"edit", id}
	for _, f := range fields {
		argv = append(argv, f.flag, f.value)
	}
	return argv
}

// ── shared pickers ────────────────────────────────────────────────────────────

func pickWorkspace(c *client.Client, header string) (api.Workspace, error) {
	wss, err := c.ListWorkspaces()
	if err != nil {
		return api.Workspace{}, err
	}
	if len(wss) == 0 {
		return api.Workspace{}, fmt.Errorf("no workspaces — create one with `stx ws add`")
	}
	byName := map[string]api.Workspace{}
	lines := make([]string, 0, len(wss))
	for _, w := range wss {
		byName[w.Name] = w
		lines = append(lines, fmt.Sprintf("%s\t%s", w.Name, w.Name))
	}
	name, err := fzfOne(lines, fzfOpts{prompt: "workspace> ", header: header})
	if err != nil {
		return api.Workspace{}, err
	}
	return byName[name], nil
}

func pickTrack(c *client.Client, wsID int64, header string) (api.Track, error) {
	tracks, err := c.Tracks(wsID)
	if err != nil {
		return api.Track{}, err
	}
	if len(tracks) == 0 {
		return api.Track{}, fmt.Errorf("no tracks in this workspace")
	}
	byName := map[string]api.Track{}
	lines := make([]string, 0, len(tracks))
	for _, t := range tracks {
		byName[t.Name] = t
		lines = append(lines, fmt.Sprintf("%s\t%s", t.Name, t.Name))
	}
	name, err := fzfOne(lines, fzfOpts{prompt: "track> ", header: header})
	if err != nil {
		return api.Track{}, err
	}
	return byName[name], nil
}

// pickTask gathers every task in the workspace (iterating tracks — there is no ws-wide task read)
// and shows `#id  [status]  title`, id in the hidden value column, `stx show {id}` in the preview.
func pickTask(c *client.Client, wsID int64, header string) (api.Task, error) {
	tracks, err := c.Tracks(wsID)
	if err != nil {
		return api.Task{}, err
	}
	sn, err := statusNames(c, wsID)
	if err != nil {
		return api.Task{}, err
	}
	byID := map[string]api.Task{}
	var lines []string
	for _, tr := range tracks {
		tasks, err := c.TrackTasks(tr.ID)
		if err != nil {
			return api.Task{}, err
		}
		for _, t := range tasks {
			id := strconv.FormatInt(t.ID, 10)
			byID[id] = t
			lines = append(lines, fmt.Sprintf("%s\t#%s  [%s]  %s", id, id, sn[t.StatusID], t.Title))
		}
	}
	if len(lines) == 0 {
		return api.Task{}, fmt.Errorf("no tasks in this workspace")
	}
	id, err := fzfOne(lines, fzfOpts{
		prompt:  "task> ",
		header:  header,
		preview: self() + " show {1}",
	})
	if err != nil {
		return api.Task{}, err
	}
	return byID[id], nil
}

// ── optional-field collection (shared by add/edit) ────────────────────────────

type fieldSpec struct {
	flag string // e.g. "--title", "--status"
	kind string // "text" | "int" | "status" | "kind"
}

// collectFields multi-selects which fields to set, then collects each value (fzf for enum kinds,
// readline for free text). required=true means at least one field is expected (edit); when false
// (add extras), selecting none returns an empty slice rather than cancelling.
func collectFields(c *client.Client, wsID int64, specs []fieldSpec, header string, required bool) ([]kv, error) {
	lines := make([]string, len(specs))
	for i, s := range specs {
		name := strings.TrimPrefix(s.flag, "--")
		lines[i] = fmt.Sprintf("%s\t%s", name, name)
	}
	chosen, err := fzfMany(lines, fzfOpts{prompt: "field(s)> ", header: header})
	if err != nil {
		if !required && errors.Is(err, errPickCancelled) {
			return nil, nil
		}
		return nil, err
	}
	spec := map[string]fieldSpec{}
	for _, s := range specs {
		spec[strings.TrimPrefix(s.flag, "--")] = s
	}
	var out []kv
	for _, name := range chosen {
		s := spec[name]
		val, err := collectValue(c, wsID, s, header)
		if err != nil {
			return nil, err
		}
		out = append(out, kv{flag: s.flag, value: val})
	}
	return out, nil
}

func collectValue(c *client.Client, wsID int64, s fieldSpec, header string) (string, error) {
	switch s.kind {
	case "status":
		return pickStatusName(c, wsID, header)
	case "kind":
		return pickKindName(c, wsID, header)
	case "int":
		v, err := promptLine(strings.TrimPrefix(s.flag, "--") + "> ")
		if err != nil {
			return "", err
		}
		if _, e := strconv.Atoi(v); e != nil {
			return "", fmt.Errorf("%s must be an integer, got %q", s.flag, v)
		}
		return v, nil
	default: // text
		return promptLine(strings.TrimPrefix(s.flag, "--") + "> ")
	}
}

func pickStatusName(c *client.Client, wsID int64, header string) (string, error) {
	statuses, err := c.Statuses(wsID)
	if err != nil {
		return "", err
	}
	lines := make([]string, 0, len(statuses))
	for _, s := range statuses {
		lines = append(lines, s.Name+"\t"+s.Name)
	}
	return fzfOne(lines, fzfOpts{prompt: "status> ", header: header})
}

func pickKindName(c *client.Client, wsID int64, header string) (string, error) {
	kinds, err := c.Kinds(wsID)
	if err != nil {
		return "", err
	}
	if len(kinds) == 0 {
		return "", fmt.Errorf("no kinds in this workspace")
	}
	lines := make([]string, 0, len(kinds))
	for _, k := range kinds {
		lines = append(lines, k.Name+"\t"+k.Name)
	}
	return fzfOne(lines, fzfOpts{prompt: "kind> ", header: header})
}

// ── fzf / stdin plumbing (behind vars so tests stub them) ─────────────────────

type fzfOpts struct {
	prompt  string
	header  string
	preview string
	multi   bool
}

// fzfRun feeds "value\tlabel" lines to fzf and returns the chosen values (first TAB-field of each
// selected line). The label column (2..) is what the user sees. Any non-zero fzf exit (Esc, no
// match) becomes errPickCancelled. Overridable in tests.
var fzfRun = func(lines []string, o fzfOpts) ([]string, error) {
	args := []string{"--reverse", "--border=rounded", "--delimiter=\t", "--with-nth=2.."}
	if o.prompt != "" {
		args = append(args, "--prompt="+o.prompt)
	}
	// The command-so-far goes on the *outer* border, not --header: a header lives in the list
	// pane, which shrinks to ~45% when a right-side preview is on and truncates there. The border
	// label spans the full window width regardless of the preview split.
	if o.header != "" {
		args = append(args,
			"--border-label= "+o.header+" ",
			"--border-label-pos=3",
			"--color=label:bold")
	}
	if o.preview != "" {
		args = append(args, "--preview="+o.preview, "--preview-window=right:55%:wrap")
	}
	if o.multi {
		args = append(args, "--multi")
	}
	cmd := exec.Command("fzf", args...)
	cmd.Stdin = strings.NewReader(strings.Join(lines, "\n"))
	cmd.Stderr = os.Stderr
	out, err := cmd.Output()
	if err != nil {
		return nil, errPickCancelled // Esc/Ctrl-C (130) or no match (1)
	}
	var vals []string
	for _, l := range strings.Split(strings.TrimRight(string(out), "\n"), "\n") {
		if l == "" {
			continue
		}
		vals = append(vals, strings.SplitN(l, "\t", 2)[0])
	}
	if len(vals) == 0 {
		return nil, errPickCancelled
	}
	return vals, nil
}

func fzfOne(lines []string, o fzfOpts) (string, error) {
	o.multi = false
	vals, err := fzfRun(lines, o)
	if err != nil {
		return "", err
	}
	return vals[0], nil
}

func fzfMany(lines []string, o fzfOpts) ([]string, error) {
	o.multi = true
	return fzfRun(lines, o)
}

var stdin = bufio.NewReader(os.Stdin)

// promptLine reads one trimmed line of free text from stdin. Overridable in tests.
var promptLine = func(label string) (string, error) {
	fmt.Fprint(os.Stderr, label)
	s, err := stdin.ReadString('\n')
	if err != nil && s == "" {
		return "", errPickCancelled
	}
	return strings.TrimSpace(s), nil
}

// confirm prints the assembled command and asks to run it (default yes). Overridable in tests.
var confirm = func(cmdLine string) bool {
	fmt.Fprintf(os.Stderr, "\n  %s\n\nrun? [Y/n] ", cmdLine)
	s, _ := stdin.ReadString('\n')
	switch strings.TrimSpace(strings.ToLower(s)) {
	case "", "y", "yes":
		return true
	default:
		return false
	}
}

// self is the absolute path to the running binary, used in fzf --preview shell commands so the
// preview works regardless of the installed name / CWD.
func self() string {
	if p, err := os.Executable(); err == nil {
		return p
	}
	return os.Args[0]
}
