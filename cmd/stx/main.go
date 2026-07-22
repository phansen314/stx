// Command stx is the Go client for the stx daemon (Phase 0 spine: ls + edit).
package main

import (
	"os"

	"github.com/phansen314/stx/internal/cli"
)

// Exit codes follow grep: 0 results, 1 empty result set, 2 error (see internal/cli/exit.go).
func main() { os.Exit(cli.Run()) }
