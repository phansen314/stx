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
# Each picker shows the command-so-far as its fzf header ($1), so you always see what you build.
_stxb_ws() {      # $1=header -> workspace name
    command stx ls --json 2>/dev/null \
        | jq -r '.[] | "\(.name)\t\(.tracks) track(s)"' \
        | fzf --delimiter='\t' --with-nth=1,2 --height=45% --reverse --prompt='workspace> ' \
              --header="$1" | cut -f1
}
_stxb_track() {   # $1=ws $2=header -> track name
    command stx tree -w "$1" --json 2>/dev/null | jq -r '.tracks[].track' \
        | fzf --height=45% --reverse --prompt='track> ' --header="$2"
}
_stxb_task() {    # $1=ws $2=header -> task id
    command stx tree -w "$1" --json 2>/dev/null \
        | jq -r '.tracks[].tasks[] | "\(.id)\t[\(.status)] \(.title)"' \
        | fzf --delimiter='\t' --with-nth=2 --height=55% --reverse \
              --preview 'stx show {1}' --preview-window=right:55%:wrap --prompt='task> ' \
              --header="$2" | cut -f1
}
_stxb_status() {  # $1=ws $2=header -> status name
    command stx status ls -w "$1" --json 2>/dev/null | jq -r '.[].name' \
        | fzf --height=45% --reverse --prompt='status> ' --header="$2"
}

_stx_build() {
    command -v fzf >/dev/null 2>&1 || { command stx --help; return; }
    command -v jq  >/dev/null 2>&1 || { echo "stx builder needs jq" >&2; return; }
    local cmd
    cmd="$(command stx __commands \
        | fzf --delimiter='\t' --nth=1,2 --with-nth=1,2 --height=60% --reverse \
              --preview 'stx {1} -h' --preview-window=right:55%:wrap \
              --prompt='stx> ' --header='building:  stx …' | cut -f1)"
    [ -z "$cmd" ] && return

    local line='' ws id st tr title field val h
    case "$cmd" in
        add)
            ws="$(_stxb_ws       'building:  stx add …')";                       [ -z "$ws" ] && return
            tr="$(_stxb_track "$ws" "building:  stx add -w $ws …")";             [ -z "$tr" ] && return
            printf 'building:  stx add -w %s -t %s …\n' "$ws" "$tr"
            read -r -e -p 'title> ' title;                                       [ -z "$title" ] && return
            printf -v line 'stx add %q -w %q -t %q' "$title" "$ws" "$tr" ;;
        mv)
            ws="$(_stxb_ws       'building:  stx mv …')";                        [ -z "$ws" ] && return
            id="$(_stxb_task "$ws" "building:  stx mv …   (workspace: $ws)")";    [ -z "$id" ] && return
            st="$(_stxb_status "$ws" "building:  stx mv $id …")";                 [ -z "$st" ] && return
            printf -v line 'stx mv %s %q' "$id" "$st" ;;
        done)
            ws="$(_stxb_ws       'building:  stx done …')";                      [ -z "$ws" ] && return
            id="$(_stxb_task "$ws" "building:  stx done …   (workspace: $ws)")";  [ -z "$id" ] && return
            printf -v line 'stx done %s' "$id" ;;
        show)
            ws="$(_stxb_ws       'building:  stx show …')";                      [ -z "$ws" ] && return
            id="$(_stxb_task "$ws" "building:  stx show …   (workspace: $ws)")";  [ -z "$id" ] && return
            printf -v line 'stx show %s' "$id" ;;
        edit)
            ws="$(_stxb_ws       'building:  stx edit …')";                      [ -z "$ws" ] && return
            id="$(_stxb_task "$ws" "building:  stx edit …   (workspace: $ws)")";  [ -z "$id" ] && return
            h="building:  stx edit $id …"
            field="$(printf 'title\ndesc\npriority' \
                | fzf --height=30% --reverse --prompt='field> ' --header="$h")"; [ -z "$field" ] && return
            printf 'building:  stx edit %s --%s …\n' "$id" "$field"
            read -r -e -p "$field> " val;                                        [ -z "$val" ] && return
            printf -v line 'stx edit %s --%s %q' "$id" "$field" "$val" ;;
        next|tree)
            ws="$(_stxb_ws "building:  stx $cmd …")";                            [ -z "$ws" ] && return
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
