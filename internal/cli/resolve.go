package cli

import (
	"fmt"
	"sort"
	"strconv"
	"strings"

	"github.com/phansen314/stx/internal/api"
	"github.com/phansen314/stx/internal/client"
)

// resolveWorkspace turns a -w name-or-id into a Workspace, mirroring context.workspace/_pick:
// numeric → by id; else exact name (error on miss/ambiguity). Empty ref → the "required" error.
func resolveWorkspace(c *client.Client, ref string) (api.Workspace, error) {
	if ref == "" {
		return api.Workspace{}, fmt.Errorf("--workspace required (e.g. -w auth-rewrite)")
	}
	wss, err := c.ListWorkspaces()
	if err != nil {
		return api.Workspace{}, err
	}
	if id, e := strconv.ParseInt(ref, 10, 64); e == nil {
		for _, w := range wss {
			if w.ID == id {
				return w, nil
			}
		}
		return api.Workspace{}, fmt.Errorf("no workspace with id %d", id)
	}
	var matches []api.Workspace
	names := make([]string, 0, len(wss))
	for _, w := range wss {
		names = append(names, w.Name)
		if w.Name == ref {
			matches = append(matches, w)
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
		return api.Workspace{}, fmt.Errorf("no workspace named '%s'. available: %s", ref, avail)
	default:
		return api.Workspace{}, fmt.Errorf("workspace name '%s' is ambiguous (%d matches) — use an id", ref, len(matches))
	}
}

// resolveTrack turns a --track name-or-id into a Track within a workspace.
func resolveTrack(c *client.Client, wsID int64, ref string) (api.Track, error) {
	tracks, err := c.Tracks(wsID)
	if err != nil {
		return api.Track{}, err
	}
	if id, e := strconv.ParseInt(ref, 10, 64); e == nil {
		for _, t := range tracks {
			if t.ID == id {
				return t, nil
			}
		}
		return api.Track{}, fmt.Errorf("no track with id %d", id)
	}
	var matches []api.Track
	names := make([]string, 0, len(tracks))
	for _, t := range tracks {
		names = append(names, t.Name)
		if t.Name == ref {
			matches = append(matches, t)
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
		return api.Track{}, fmt.Errorf("no track named '%s'. available: %s", ref, avail)
	default:
		return api.Track{}, fmt.Errorf("track name '%s' is ambiguous (%d matches) — use an id", ref, len(matches))
	}
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
