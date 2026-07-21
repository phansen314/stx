package cli

import (
	"errors"

	"github.com/phansen314/stx/internal/client"
)

// retryConflict mirrors Python's _retry_conflict: read the current version, run do(version),
// and on a daemon VersionConflict re-read the version once and retry a single time. Any other
// error propagates. The typed *client.APIError match replaces string-scraping the envelope.
func retryConflict[T any](get func() (int, error), do func(version int) (T, error)) (T, error) {
	var zero T
	version, err := get()
	if err != nil {
		return zero, err
	}
	out, err := do(version)
	if err == nil {
		return out, nil
	}
	var ae *client.APIError
	if !errors.As(err, &ae) || ae.Variant != "VersionConflict" {
		return zero, err
	}
	if version, err = get(); err != nil { // stale → re-read once
		return zero, err
	}
	return do(version)
}
