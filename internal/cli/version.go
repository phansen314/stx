package cli

import (
	"fmt"

	"github.com/phansen314/stx/internal/client"
	"github.com/phansen314/stx/internal/version"
	"github.com/spf13/cobra"
)

// versionPayload is the --json shape. Daemon is omitted when the daemon isn't reachable, so the
// key's presence is itself the answer to "is it up?".
type versionPayload struct {
	Version string         `json:"version"`
	Daemon  *daemonPayload `json:"daemon,omitempty"`
}

type daemonPayload struct {
	BaseURL string `json:"baseUrl"`
	Schema  int    `json:"schema"`
	Seq     int64  `json:"seq"`
}

// newVersionCmd reports the client's build version, plus the daemon's schema/seq when it answers.
//
// Deliberately does NOT dial(): `stx version` has to work with the daemon down — that's half of
// what you run it for. The daemon line is best-effort and silently absent otherwise. Never
// markEmpty(): a version is always a result.
func newVersionCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "version",
		Short: "client version, and the daemon's schema/seq when it's up",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			payload := versionPayload{Version: version.Version}
			lines := []string{"stx " + version.Version}

			if c := client.New(flagBaseURL); c.Ping() {
				if ch, err := c.Changes(); err == nil {
					payload.Daemon = &daemonPayload{BaseURL: flagBaseURL, Schema: ch.Schema, Seq: ch.Seq}
					lines = append(lines, fmt.Sprintf("daemon: %s (schema %d, seq %d)", flagBaseURL, ch.Schema, ch.Seq))
				}
			}
			// -q is the scriptable form: the bare version, so `v=$(stx version -q)` works.
			return emitLines(cmd, []string{version.Version}, payload, joinLines(lines))
		},
	}
}
