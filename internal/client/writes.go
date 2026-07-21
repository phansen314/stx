package client

import (
	"fmt"

	"github.com/phansen314/stx/internal/api"
)

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
