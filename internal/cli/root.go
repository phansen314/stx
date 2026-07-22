// Package cli builds the cobra command tree for the stx CLI.
package cli

import (
	"fmt"
	"os"

	"github.com/phansen314/stx/internal/client"
	"github.com/spf13/cobra"
)

// persistent-flag values, bound on the root command (cobra parses them in any position).
var (
	flagBaseURL string
	flagJSON    bool
)

// NewRootCmd assembles the full command tree. Phase 0: ls + edit.
func NewRootCmd() *cobra.Command {
	root := &cobra.Command{
		Use:           "stx",
		Short:         "stateless CLI over the stx daemon",
		SilenceUsage:  true, // errors are ours to print; don't dump usage on RunE failure
		SilenceErrors: true,
	}
	def := os.Getenv("STX_URL")
	if def == "" {
		def = client.DefaultBaseURL
	}
	root.PersistentFlags().StringVar(&flagBaseURL, "base-url", def, "daemon URL")
	root.PersistentFlags().BoolVar(&flagJSON, "json", false, "emit raw JSON instead of compact text")

	root.AddCommand(
		newLsCmd(), newTreeCmd(), newNextCmd(), newShowCmd(),
		newAddCmd(), newMvCmd(), newEditCmd(), newDoneCmd(),
		newBlockCmd(), newRelateCmd(), newUnblockCmd(), newUnrelateCmd(), newRelateKindsCmd(),
		newMetaCmd(), newGraphCmd(), newArchiveCmd(), newPickCmd(),
		newWsCmd(), newTrackCmd(), newSegmentCmd(), newStatusCmd(), newKindCmd(), newTransitionCmd(),
	)
	registerCompletions(root)
	return root
}

// dial builds a client and verifies the daemon is reachable (mirrors Python's _client).
func dial() (*client.Client, error) {
	c := client.New(flagBaseURL)
	if !c.Ping() {
		return nil, fmt.Errorf("daemon unreachable at %s — start it with ./gradlew run", flagBaseURL)
	}
	return c, nil
}
