package client

import (
	"fmt"
	"net/url"
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

// Statuses → GET /workspaces/{ws}/statuses.
func (c *Client) Statuses(ws int64) ([]api.Status, error) {
	var out api.Items[api.Status]
	return out.Items, c.call("GET", fmt.Sprintf("/workspaces/%d/statuses", ws), nil, &out)
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
