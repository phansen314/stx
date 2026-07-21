package cli

import (
	"fmt"

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

// bashFzfCompletion wires `stx <TAB>` (at the command position) to an fzf menu whose preview pane
// shows each command's -h help. Falls back to plain name completion when fzf is absent. It calls
// the `stx` on PATH — point that at the Go binary (Phase 6, or a shell alias).
const bashFzfCompletion = `# stx fzf completion — eval "$(stx fzf-completion)"  (add that line to ~/.bashrc)
# TAB after 'stx' opens an fzf menu of commands, with each command's -h help live in the
# preview pane. Falls back to plain name completion when fzf is not installed.
_stx_fzf() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    [ "$COMP_CWORD" -eq 1 ] || return 0            # only complete the command word (this slice)
    if command -v fzf >/dev/null 2>&1; then
        local picked
        picked="$(stx __commands \
            | fzf --delimiter='\t' --nth=1,2 --with-nth=1,2 --height=40% --reverse \
                  --query="$cur" --preview 'stx {1} -h' --preview-window=right:55%:wrap \
            | cut -f1)"
        [ -n "$picked" ] && COMPREPLY=( "$picked" )
    else
        COMPREPLY=( $(compgen -W "$(stx __commands | cut -f1)" -- "$cur") )
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
			fmt.Fprint(cmd.OutOrStdout(), bashFzfCompletion)
			return nil
		},
	}
}
