package cli

import (
	"fmt"
	"io"

	"github.com/spf13/cobra"
)

// newCommandsCmd is a hidden emitter of `name<TAB>short-help` for every top-level command,
// single-sourced from the cobra tree so it can't drift. The fzf completion script (below) feeds
// it into fzf; daemon-free, so completion works with the daemon stopped.
func newCommandsCmd() *cobra.Command {
	return &cobra.Command{
		Use:    "__commands",
		Hidden: true,
		Args:   cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			out := cmd.OutOrStdout()
			for _, c := range cmd.Root().Commands() {
				if c.Hidden || c.Name() == "__commands" {
					continue
				}
				fmt.Fprintf(out, "%s\t%s\n", c.Name(), c.Short)
			}
			return nil
		},
	}
}

// bashFzfCompletion wires `stx <TAB>` (the command word) to an fzf menu whose preview pane shows
// each command's -h help. Everything AFTER the command — flags, subcommands (meta ls/get/set/del,
// status default/archive, …) — delegates to cobra's own `__complete` protocol, so TAB keeps working
// past the command word. Self-contained: no bash-completion package needed. Without fzf, cobra's
// completion handles the command word too. Calls the `stx` on PATH (the Go binary after cutover).
const bashFzfCompletion = `# stx fzf completion — eval "$(stx fzf-completion)"  (add that line to ~/.bashrc)
# stx <TAB>            → fzf menu of commands, each command's -h in the preview pane
# stx <cmd> <TAB>      → fzf menu of that command's subcommands / flags (with descriptions),
#                        the command's -h in the preview; a lone free-text arg falls back to
#                        offering the flags so TAB is never dead
# One candidate inserts directly (no menu). Without fzf, plain completion is used throughout.
_stx_fzf() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    local fzf=0; command -v fzf >/dev/null 2>&1 && fzf=1

    # 1) the command word → fzf menu with -h help preview
    if [ "$COMP_CWORD" -eq 1 ] && [ $fzf -eq 1 ]; then
        local picked
        picked="$(stx __commands \
            | fzf --delimiter='\t' --nth=1,2 --with-nth=1,2 --height=40% --reverse \
                  --query="$cur" --preview 'stx {1} -h' --preview-window=right:55%:wrap \
            | cut -f1)"
        [ -n "$picked" ] && COMPREPLY=( "$picked" )
        return
    fi

    # 2) after the command → candidates from the CLI's own completion protocol
    local pre="${COMP_WORDS[*]:1:COMP_CWORD-1}"       # e.g. "meta ls" (parent path, no cur)
    local raw
    raw="$(stx __complete ${pre:+$pre} "$cur" 2>/dev/null | grep -v '^:')"
    # a bare free-text positional completes to nothing → offer the command's flags instead
    if [ -z "$raw" ] && [ "${cur:0:1}" != "-" ]; then
        raw="$(stx __complete ${pre:+$pre} -- 2>/dev/null | grep -v '^:')"
    fi
    [ -z "$raw" ] && return

    local names; names="$(cut -f1 <<<"$raw")"
    if [ $fzf -eq 1 ] && [ "$(wc -l <<<"$names")" -gt 1 ]; then
        local picked
        picked="$(printf '%s\n' "$raw" \
            | fzf --delimiter='\t' --nth=1,2 --with-nth=1,2 --height=40% --reverse \
                  --query="$cur" --preview "stx $pre -h" --preview-window=right:55%:wrap \
            | cut -f1)"
        [ -n "$picked" ] && COMPREPLY=( "$picked" )
    else
        COMPREPLY=( $(compgen -W "$names" -- "$cur") )
    fi
}
complete -F _stx_fzf stx
`

func newFzfCompletionCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "fzf-completion",
		Short: "print a bash completion script: `stx <TAB>` → fzf menu with help preview",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			_, err := io.WriteString(cmd.OutOrStdout(), bashFzfCompletion)
			return err
		},
	}
}
