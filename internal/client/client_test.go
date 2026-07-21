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

func TestCall_TransportFailureBecomesConnError(t *testing.T) {
	// nothing listening on this port → dial refused
	_, err := New("http://127.0.0.1:1").ListWorkspaces()
	var ce *ConnError
	if !errors.As(err, &ce) {
		t.Fatalf("want *ConnError, got %T (%v)", err, err)
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
