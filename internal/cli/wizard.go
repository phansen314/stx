package cli

import (
	"io"

	"github.com/spf13/cobra"
)

// bashWizard is the guided command builder. Bare `stx` in a terminal (no args) runs an fzf chain
// that assembles a command and drops it on the prompt (editable) via `read -e -i`; with args, the
// `stx` function forwards to the real binary (`command stx`). v1 covers the daily loop; other
// commands fall back to placing `stx <cmd> ` on the prompt for you to finish (TAB completes).
const bashWizard = `# stx guided builder — bare 'stx' (terminal, no args) → fzf chain → command on your prompt.
_stxb_ws() {      # -> workspace name
    command stx ls --json 2>/dev/null \
        | jq -r '.[] | "\(.name)\t\(.tracks) track(s)"' \
        | fzf --delimiter='\t' --with-nth=1,2 --height=40% --reverse --prompt='workspace> ' | cut -f1
}
_stxb_track() {   # $1=ws -> track name
    command stx tree -w "$1" --json 2>/dev/null | jq -r '.tracks[].track' \
        | fzf --height=40% --reverse --prompt='track> '
}
_stxb_task() {    # $1=ws -> task id
    command stx tree -w "$1" --json 2>/dev/null \
        | jq -r '.tracks[].tasks[] | "\(.id)\t[\(.status)] \(.title)"' \
        | fzf --delimiter='\t' --with-nth=2 --height=50% --reverse \
              --preview 'stx show {1}' --preview-window=right:55%:wrap --prompt='task> ' | cut -f1
}
_stxb_status() {  # $1=ws -> status name
    command stx status ls -w "$1" --json 2>/dev/null | jq -r '.[].name' \
        | fzf --height=40% --reverse --prompt='status> '
}

_stx_build() {
    command -v fzf >/dev/null 2>&1 || { command stx --help; return; }
    command -v jq  >/dev/null 2>&1 || { echo "stx builder needs jq" >&2; return; }
    local cmd
    cmd="$(command stx __commands \
        | fzf --delimiter='\t' --nth=1,2 --with-nth=1,2 --height=60% --reverse \
              --preview 'stx {1} -h' --preview-window=right:55%:wrap --prompt='stx> ' | cut -f1)"
    [ -z "$cmd" ] && return

    local line='' ws id st tr title field val
    case "$cmd" in
        add)
            ws="$(_stxb_ws)";          [ -z "$ws" ] && return
            tr="$(_stxb_track "$ws")"; [ -z "$tr" ] && return
            read -r -e -p 'title> ' title; [ -z "$title" ] && return
            printf -v line 'stx add %q -w %q -t %q' "$title" "$ws" "$tr" ;;
        mv)
            ws="$(_stxb_ws)";           [ -z "$ws" ] && return
            id="$(_stxb_task "$ws")";   [ -z "$id" ] && return
            st="$(_stxb_status "$ws")"; [ -z "$st" ] && return
            printf -v line 'stx mv %s %q' "$id" "$st" ;;
        done)
            ws="$(_stxb_ws)"; id="$(_stxb_task "$ws")"; [ -z "$id" ] && return
            printf -v line 'stx done %s' "$id" ;;
        show)
            ws="$(_stxb_ws)"; id="$(_stxb_task "$ws")"; [ -z "$id" ] && return
            printf -v line 'stx show %s' "$id" ;;
        edit)
            ws="$(_stxb_ws)"; id="$(_stxb_task "$ws")"; [ -z "$id" ] && return
            field="$(printf 'title\ndesc\npriority' | fzf --height=20% --reverse --prompt='field> ')"
            [ -z "$field" ] && return
            read -r -e -p "$field> " val; [ -z "$val" ] && return
            printf -v line 'stx edit %s --%s %q' "$id" "$field" "$val" ;;
        next|tree)
            ws="$(_stxb_ws)"; [ -z "$ws" ] && return
            printf -v line 'stx %s -w %q' "$cmd" "$ws" ;;
        ls)
            line='stx ls' ;;
        *)
            printf -v line 'stx %s ' "$cmd" ;;    # fallback: finish it yourself (TAB completes)
    esac
    [ -z "$line" ] && return

    local final
    IFS= read -r -e -i "$line" -p 'run> ' final
    [ -n "$final" ] && eval "$final"
}

# The stx wrapper: no args in a terminal -> the builder; otherwise the real binary.
stx() {
    if [ "$#" -eq 0 ] && [ -t 0 ] && [ -t 1 ]; then
        _stx_build
    else
        command stx "$@"
    fi
}
`

// newShellInitCmd prints the full shell integration: the fzf completion AND the guided builder.
// eval "$(stx shell-init)" in ~/.bashrc sets up both.
func newShellInitCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "shell-init",
		Short: "print full shell integration (fzf completion + bare-stx guided builder); eval it",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			if _, err := io.WriteString(cmd.OutOrStdout(), bashWizard); err != nil {
				return err
			}
			_, err := io.WriteString(cmd.OutOrStdout(), bashFzfCompletion)
			return err
		},
	}
}
