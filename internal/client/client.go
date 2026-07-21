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

// APIError is a non-2xx response carrying the daemon's error envelope.
type APIError struct {
	Code    int
	Variant string `json:"error"`
	Message string `json:"message"`
}

func (e *APIError) Error() string {
	if e.Message == "" {
		return e.Variant
	}
	return fmt.Sprintf("%s: %s", e.Variant, e.Message)
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
		ae := &APIError{Code: resp.StatusCode}
		_ = json.Unmarshal(data, ae) // best-effort; leaves Variant/Message empty on non-JSON
		if ae.Variant == "" {
			ae.Variant = fmt.Sprintf("HTTP%d", resp.StatusCode)
		}
		return ae
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
