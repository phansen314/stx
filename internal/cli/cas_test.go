package cli

import (
	"errors"
	"testing"

	"github.com/phansen314/stx/internal/client"
)

func TestRetryConflict_SuccessFirstTry(t *testing.T) {
	gets := 0
	out, err := retryConflict(
		func() (int, error) { gets++; return 5, nil },
		func(v int) (string, error) {
			if v != 5 {
				t.Fatalf("want version 5, got %d", v)
			}
			return "ok", nil
		},
	)
	if err != nil || out != "ok" || gets != 1 {
		t.Fatalf("out=%q err=%v gets=%d", out, err, gets)
	}
}

func TestRetryConflict_ReReadsOnceOnVersionConflict(t *testing.T) {
	versions := []int{5, 6}
	gets := 0
	var seen []int
	out, err := retryConflict(
		func() (int, error) { v := versions[gets]; gets++; return v, nil },
		func(v int) (string, error) {
			seen = append(seen, v)
			if len(seen) == 1 {
				return "", &client.APIError{Variant: "VersionConflict"}
			}
			return "ok", nil
		},
	)
	if err != nil || out != "ok" {
		t.Fatalf("out=%q err=%v", out, err)
	}
	if gets != 2 || len(seen) != 2 || seen[0] != 5 || seen[1] != 6 {
		t.Fatalf("expected re-read with fresh version: gets=%d seen=%v", gets, seen)
	}
}

func TestRetryConflict_PropagatesOtherErrors(t *testing.T) {
	boom := &client.APIError{Variant: "NotFound"}
	_, err := retryConflict(
		func() (int, error) { return 1, nil },
		func(int) (string, error) { return "", boom },
	)
	var ae *client.APIError
	if !errors.As(err, &ae) || ae.Variant != "NotFound" {
		t.Fatalf("want NotFound propagated, got %v", err)
	}
}
