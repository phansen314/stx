package client

import (
	"encoding/json"
	"fmt"

	"github.com/phansen314/stx/internal/api"
)

// CreateTaskParams mirrors create_task; exactly one of Track/Segment is set. StatusID/KindID are
// omitted from the body when nil (daemon applies the workspace default status).
type CreateTaskParams struct {
	Track       *int64
	Segment     *int64
	Title       string
	Description string
	Priority    int
	StatusID    *int64
	KindID      *int64
}

// CreateTask → POST /segments/{id}/tasks or /tracks/{id}/tasks.
func (c *Client) CreateTask(p CreateTaskParams) (api.Task, error) {
	body := map[string]any{"title": p.Title, "description": p.Description, "priority": p.Priority}
	if p.StatusID != nil {
		body["statusId"] = *p.StatusID
	}
	if p.KindID != nil {
		body["kindId"] = *p.KindID
	}
	var out api.Task
	if p.Segment != nil {
		return out, c.call("POST", fmt.Sprintf("/segments/%d/tasks", *p.Segment), body, &out)
	}
	return out, c.call("POST", fmt.Sprintf("/tracks/%d/tasks", *p.Track), body, &out)
}

// MoveStatus → POST /tasks/{id}/status (CAS on expectedVersion; validates the transition).
func (c *Client) MoveStatus(id, toStatusID int64, expectedVersion int) (api.Task, error) {
	body := map[string]any{"toStatusId": toStatusID, "expectedVersion": expectedVersion}
	var out api.Task
	return out, c.call("POST", fmt.Sprintf("/tasks/%d/status", id), body, &out)
}

// EditTask → PATCH /tasks/{id}. changes is a partial-update map (camelCase keys) merged with
// the required expectedVersion CAS token; a field present updates it, absent leaves it. Only
// kindId uses the explicit clearKind flag to distinguish "clear" from "unchanged".
func (c *Client) EditTask(id int64, expectedVersion int, changes map[string]any) (api.Task, error) {
	body := withVersion(expectedVersion, changes)
	var out api.Task
	return out, c.call("PATCH", fmt.Sprintf("/tasks/%d", id), body, &out)
}

// EditTrack / EditWorkspace → PATCH with a CAS token (used by meta set/del on those entities).
func (c *Client) EditTrack(id int64, expectedVersion int, changes map[string]any) (api.Track, error) {
	var out api.Track
	return out, c.call("PATCH", fmt.Sprintf("/tracks/%d", id), withVersion(expectedVersion, changes), &out)
}

func (c *Client) EditWorkspace(id int64, expectedVersion int, changes map[string]any) (api.Workspace, error) {
	var out api.Workspace
	return out, c.call("PATCH", fmt.Sprintf("/workspaces/%d", id), withVersion(expectedVersion, changes), &out)
}

func withVersion(v int, changes map[string]any) map[string]any {
	body := map[string]any{"expectedVersion": v}
	for k, val := range changes {
		body[k] = val
	}
	return body
}

// Edge writes drive the `next` frontier. block/relate add; unblock/unrelate archive the edge.
// The daemon's response body is returned verbatim (json.RawMessage) for --json output.
func (c *Client) AddBlocks(source, target int64) (json.RawMessage, error) {
	return c.edge("/blocks", map[string]any{"sourceTaskId": source, "targetTaskId": target})
}

func (c *Client) RemoveBlocks(source, target int64) (json.RawMessage, error) {
	return c.edge("/blocks/archive", map[string]any{"sourceTaskId": source, "targetTaskId": target})
}

func (c *Client) AddRelates(kind string, source, target int64) (json.RawMessage, error) {
	return c.edge("/relates", map[string]any{"kind": kind, "sourceTaskId": source, "targetTaskId": target})
}

func (c *Client) RemoveRelates(kind string, source, target int64) (json.RawMessage, error) {
	return c.edge("/relates/archive", map[string]any{"kind": kind, "sourceTaskId": source, "targetTaskId": target})
}

func (c *Client) edge(path string, body map[string]any) (json.RawMessage, error) {
	var out json.RawMessage
	return out, c.call("POST", path, body, &out)
}

// Archive → POST /{kind}/{id}/archive, kind ∈ {tasks, segments, tracks, workspaces}.
func (c *Client) Archive(kind string, id int64) error {
	return c.call("POST", fmt.Sprintf("/%s/%d/archive", kind, id), nil, nil)
}
