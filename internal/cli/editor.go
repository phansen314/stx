package cli

import (
	"fmt"
	"os"
	"os/exec"
	"strings"

	"github.com/spf13/cobra"
)

// GUI editors fork and return immediately unless told to wait — without a wait flag stx would read
// the temp file back before a single keystroke and report "unchanged". This table is the set of
// editors stx knows how to flag: `wait` blocks until the buffer closes, `newWindow` opens a fresh
// window. Anything not listed is assumed to be a terminal editor (vi, nano, emacs -nw, hx …),
// which blocks by nature and needs a tty.
var guiEditors = map[string]struct {
	wait      string   // the flag to add when none of waitFlags is present
	newWindow string   // the flag to add when the user typed no flags at all
	waitFlags []string // spellings that already mean "wait"
}{
	"zed":           {wait: "-w", newWindow: "-n", waitFlags: []string{"-w", "--wait"}},
	"code":          {wait: "-w", newWindow: "-n", waitFlags: []string{"-w", "--wait"}},
	"code-insiders": {wait: "-w", newWindow: "-n", waitFlags: []string{"-w", "--wait"}},
	"codium":        {wait: "-w", newWindow: "-n", waitFlags: []string{"-w", "--wait"}},
	"cursor":        {wait: "-w", newWindow: "-n", waitFlags: []string{"-w", "--wait"}},
	"subl":          {wait: "-w", newWindow: "-n", waitFlags: []string{"-w", "--wait"}},
}

// editorsOnPath is the probe order when nothing is set in the environment: the windowed editors
// first (they work without a tty), then a terminal fallback.
var editorsOnPath = []string{"zed", "code", "vi"}

// shellMeta are characters that make whitespace-splitting the wrong way to read an editor value
// ("EDITOR=code --wait" splits fine; `EDITOR='f() { … }; f'` does not). Their presence switches to
// git's approach — hand the whole thing to sh.
const shellMeta = "\"'$`|&;<>(){}[]*?~\\\n"

// editorCommand resolves the argv that opens path in the user's editor, and reports whether that
// editor is a windowed one (which needs no tty). Resolution order: $STX_EDITOR, $VISUAL, $EDITOR,
// then the first of editorsOnPath that exists.
//
// Flags the user typed are never rewritten. A known GUI editor named with no flags at all gets
// `-n -w` (new window, wait); one that was given flags only gets its wait flag added if missing.
func editorCommand(path string) (argv []string, gui bool, err error) {
	value := ""
	for _, env := range []string{"STX_EDITOR", "VISUAL", "EDITOR"} {
		if v := strings.TrimSpace(os.Getenv(env)); v != "" {
			value = v
			break
		}
	}
	if value == "" {
		for _, name := range editorsOnPath {
			if _, e := exec.LookPath(name); e == nil {
				value = name
				break
			}
		}
	}
	if value == "" {
		return nil, false, fmt.Errorf(
			"no editor found — set $EDITOR (e.g. export EDITOR='zed -n -w') or pass --desc")
	}
	// Too shell-ish to tokenize: run it the way git does and leave the flagging to the user.
	if strings.ContainsAny(value, shellMeta) {
		return []string{"sh", "-c", value + ` "$1"`, "sh", path}, false, nil
	}

	fields := strings.Fields(value)
	prog := fields[0]
	if i := strings.LastIndex(prog, "/"); i >= 0 {
		prog = prog[i+1:] // /usr/bin/code → code
	}
	spec, isGUI := guiEditors[prog]
	if !isGUI {
		return append(fields, path), false, nil
	}
	flags := fields[1:]
	if len(flags) == 0 {
		fields = append(fields, spec.newWindow, spec.wait)
	} else if !containsAny(flags, spec.waitFlags) {
		fields = append(fields, spec.wait)
	}
	return append(fields, path), true, nil
}

func containsAny(haystack, needles []string) bool {
	for _, h := range haystack {
		for _, n := range needles {
			if h == n {
				return true
			}
		}
	}
	return false
}

// runEditor opens path in the user's editor and blocks until it exits. A var so tests can stub the
// launch without spawning anything.
var runEditor = func(cmd *cobra.Command, path string) error {
	argv, gui, err := editorCommand(path)
	if err != nil {
		return err
	}
	// A terminal editor with nowhere to draw would hang or scribble into a pipe; a windowed one
	// doesn't care what stdio looks like.
	if !gui && !interactive() {
		return fmt.Errorf("editor %q needs a terminal — set $STX_EDITOR to a windowed editor "+
			"(e.g. 'zed -n -w') or pass --desc", argv[0])
	}
	ed := exec.Command(argv[0], argv[1:]...)
	ed.Stdin, ed.Stdout, ed.Stderr = os.Stdin, cmd.ErrOrStderr(), cmd.ErrOrStderr()
	if err := ed.Run(); err != nil {
		return fmt.Errorf("editor %s: %w", strings.Join(argv, " "), err)
	}
	return nil
}

// editedBuffer is what came back from the editor: the saved text, whether it differs from what stx
// wrote, and — when it differs — the path of the temp file, still on disk. The caller removes it
// once the daemon has the text (see keep/discard below), so a failed write never loses a long
// description.
type editedBuffer struct {
	text    string
	changed bool
	path    string // "" once the file has been removed
}

// discard removes the retained buffer; keep leaves it and returns a hint naming it.
func (b *editedBuffer) discard() {
	if b.path != "" {
		os.Remove(b.path)
		b.path = ""
	}
}

func (b *editedBuffer) keep() string {
	if b.path == "" {
		return ""
	}
	return " — your text is still in " + b.path
}

// editDescription round-trips current through the user's editor. The whole buffer IS the
// description: nothing is parsed or stripped, so markdown headings survive byte-for-byte, minus the
// single trailing newline editors add on save.
func editDescription(cmd *cobra.Command, id int64, current string) (editedBuffer, error) {
	f, err := os.CreateTemp("", fmt.Sprintf("stx-edit-%d-*.md", id))
	if err != nil {
		return editedBuffer{}, fmt.Errorf("creating the editor buffer: %w", err)
	}
	path := f.Name()
	seed := current
	if seed != "" && !strings.HasSuffix(seed, "\n") {
		seed += "\n"
	}
	_, werr := f.WriteString(seed)
	cerr := f.Close()
	if werr != nil || cerr != nil {
		os.Remove(path)
		return editedBuffer{}, fmt.Errorf("writing the editor buffer: %w", firstErr(werr, cerr))
	}

	if err := runEditor(cmd, path); err != nil {
		// A crash after the user saved must not eat their text; a failure with nothing typed
		// leaves only what stx seeded, so that one is safe to clean up.
		if raw, rerr := os.ReadFile(path); rerr == nil && string(raw) != seed {
			return editedBuffer{path: path}, fmt.Errorf("%w — your text is still in %s", err, path)
		}
		os.Remove(path)
		return editedBuffer{}, err
	}

	raw, err := os.ReadFile(path)
	if err != nil {
		return editedBuffer{}, fmt.Errorf("reading %s back: %w", path, err)
	}
	if string(raw) == seed {
		os.Remove(path)
		return editedBuffer{text: current}, nil
	}
	return editedBuffer{text: strings.TrimSuffix(string(raw), "\n"), changed: true, path: path}, nil
}

func firstErr(errs ...error) error {
	for _, e := range errs {
		if e != nil {
			return e
		}
	}
	return nil
}
