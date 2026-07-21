package client

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestCall_ErrorEnvelopeBecomesTypedAPIError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(409)
		io.WriteString(w, `{"error":"VersionConflict","message":"stale"}`)
	}))
	defer srv.Close()

	_, err := New(srv.URL).TaskDetail(1)
	var ae *APIError
	if !errors.As(err, &ae) {
		t.Fatalf("want *APIError, got %T (%v)", err, err)
	}
	if ae.Code != 409 || ae.Variant != "VersionConflict" || ae.Message != "stale" {
		t.Fatalf("bad envelope decode: %+v", ae)
	}
}

func TestCall_MessagelessEnvelopeSurfacesVariantFields(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(404)
		io.WriteString(w, `{"error":"NotFound","entity":"task","id":99999999}`)
	}))
	defer srv.Close()

	_, err := New(srv.URL).TaskDetail(99999999)
	var ae *APIError
	if !errors.As(err, &ae) {
		t.Fatalf("want *APIError, got %T", err)
	}
	// no "message" field → variant-specific fields land in Detail (sorted, integer-formatted)
	if ae.Variant != "NotFound" || ae.Detail != "entity=task, id=99999999" {
		t.Fatalf("bad parse: variant=%q detail=%q", ae.Variant, ae.Detail)
	}
	if got := ae.Error(); got != "NotFound: entity=task, id=99999999" {
		t.Fatalf("bad Error(): %q", got)
	}
}

func TestCall_TransportFailureBecomesConnError(t *testing.T) {
	// nothing listening on this port → dial refused
	_, err := New("http://127.0.0.1:1").ListWorkspaces()
	var ce *ConnError
	if !errors.As(err, &ce) {
		t.Fatalf("want *ConnError, got %T (%v)", err, err)
	}
}

func TestCreateTask_RoutesToSegmentAndOmitsNilFields(t *testing.T) {
	var gotPath string
	var gotBody map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		_ = json.NewDecoder(r.Body).Decode(&gotBody)
		io.WriteString(w, `{"id":5,"title":"t"}`)
	}))
	defer srv.Close()

	seg := int64(4)
	_, err := New(srv.URL).CreateTask(CreateTaskParams{Segment: &seg, Title: "t", Priority: 2})
	if err != nil {
		t.Fatal(err)
	}
	if gotPath != "/segments/4/tasks" {
		t.Fatalf("wrong route: %s", gotPath)
	}
	// title/description/priority always present; statusId/kindId omitted when nil
	if _, ok := gotBody["statusId"]; ok {
		t.Fatalf("statusId should be omitted: %v", gotBody)
	}
	if _, ok := gotBody["kindId"]; ok {
		t.Fatalf("kindId should be omitted: %v", gotBody)
	}
	if gotBody["title"] != "t" || gotBody["priority"] != float64(2) {
		t.Fatalf("bad body: %v", gotBody)
	}
}

func TestMoveStatus_Body(t *testing.T) {
	var gotBody map[string]any
	var gotPath string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		_ = json.NewDecoder(r.Body).Decode(&gotBody)
		io.WriteString(w, `{"id":7,"title":"T","version":3}`)
	}))
	defer srv.Close()

	if _, err := New(srv.URL).MoveStatus(7, 12, 2); err != nil {
		t.Fatal(err)
	}
	if gotPath != "/tasks/7/status" ||
		gotBody["toStatusId"] != float64(12) || gotBody["expectedVersion"] != float64(2) {
		t.Fatalf("bad move: %s %v", gotPath, gotBody)
	}
}

func TestEditTask_MergesVersionAndParsesResult(t *testing.T) {
	var gotBody map[string]any
	var gotMethod, gotPath string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotMethod, gotPath = r.Method, r.URL.Path
		_ = json.NewDecoder(r.Body).Decode(&gotBody)
		io.WriteString(w, `{"id":7,"title":"T","description":"d","priority":2,"version":9}`)
	}))
	defer srv.Close()

	task, err := New(srv.URL).EditTask(7, 8, map[string]any{"description": "d"})
	if err != nil {
		t.Fatal(err)
	}
	if gotMethod != "PATCH" || gotPath != "/tasks/7" {
		t.Fatalf("wrong request: %s %s", gotMethod, gotPath)
	}
	// expectedVersion is merged in; provided fields passed through
	if gotBody["expectedVersion"] != float64(8) || gotBody["description"] != "d" {
		t.Fatalf("bad body: %v", gotBody)
	}
	if task.ID != 7 || task.Version != 9 {
		t.Fatalf("bad parse: %+v", task)
	}
}
