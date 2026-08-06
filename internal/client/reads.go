package client

import (
	"fmt"
	"net/url"
	"sort"
	"strconv"

	"github.com/phansen314/stx/internal/api"
)

// ListWorkspaces → GET /workspaces.
func (c *Client) ListWorkspaces() ([]api.Workspace, error) {
	var out api.Items[api.Workspace]
	return out.Items, c.call("GET", "/workspaces", nil, &out)
}

// Tracks → GET /workspaces/{ws}/tracks.
func (c *Client) Tracks(ws int64) ([]api.Track, error) {
	var out api.Items[api.Track]
	return out.Items, c.call("GET", fmt.Sprintf("/workspaces/%d/tracks", ws), nil, &out)
}

// Statuses → GET /workspaces/{ws}/statuses, sorted (kanbanOrder, id) like the Python client so
// "first terminal" and kanban ordering are deterministic regardless of daemon row order.
func (c *Client) Statuses(ws int64) ([]api.Status, error) {
	var out api.Items[api.Status]
	if err := c.call("GET", fmt.Sprintf("/workspaces/%d/statuses", ws), nil, &out); err != nil {
		return nil, err
	}
	sort.Slice(out.Items, func(i, j int) bool {
		if out.Items[i].KanbanOrder != out.Items[j].KanbanOrder {
			return out.Items[i].KanbanOrder < out.Items[j].KanbanOrder
		}
		return out.Items[i].ID < out.Items[j].ID
	})
	return out.Items, nil
}

// Transitions → GET /workspaces/{ws}/transitions (the legal-move state machine).
func (c *Client) Transitions(ws int64) ([]api.Transition, error) {
	var out api.Items[api.Transition]
	return out.Items, c.call("GET", fmt.Sprintf("/workspaces/%d/transitions", ws), nil, &out)
}

// RelatesKinds → GET /workspaces/{ws}/relates-kinds (free-text kinds currently in use).
func (c *Client) RelatesKinds(ws int64) ([]string, error) {
	var out api.Items[string]
	return out.Items, c.call("GET", fmt.Sprintf("/workspaces/%d/relates-kinds", ws), nil, &out)
}

// Blockers → GET /tasks/{id}/blockers[?depth=], the inverse of Next: the unfinished tasks holding
// this one back, ordered depth-shallowest-first.
func (c *Client) Blockers(id int64, depth *int64) ([]api.Blocker, error) {
	path := fmt.Sprintf("/tasks/%d/blockers", id)
	if depth != nil {
		path += "?depth=" + strconv.FormatInt(*depth, 10)
	}
	var out api.Items[api.Blocker]
	return out.Items, c.call("GET", path, nil, &out)
}

// Changes → GET /changes, the daemon's liveness/poll token: a run-scoped write counter plus the
// schema version. `seq` does not survive a restart (a durable cursor is deferred by design), so
// treat it as "has anything changed since I last looked", never as a resumable position.
func (c *Client) Changes() (api.Changes, error) {
	var out api.Changes
	return out, c.call("GET", "/changes", nil, &out)
}

// Edges → GET /workspaces/{ws}/edges (bulk export for graph).
func (c *Client) Edges(ws int64) (api.Edges, error) {
	var out api.Edges
	return out, c.call("GET", fmt.Sprintf("/workspaces/%d/edges", ws), nil, &out)
}

// Kinds → GET /workspaces/{ws}/kinds.
func (c *Client) Kinds(ws int64) ([]api.Kind, error) {
	var out api.Items[api.Kind]
	return out.Items, c.call("GET", fmt.Sprintf("/workspaces/%d/kinds", ws), nil, &out)
}

// Segments → GET /tracks/{track}/segments.
func (c *Client) Segments(track int64) ([]api.Segment, error) {
	var out api.Items[api.Segment]
	return out.Items, c.call("GET", fmt.Sprintf("/tracks/%d/segments", track), nil, &out)
}

// TrackTasks → GET /tracks/{track}/tasks (daemon orders priority DESC, id ASC).
func (c *Client) TrackTasks(track int64) ([]api.Task, error) {
	var out api.Items[api.Task]
	return out.Items, c.call("GET", fmt.Sprintf("/tracks/%d/tasks", track), nil, &out)
}

// TaskDetail → GET /tasks/{id}.
func (c *Client) TaskDetail(id int64) (api.TaskDetail, error) {
	var out api.TaskDetail
	return out, c.call("GET", fmt.Sprintf("/tasks/%d", id), nil, &out)
}

// NextParams is the frontier query. Workspace scope is required; every other field is an
// optional filter and a nil pointer omits its query param entirely — the daemon reads them with
// longQuery(), so "absent" and "zero" are different things.
type NextParams struct {
	Workspace                   int64
	Track, Segment, Kind, Limit *int64
	// As identifies the caller so its own leases stay visible; empty means an anonymous read,
	// which sees only unleased work.
	As string
}

// Next → GET /next?workspace=&track=&segment=&kind=&limit=&as=.
func (c *Client) Next(p NextParams) ([]api.FrontierItem, error) {
	q := url.Values{"workspace": {strconv.FormatInt(p.Workspace, 10)}}
	for name, v := range map[string]*int64{
		"track": p.Track, "segment": p.Segment, "kind": p.Kind, "limit": p.Limit,
	} {
		if v != nil {
			q.Set(name, strconv.FormatInt(*v, 10))
		}
	}
	if p.As != "" {
		q.Set("as", p.As)
	}
	var out api.Items[api.FrontierItem]
	return out.Items, c.call("GET", "/next?"+q.Encode(), nil, &out)
}

// Claims → GET /workspaces/{ws}/claims (live leases only; expired ones are not rows).
func (c *Client) Claims(ws int64) ([]api.Claim, error) {
	var out api.Items[api.Claim]
	return out.Items, c.call("GET", fmt.Sprintf("/workspaces/%d/claims", ws), nil, &out)
}
