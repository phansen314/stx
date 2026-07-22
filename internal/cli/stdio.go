package cli

import (
	"bufio"
	"fmt"
	"io"
	"strings"

	"github.com/spf13/cobra"
)

// stdinClaimed names the argument that consumed stdin this invocation ("" = still free). Stdin is
// a single stream: `stx done - --desc -` cannot mean two things, so the second claim errors.
var stdinClaimed string

func claimStdin(what string) error {
	if stdinClaimed != "" {
		return fmt.Errorf("stdin is already being read for %s — only one `-` per command", stdinClaimed)
	}
	stdinClaimed = what
	return nil
}

// readIDs resolves a positional id argument: the single parsed id, or — when arg is "-" — every id
// read from stdin. Piped lines are read leniently so both output modes round-trip:
//
//	stx next -w ws -q | stx done -      # bare ids
//	stx next -w ws    | stx done -      # the padded human render ("  41  P2  [Todo]  title")
//
// Only the first whitespace-separated field is parsed, a leading "#" is stripped (matching how
// `show`/`tree` print ids), blank lines are skipped, and a "#" followed by anything non-numeric is
// treated as a comment.
func readIDs(cmd *cobra.Command, arg string) ([]int64, error) {
	if arg != "-" {
		id, err := parseID(arg)
		if err != nil {
			return nil, err
		}
		return []int64{id}, nil
	}
	if err := claimStdin("<id>"); err != nil {
		return nil, err
	}
	var ids []int64
	sc := bufio.NewScanner(cmd.InOrStdin())
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" {
			continue
		}
		field := strings.Fields(line)[0]
		field = strings.TrimPrefix(field, "#")
		if field == "" || field[0] < '0' || field[0] > '9' {
			continue // a comment line, or a header — not an id
		}
		id, err := parseID(field)
		if err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}
	if err := sc.Err(); err != nil {
		return nil, fmt.Errorf("reading ids from stdin: %w", err)
	}
	if len(ids) == 0 {
		return nil, fmt.Errorf("no ids on stdin")
	}
	return ids, nil
}

// readValue returns a flag's value, or all of stdin when it is "-" (one trailing newline trimmed,
// so `--desc - < notes.md` stores the file as typed). `what` names the flag in the clash error.
func readValue(cmd *cobra.Command, v, what string) (string, error) {
	if v != "-" {
		return v, nil
	}
	if err := claimStdin(what); err != nil {
		return "", err
	}
	b, err := io.ReadAll(cmd.InOrStdin())
	if err != nil {
		return "", fmt.Errorf("reading %s from stdin: %w", what, err)
	}
	return strings.TrimSuffix(string(b), "\n"), nil
}

// runIDs applies op to each id. A single id propagates its error verbatim; a batch keeps going
// past failures (xargs/rm semantics), reporting each on stderr, and fails the command if any did.
func runIDs(cmd *cobra.Command, ids []int64, op func(id int64) error) error {
	if len(ids) == 1 {
		return op(ids[0])
	}
	failed := 0
	for _, id := range ids {
		if err := op(id); err != nil {
			fmt.Fprintln(cmd.ErrOrStderr(), FormatError(err))
			failed++
		}
	}
	if failed > 0 {
		return fmt.Errorf("%d of %d failed", failed, len(ids))
	}
	return nil
}
