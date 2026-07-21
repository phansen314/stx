package client

import (
	"fmt"

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

// Statuses → GET /workspaces/{ws}/statuses.
func (c *Client) Statuses(ws int64) ([]api.Status, error) {
	var out api.Items[api.Status]
	return out.Items, c.call("GET", fmt.Sprintf("/workspaces/%d/statuses", ws), nil, &out)
}

// TaskDetail → GET /tasks/{id}.
func (c *Client) TaskDetail(id int64) (api.TaskDetail, error) {
	var out api.TaskDetail
	return out, c.call("GET", fmt.Sprintf("/tasks/%d", id), nil, &out)
}
