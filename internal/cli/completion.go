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

// bashFzfCompletion wires `stx <TAB>` (the command word) to an fzf menu whose preview pane shows
// each command's -h help. Everything AFTER the command — flags, subcommands (meta ls/get/set/del,
// status default/archive, …) — delegates to cobra's own `__complete` protocol, so TAB keeps working
// past the command word. Self-contained: no bash-completion package needed. Without fzf, cobra's
// completion handles the command word too. Calls the `stx` on PATH (the Go binary after cutover).
const bashFzfCompletion = `# stx fzf completion — eval "$(stx fzf-completion)"  (add that line to ~/.bashrc)
# The command word (stx <TAB>) opens an fzf menu with each command's -h help in the preview pane.
# After a command is chosen, TAB completes that command's flags and subcommands. Needs fzf for the
# menu; without it, TAB uses the CLI's own completion everywhere.
_stx_fzf() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    # command word → fzf menu with help preview
    if [ "$COMP_CWORD" -eq 1 ] && command -v fzf >/dev/null 2>&1; then
        local picked
        picked="$(stx __commands \
            | fzf --delimiter='\t' --nth=1,2 --with-nth=1,2 --height=40% --reverse \
                  --query="$cur" --preview 'stx {1} -h' --preview-window=right:55%:wrap \
            | cut -f1)"
        [ -n "$picked" ] && COMPREPLY=( "$picked" )
        return
    fi
    # everything else → the CLI's own completion protocol (flags, subcommands, values)
    local args name comps=()
    args=( "${COMP_WORDS[@]:1:COMP_CWORD-1}" "$cur" )
    while IFS=$'\t' read -r name _; do
        [ "${name:0:1}" = ":" ] && continue        # skip the trailing :directive line
        comps+=( "$name" )
    done < <(stx __complete "${args[@]}" 2>/dev/null)
    COMPREPLY=( $(compgen -W "${comps[*]}" -- "$cur") )
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
