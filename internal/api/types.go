// Package api holds the wire DTOs that mirror the stx daemon's JSON exactly.
//
// Field json tags are camelCase to match the daemon (kotlinx serializes property names
// verbatim), so json.MarshalIndent reproduces the Python client's `--json` output and the
// parity harness can diff the two directly. All list endpoints wrap rows in {"items":[...]}.
package api

// Items is the generic {"items":[...]} envelope every list endpoint returns.
type Items[T any] struct {
	Items []T `json:"items"`
}

type Workspace struct {
	ID           int64  `json:"id"`
	Name         string `json:"name"`
	MetadataJSON string `json:"metadataJson"`
	Archived     bool   `json:"archived"`
	Version      int    `json:"version"`
	CreatedAt    string `json:"createdAt"`
	UpdatedAt    string `json:"updatedAt"`
}

type Track struct {
	ID          int64  `json:"id"`
	WorkspaceID int64  `json:"workspaceId"`
	Name        string `json:"name"`
	Description string `json:"description"`
	Archived    bool   `json:"archived"`
	Version     int    `json:"version"`
}

type Status struct {
	ID          int64  `json:"id"`
	WorkspaceID int64  `json:"workspaceId"`
	Name        string `json:"name"`
	KanbanOrder int    `json:"kanbanOrder"`
	Terminal    bool   `json:"terminal"`
	IsDefault   bool   `json:"isDefault"`
	Archived    bool   `json:"archived"`
}

// Task is the full task row returned by GET /tasks/{id} (as detail.task) and PATCH /tasks/{id}.
type Task struct {
	ID           int64  `json:"id"`
	WorkspaceID  int64  `json:"workspaceId"`
	SegmentID    int64  `json:"segmentId"`
	StatusID     int64  `json:"statusId"`
	KindID       *int64 `json:"kindId"`
	Title        string `json:"title"`
	Description  string `json:"description"`
	Priority     int    `json:"priority"`
	MetadataJSON string `json:"metadataJson"`
	Archived     bool   `json:"archived"`
	Version      int    `json:"version"`
	CreatedAt    string `json:"createdAt"`
	UpdatedAt    string `json:"updatedAt"`
}

// TaskDetail is GET /tasks/{id}: the task plus its incident edges.
type TaskDetail struct {
	Task      Task           `json:"task"`
	BlocksIn  []int64        `json:"blocksIn"`
	BlocksOut []int64        `json:"blocksOut"`
	Relates   []RelatesEdge  `json:"relates"`
}

type RelatesEdge struct {
	Kind        string `json:"kind"`
	OtherTaskID int64  `json:"otherTaskId"`
	Outgoing    bool   `json:"outgoing"`
}
