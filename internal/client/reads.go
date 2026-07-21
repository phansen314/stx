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

// Next → GET /next?workspace=&track=&segment=&limit= (nil pointers omit the param).
func (c *Client) Next(ws int64, track, segment, limit *int64) ([]api.FrontierItem, error) {
	q := url.Values{"workspace": {strconv.FormatInt(ws, 10)}}
	if track != nil {
		q.Set("track", strconv.FormatInt(*track, 10))
	}
	if segment != nil {
		q.Set("segment", strconv.FormatInt(*segment, 10))
	}
	if limit != nil {
		q.Set("limit", strconv.FormatInt(*limit, 10))
	}
	var out api.Items[api.FrontierItem]
	return out.Items, c.call("GET", "/next?"+q.Encode(), nil, &out)
}
