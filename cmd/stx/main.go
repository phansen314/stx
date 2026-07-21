// Command stx is the Go client for the stx daemon (Phase 0 spine: ls + edit).
package main

import (
	"fmt"
	"os"

	"github.com/phansen314/stx/internal/cli"
)

func main() {
	if err := cli.NewRootCmd().Execute(); err != nil {
		fmt.Fprintln(os.Stderr, cli.FormatError(err))
		os.Exit(1)
	}
}
