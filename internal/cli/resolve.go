package cli

import (
	"fmt"
	"sort"
	"strconv"
	"strings"

	"github.com/phansen314/stx/internal/api"
	"github.com/phansen314/stx/internal/client"
)

// pickByRef resolves a name-or-id ref against a list, mirroring context._pick: numeric → by id;
// else exact name match (error on miss with the available names, or on ambiguity).
func pickByRef[T any](items []T, ref, kind string, idOf func(T) int64, nameOf func(T) string) (T, error) {
	var zero T
	if id, e := strconv.ParseInt(ref, 10, 64); e == nil {
		for _, it := range items {
			if idOf(it) == id {
				return it, nil
			}
		}
		return zero, fmt.Errorf("no %s with id %d", kind, id)
	}
	var matches []T
	names := make([]string, 0, len(items))
	for _, it := range items {
		names = append(names, nameOf(it))
		if nameOf(it) == ref {
			matches = append(matches, it)
		}
	}
	switch len(matches) {
	case 1:
		return matches[0], nil
	case 0:
		sort.Strings(names)
		avail := "(none)"
		if len(names) > 0 {
			avail = strings.Join(names, ", ")
		}
		return zero, fmt.Errorf("no %s named '%s'. available: %s", kind, ref, avail)
	default:
		return zero, fmt.Errorf("%s name '%s' is ambiguous (%d matches) — use an id", kind, ref, len(matches))
	}
}

func resolveWorkspace(c *client.Client, ref string) (api.Workspace, error) {
	if ref == "" {
		return api.Workspace{}, fmt.Errorf("--workspace required (e.g. -w auth-rewrite)")
	}
	wss, err := c.ListWorkspaces()
	if err != nil {
		return api.Workspace{}, err
	}
	return pickByRef(wss, ref, "workspace", func(w api.Workspace) int64 { return w.ID }, func(w api.Workspace) string { return w.Name })
}

func resolveTrack(c *client.Client, wsID int64, ref string) (api.Track, error) {
	tracks, err := c.Tracks(wsID)
	if err != nil {
		return api.Track{}, err
	}
	return pickByRef(tracks, ref, "track", func(t api.Track) int64 { return t.ID }, func(t api.Track) string { return t.Name })
}

// resolveStatusIn / resolveKindIn pick from an already-fetched list (mirror context.status/kind).
func resolveStatusIn(statuses []api.Status, ref string) (api.Status, error) {
	return pickByRef(statuses, ref, "status", func(s api.Status) int64 { return s.ID }, func(s api.Status) string { return s.Name })
}

func resolveKindIn(kinds []api.Kind, ref string) (api.Kind, error) {
	return pickByRef(kinds, ref, "kind", func(k api.Kind) int64 { return k.ID }, func(k api.Kind) string { return k.Name })
}

// statusNames / kindNames build id→name maps for rendering (mirror _status_names/_kind_names).
func statusNames(c *client.Client, wsID int64) (map[int64]string, error) {
	ss, err := c.Statuses(wsID)
	if err != nil {
		return nil, err
	}
	m := make(map[int64]string, len(ss))
	for _, s := range ss {
		m[s.ID] = s.Name
	}
	return m, nil
}

func kindNames(c *client.Client, wsID int64) (map[int64]string, error) {
	ks, err := c.Kinds(wsID)
	if err != nil {
		return nil, err
	}
	m := make(map[int64]string, len(ks))
	for _, k := range ks {
		m[k.ID] = k.Name
	}
	return m, nil
}
