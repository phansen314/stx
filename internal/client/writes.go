package client

import (
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
	body := map[string]any{"expectedVersion": expectedVersion}
	for k, v := range changes {
		body[k] = v
	}
	var out api.Task
	return out, c.call("PATCH", fmt.Sprintf("/tasks/%d", id), body, &out)
}
