// Package client is the stx daemon wire client — the Go equivalent of Python's stxc.
//
// One core method (call) does HTTP + JSON + the {error,message} envelope; typed errors
// (APIError, ConnError) let callers match on the daemon's error variant (e.g. the CAS
// retry keys on VersionConflict). Endpoint methods live in reads.go / writes.go.
package client

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"sort"
	"strings"
	"time"
)

// DefaultBaseURL matches the daemon's loopback binding.
const DefaultBaseURL = "http://127.0.0.1:8420"

// Client talks to the daemon over loopback HTTP.
type Client struct {
	base string
	http *http.Client
}

// New builds a client for base (trailing slash trimmed).
func New(base string) *Client {
	for len(base) > 0 && base[len(base)-1] == '/' {
		base = base[:len(base)-1]
	}
	return &Client{base: base, http: &http.Client{Timeout: 15 * time.Second}}
}

// APIError is a non-2xx response carrying the daemon's error envelope
// ({error: <variant>, ...variant-specific fields}; no fixed `message` key). Variant-specific
// fields (e.g. entity/id on NotFound) land in Detail so they aren't lost.
type APIError struct {
	Code    int
	Variant string
	Message string // the "message" field, when the variant carries one (e.g. VersionConflict)
	Detail  string // other variant-specific fields, rendered "k=v, k=v" (sorted)
}

func (e *APIError) Error() string {
	switch {
	case e.Message != "":
		return e.Variant + ": " + e.Message
	case e.Detail != "":
		return e.Variant + ": " + e.Detail
	default:
		return e.Variant
	}
}

// parseAPIError decodes the daemon error envelope. UseNumber keeps ids as integers (not float
// scientific notation) when rendered into Detail.
func parseAPIError(code int, body []byte) *APIError {
	ae := &APIError{Code: code}
	var env map[string]any
	dec := json.NewDecoder(bytes.NewReader(body))
	dec.UseNumber()
	if err := dec.Decode(&env); err != nil || env == nil {
		ae.Variant = fmt.Sprintf("HTTP%d", code)
		return ae
	}
	if v, ok := env["error"].(string); ok {
		ae.Variant = v
	} else {
		ae.Variant = fmt.Sprintf("HTTP%d", code)
	}
	if m, ok := env["message"].(string); ok {
		ae.Message = m
	}
	keys := make([]string, 0, len(env))
	for k := range env {
		if k != "error" && k != "message" {
			keys = append(keys, k)
		}
	}
	sort.Strings(keys)
	parts := make([]string, 0, len(keys))
	for _, k := range keys {
		parts = append(parts, fmt.Sprintf("%s=%v", k, env[k]))
	}
	ae.Detail = strings.Join(parts, ", ")
	return ae
}

// ConnError wraps a transport failure (daemon down / reset / timeout).
type ConnError struct{ Err error }

func (e *ConnError) Error() string { return fmt.Sprintf("daemon request failed: %v", e.Err) }
func (e *ConnError) Unwrap() error { return e.Err }

// call performs one request. body (if non-nil) is JSON-encoded; on 2xx the response is
// decoded into out (if non-nil); non-2xx yields *APIError, transport failure *ConnError.
func (c *Client) call(method, path string, body, out any) error {
	var rdr io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return err
		}
		rdr = bytes.NewReader(b)
	}
	req, err := http.NewRequest(method, c.base+path, rdr)
	if err != nil {
		return err
	}
	req.Header.Set("content-type", "application/json")
	resp, err := c.http.Do(req)
	if err != nil {
		return &ConnError{Err: err}
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return &ConnError{Err: err}
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return parseAPIError(resp.StatusCode, data)
	}
	if out != nil {
		return json.Unmarshal(data, out)
	}
	return nil
}

// Ping reports whether the daemon answers /health.
func (c *Client) Ping() bool {
	resp, err := c.http.Get(c.base + "/health")
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	return resp.StatusCode == 200
}
