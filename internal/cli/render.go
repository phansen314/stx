package cli

import (
	"encoding/json"
	"errors"
	"fmt"
	"strconv"

	"github.com/phansen314/stx/internal/client"
	"github.com/spf13/cobra"
)

// printJSON writes v as indented JSON (the --json escape hatch), matching Python's
// json.dumps(..., indent=2).
func printJSON(cmd *cobra.Command, v any) error {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return err
	}
	_, err = fmt.Fprintln(cmd.OutOrStdout(), string(b))
	return err
}

// parseID turns a positional id argument into an int64 (argparse type=int equivalent).
func parseID(s string) (int64, error) {
	id, err := strconv.ParseInt(s, 10, 64)
	if err != nil {
		return 0, fmt.Errorf("invalid id %q", s)
	}
	return id, nil
}

// FormatError maps a command error to the CLI's stderr line, mirroring Python's main():
// APIError → "error: <Variant>: <msg>", ConnError → "error: daemon request failed: …",
// everything else → "error: <msg>".
func FormatError(err error) string {
	var ae *client.APIError
	var ce *client.ConnError
	switch {
	case errors.As(err, &ae):
		return "error: " + ae.Error()
	case errors.As(err, &ce):
		return "error: " + ce.Error()
	default:
		return fmt.Sprintf("error: %v", err)
	}
}
