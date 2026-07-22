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

// pickCommands is the builder catalog shown in the top-level fzf menu, grouped daily-loop →
// edges → graph/meta/archive → admin. Each entry has a builder in `builders`.
var pickCommands = []struct{ name, help string }{
	{"add", "create a task"},
	{"mv", "move a task's status"},
	{"done", "move a task to the terminal status"},
	{"edit", "edit a task"},
	{"show", "task detail + edges"},
	{"next", "ready frontier"},
	{"tree", "workspace tree"},
	{"block", "mark a task blocked by another"},
	{"unblock", "remove a blocks edge"},
	{"relate", "add a relation between tasks"},
	{"unrelate", "remove a relation"},
	{"relate-kinds", "list relation kinds in use"},
	{"graph", "emit the task graph as DOT"},
	{"meta", "get/set/delete metadata keys"},
	{"archive", "archive an entity"},
	{"ws", "create a workspace"},
	{"track", "create a track"},
	{"segment", "create a segment"},
	{"status", "status admin"},
	{"kind", "kind admin"},
	{"transition", "add a status transition"},
}

var builders = map[string]func(*client.Client) ([]string, error){
	"add":          buildAdd,
	"mv":           buildMv,
	"done":         buildDone,
	"edit":         buildEdit,
	"show":         buildShow,
	"next":         buildNext,
	"tree":         buildTree,
	"block":        func(c *client.Client) ([]string, error) { return buildBlockLike(c, "block") },
	"unblock":      func(c *client.Client) ([]string, error) { return buildBlockLike(c, "unblock") },
	"relate":       func(c *client.Client) ([]string, error) { return buildRelateLike(c, "relate") },
	"unrelate":     func(c *client.Client) ([]string, error) { return buildRelateLike(c, "unrelate") },
	"relate-kinds": buildRelateKinds,
	"graph":        buildGraph,
	"meta":         buildMeta,
	"archive":      buildArchive,
	"ws":           buildWsNew,
	"track":        buildTrackNew,
	"segment":      buildSegmentNew,
	"status":       buildStatus,
	"kind":         buildKind,
	"transition":   buildTransition,
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

// ── edges: block / unblock / relate / unrelate / relate-kinds ─────────────────

// buildBlockLike picks the blocked task then the blocker, both in one workspace.
func buildBlockLike(c *client.Client, name string) ([]string, error) {
	ws, err := pickWorkspace(c, "building:  stx "+name+" …")
	if err != nil {
		return nil, err
	}
	task, err := pickTask(c, ws.ID, "building:  stx "+name+" …   (workspace: "+ws.Name+")")
	if err != nil {
		return nil, err
	}
	blocker, err := pickTask(c, ws.ID, fmt.Sprintf("building:  stx %s %d --on …   (the blocker)", name, task.ID))
	if err != nil {
		return nil, err
	}
	return []string{name, itoa(task.ID), "--on", itoa(blocker.ID)}, nil
}

// buildRelateLike picks two tasks and a relation kind (from live kinds, else free text).
func buildRelateLike(c *client.Client, name string) ([]string, error) {
	ws, err := pickWorkspace(c, "building:  stx "+name+" …")
	if err != nil {
		return nil, err
	}
	task, err := pickTask(c, ws.ID, "building:  stx "+name+" …   (workspace: "+ws.Name+")")
	if err != nil {
		return nil, err
	}
	other, err := pickTask(c, ws.ID, fmt.Sprintf("building:  stx %s %d --to …   (the other task)", name, task.ID))
	if err != nil {
		return nil, err
	}
	kind, err := pickRelateKind(c, ws.ID, fmt.Sprintf("building:  stx %s %d --to %d --kind …", name, task.ID, other.ID))
	if err != nil {
		return nil, err
	}
	return []string{name, itoa(task.ID), "--to", itoa(other.ID), "--kind", kind}, nil
}

func buildRelateKinds(c *client.Client) ([]string, error) {
	ws, err := pickWorkspace(c, "building:  stx relate-kinds …")
	if err != nil {
		return nil, err
	}
	return []string{"relate-kinds", "-w", ws.Name}, nil
}

func buildGraph(c *client.Client) ([]string, error) {
	ws, err := pickWorkspace(c, "building:  stx graph …")
	if err != nil {
		return nil, err
	}
	argv := []string{"graph", "-w", ws.Name}

	// optional flags — multi-select which to add, then collect each. Cancelling the pane (Esc)
	// leaves the bare `graph -w <ws>`.
	opts, err := fzfMany([]string{
		"track\tscope to a track (-t)",
		"blocks-only\tomit relates_to edges",
		"vertical\ttop-to-bottom layout",
		"out\trender to a file (-o)",
		"format\toutput format for -o",
	}, fzfOpts{prompt: "options> ", header: "building:  stx graph -w " + ws.Name + " …"})
	if err != nil {
		if errors.Is(err, errPickCancelled) {
			return argv, nil
		}
		return nil, err
	}
	sel := map[string]bool{}
	for _, o := range opts {
		sel[o] = true
	}
	if sel["track"] {
		tr, err := pickTrack(c, ws.ID, "building:  stx graph -w "+ws.Name+" -t …")
		if err != nil {
			return nil, err
		}
		argv = append(argv, "-t", tr.Name)
	}
	if sel["blocks-only"] {
		argv = append(argv, "--blocks-only")
	}
	if sel["vertical"] {
		argv = append(argv, "--vertical")
	}
	// --format requires -o, so collect an out path whenever either is chosen.
	if sel["out"] || sel["format"] {
		out, err := promptRequired("out file (e.g. graph.svg)> ")
		if err != nil {
			return nil, err
		}
		argv = append(argv, "-o", out)
		if sel["format"] {
			f, err := pickOne("format> ", "building:  stx graph … -o "+out+" --format …", "svg", "png", "pdf")
			if err != nil {
				return nil, err
			}
			argv = append(argv, "--format", f)
		}
	}
	return argv, nil
}

// ── archive ───────────────────────────────────────────────────────────────────

func buildArchive(c *client.Client) ([]string, error) {
	typ, err := pickOne("type> ", "building:  stx archive …", "task", "segment", "track", "workspace")
	if err != nil {
		return nil, err
	}
	ws, err := pickWorkspace(c, "building:  stx archive "+typ+" …")
	if err != nil {
		return nil, err
	}
	switch typ {
	case "workspace":
		return argvArchive(typ, itoa(ws.ID)), nil
	case "task":
		task, err := pickTask(c, ws.ID, "building:  stx archive task …   (workspace: "+ws.Name+")")
		if err != nil {
			return nil, err
		}
		return argvArchive(typ, itoa(task.ID)), nil
	default: // track | segment — both start from a track
		tr, err := pickTrack(c, ws.ID, "building:  stx archive "+typ+" …")
		if err != nil {
			return nil, err
		}
		if typ == "track" {
			return argvArchive(typ, itoa(tr.ID)), nil
		}
		seg, err := pickSegment(c, tr.ID, "building:  stx archive segment …")
		if err != nil {
			return nil, err
		}
		return argvArchive(typ, itoa(seg.ID)), nil
	}
}

// ── meta ──────────────────────────────────────────────────────────────────────

func buildMeta(c *client.Client) ([]string, error) {
	sub, err := pickOne("meta> ", "building:  stx meta …", "ls", "get", "set", "del")
	if err != nil {
		return nil, err
	}
	target, err := pickMetaTarget(c, "building:  stx meta "+sub+" …")
	if err != nil {
		return nil, err
	}
	var kvArgs []string
	switch sub {
	case "get", "del":
		key, err := promptRequired("key> ")
		if err != nil {
			return nil, err
		}
		kvArgs = []string{key}
	case "set":
		key, err := promptRequired("key> ")
		if err != nil {
			return nil, err
		}
		val, err := promptRequired("value> ")
		if err != nil {
			return nil, err
		}
		kvArgs = []string{key, val}
	}
	return argvMeta(sub, kvArgs, target), nil
}

// pickMetaTarget returns the `--task <id>` / `-w <ws>` / `-w <ws> --track <t>` flags identifying
// the entity whose metadata is being edited.
func pickMetaTarget(c *client.Client, header string) ([]string, error) {
	typ, err := pickOne("target> ", header, "task", "workspace", "track")
	if err != nil {
		return nil, err
	}
	ws, err := pickWorkspace(c, header)
	if err != nil {
		return nil, err
	}
	switch typ {
	case "task":
		task, err := pickTask(c, ws.ID, header)
		if err != nil {
			return nil, err
		}
		return []string{"--task", itoa(task.ID)}, nil
	case "workspace":
		return []string{"-w", ws.Name}, nil
	default: // track
		tr, err := pickTrack(c, ws.ID, header)
		if err != nil {
			return nil, err
		}
		return []string{"-w", ws.Name, "--track", tr.Name}, nil
	}
}

// ── admin: ws / track / segment / status / kind / transition ──────────────────

func buildWsNew(c *client.Client) ([]string, error) {
	name, err := promptRequired("workspace name> ")
	if err != nil {
		return nil, err
	}
	return []string{"ws", "new", name}, nil
}

func buildTrackNew(c *client.Client) ([]string, error) {
	ws, err := pickWorkspace(c, "building:  stx track new …")
	if err != nil {
		return nil, err
	}
	name, err := promptRequired("track name> ")
	if err != nil {
		return nil, err
	}
	return []string{"track", "new", name, "-w", ws.Name}, nil
}

func buildSegmentNew(c *client.Client) ([]string, error) {
	ws, err := pickWorkspace(c, "building:  stx segment new …")
	if err != nil {
		return nil, err
	}
	tr, err := pickTrack(c, ws.ID, "building:  stx segment new -w "+ws.Name+" …")
	if err != nil {
		return nil, err
	}
	name, err := promptRequired("segment name> ")
	if err != nil {
		return nil, err
	}
	return []string{"segment", "new", name, "-w", ws.Name, "-t", tr.Name}, nil
}

func buildStatus(c *client.Client) ([]string, error) {
	sub, err := pickOne("status> ", "building:  stx status …", "new", "ls", "default", "archive")
	if err != nil {
		return nil, err
	}
	ws, err := pickWorkspace(c, "building:  stx status "+sub+" …")
	if err != nil {
		return nil, err
	}
	switch sub {
	case "ls":
		return []string{"status", "ls", "-w", ws.Name}, nil
	case "new":
		name, err := promptRequired("status name> ")
		if err != nil {
			return nil, err
		}
		order, err := promptInt("kanban order> ")
		if err != nil {
			return nil, err
		}
		return []string{"status", "new", name, "-w", ws.Name, "--order", order}, nil
	default: // default | archive — pick an existing status
		st, err := pickStatusName(c, ws.ID, "building:  stx status "+sub+" -w "+ws.Name+" …")
		if err != nil {
			return nil, err
		}
		return []string{"status", sub, st, "-w", ws.Name}, nil
	}
}

func buildKind(c *client.Client) ([]string, error) {
	sub, err := pickOne("kind> ", "building:  stx kind …", "new", "archive")
	if err != nil {
		return nil, err
	}
	ws, err := pickWorkspace(c, "building:  stx kind "+sub+" …")
	if err != nil {
		return nil, err
	}
	if sub == "new" {
		name, err := promptRequired("kind name> ")
		if err != nil {
			return nil, err
		}
		return []string{"kind", "new", name, "-w", ws.Name}, nil
	}
	k, err := pickKindName(c, ws.ID, "building:  stx kind archive -w "+ws.Name+" …")
	if err != nil {
		return nil, err
	}
	return []string{"kind", "archive", k, "-w", ws.Name}, nil
}

func buildTransition(c *client.Client) ([]string, error) {
	ws, err := pickWorkspace(c, "building:  stx transition …")
	if err != nil {
		return nil, err
	}
	from, err := pickStatusName(c, ws.ID, "building:  stx transition -w "+ws.Name+" --from …")
	if err != nil {
		return nil, err
	}
	to, err := pickStatusName(c, ws.ID, "building:  stx transition -w "+ws.Name+" --from "+from+" --to …")
	if err != nil {
		return nil, err
	}
	return []string{"transition", "-w", ws.Name, "--from", from, "--to", to}, nil
}

// ── pure argv assemblers (no I/O — unit-tested directly) ──────────────────────

// kv is a resolved flag/value pair collected from an optional-field pass.
type kv struct{ flag, value string }

// argvArchive appends --yes for the cascading types (track/workspace), matching archive.go's gate.
func argvArchive(typ, id string) []string {
	argv := []string{"archive", typ, id}
	if typ == "track" || typ == "workspace" {
		argv = append(argv, "--yes")
	}
	return argv
}

// argvMeta assembles `meta <sub> [key [value]] <target-flags…>`.
func argvMeta(sub string, kvArgs, target []string) []string {
	argv := append([]string{"meta", sub}, kvArgs...)
	return append(argv, target...)
}

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

func pickSegment(c *client.Client, trackID int64, header string) (api.Segment, error) {
	segs, err := c.Segments(trackID)
	if err != nil {
		return api.Segment{}, err
	}
	if len(segs) == 0 {
		return api.Segment{}, fmt.Errorf("no segments in this track")
	}
	byID := map[string]api.Segment{}
	lines := make([]string, 0, len(segs))
	for _, s := range segs {
		id := itoa(s.ID)
		byID[id] = s
		tag := ""
		if s.IsRoot {
			tag = " (root)"
		}
		lines = append(lines, fmt.Sprintf("%s\t#%s  %s%s", id, id, s.Name, tag))
	}
	id, err := fzfOne(lines, fzfOpts{prompt: "segment> ", header: header})
	if err != nil {
		return api.Segment{}, err
	}
	return byID[id], nil
}

// pickRelateKind offers the relation kinds already in use (free-text edges), falling back to a
// readline prompt when none exist yet — relate --kind is arbitrary text.
func pickRelateKind(c *client.Client, wsID int64, header string) (string, error) {
	kinds, err := c.RelatesKinds(wsID)
	if err != nil {
		return "", err
	}
	if len(kinds) == 0 {
		return promptRequired("kind> ")
	}
	lines := make([]string, 0, len(kinds))
	for _, k := range kinds {
		lines = append(lines, k+"\t"+k)
	}
	return fzfOne(lines, fzfOpts{prompt: "kind> ", header: header})
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

func itoa(id int64) string { return strconv.FormatInt(id, 10) }

// pickOne presents a fixed set of literal choices (value == label) in an fzf pane.
func pickOne(prompt, header string, opts ...string) (string, error) {
	lines := make([]string, len(opts))
	for i, o := range opts {
		lines[i] = o + "\t" + o
	}
	return fzfOne(lines, fzfOpts{prompt: prompt, header: header})
}

// promptRequired reads a non-empty line; empty input aborts the build (like an Esc).
func promptRequired(label string) (string, error) {
	v, err := promptLine(label)
	if err != nil {
		return "", err
	}
	if v == "" {
		return "", errPickCancelled
	}
	return v, nil
}

// promptInt reads a required integer (for flags like status --order).
func promptInt(label string) (string, error) {
	v, err := promptRequired(label)
	if err != nil {
		return "", err
	}
	if _, e := strconv.Atoi(v); e != nil {
		return "", fmt.Errorf("expected an integer, got %q", v)
	}
	return v, nil
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

// interactive reports whether both stdin and stdout are terminals — the guided builder only makes
// sense then (fzf and the readline prompts need a real TTY). Bare `stx` in a pipe/script skips it.
func interactive() bool {
	return isCharDevice(os.Stdin) && isCharDevice(os.Stdout)
}

func isCharDevice(f *os.File) bool {
	fi, err := f.Stat()
	return err == nil && fi.Mode()&os.ModeCharDevice != 0
}

// self is the absolute path to the running binary, used in fzf --preview shell commands so the
// preview works regardless of the installed name / CWD.
func self() string {
	if p, err := os.Executable(); err == nil {
		return p
	}
	return os.Args[0]
}
