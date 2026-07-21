package cli

import (
	"testing"

	"github.com/phansen314/stx/internal/api"
)

func TestPickByRef(t *testing.T) {
	ss := []api.Status{{ID: 9, Name: "Backlog"}, {ID: 10, Name: "Implementation"}}
	idOf := func(s api.Status) int64 { return s.ID }
	nameOf := func(s api.Status) string { return s.Name }

	if got, err := pickByRef(ss, "10", "status", idOf, nameOf); err != nil || got.Name != "Implementation" {
		t.Fatalf("by id: %+v %v", got, err)
	}
	if got, err := pickByRef(ss, "Backlog", "status", idOf, nameOf); err != nil || got.ID != 9 {
		t.Fatalf("by name: %+v %v", got, err)
	}
	if _, err := pickByRef(ss, "99", "status", idOf, nameOf); err == nil || err.Error() != "no status with id 99" {
		t.Fatalf("id miss: %v", err)
	}
	if _, err := pickByRef(ss, "Zed", "status", idOf, nameOf); err == nil ||
		err.Error() != "no status named 'Zed'. available: Backlog, Implementation" {
		t.Fatalf("name miss: %v", err)
	}
	dup := []api.Status{{ID: 1, Name: "X"}, {ID: 2, Name: "X"}}
	if _, err := pickByRef(dup, "X", "status", idOf, nameOf); err == nil ||
		err.Error() != "status name 'X' is ambiguous (2 matches) — use an id" {
		t.Fatalf("ambiguous: %v", err)
	}
}
