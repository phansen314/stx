package cli

import (
	"encoding/json"
	"errors"
	"fmt"
	"sort"

	"github.com/phansen314/stx/internal/client"
	"github.com/spf13/cobra"
)

// metaTarget is the resolved read/write pair for a meta selector (task | workspace | track).
// The daemon has no per-key ops, so set/del are client-side RMW over the CAS edit_* methods.
type metaTarget struct {
	read  func() (blob string, version int, err error)
	write func(version int, blob string) error
}

// selector flags, shared across the meta subcommands (persistent on the parent).
var (
	metaTask  int64
	metaWs    string
	metaTrack string
)

func resolveMetaTarget(c *client.Client) (metaTarget, error) {
	hasTask := metaTask != 0
	hasWs := metaWs != ""
	if hasTask == hasWs {
		return metaTarget{}, errors.New("pass exactly one target: --task <id> or -w <workspace>")
	}
	if metaTrack != "" && !hasWs {
		return metaTarget{}, errors.New("--track requires -w <workspace>")
	}

	if hasTask {
		id := metaTask
		return metaTarget{
			read: func() (string, int, error) {
				d, err := c.TaskDetail(id)
				return d.Task.MetadataJSON, d.Task.Version, err
			},
			write: func(v int, blob string) error {
				_, err := c.EditTask(id, v, map[string]any{"metadataJson": blob})
				return err
			},
		}, nil
	}

	ws, err := resolveWorkspace(c, metaWs)
	if err != nil {
		return metaTarget{}, err
	}
	if metaTrack != "" {
		tr, err := resolveTrack(c, ws.ID, metaTrack)
		if err != nil {
			return metaTarget{}, err
		}
		trID := tr.ID
		return metaTarget{
			read: func() (string, int, error) {
				t, err := resolveTrack(c, ws.ID, metaTrack) // re-read for fresh version
				return t.MetadataJSON, t.Version, err
			},
			write: func(v int, blob string) error {
				_, err := c.EditTrack(trID, v, map[string]any{"metadataJson": blob})
				return err
			},
		}, nil
	}
	return metaTarget{
		read: func() (string, int, error) {
			w, err := resolveWorkspace(c, metaWs)
			return w.MetadataJSON, w.Version, err
		},
		write: func(v int, blob string) error {
			_, err := c.EditWorkspace(ws.ID, v, map[string]any{"metadataJson": blob})
			return err
		},
	}, nil
}

// metaLoad parses the blob into a JSON object (mirror _meta_load).
func metaLoad(blob string) (map[string]any, error) {
	if blob == "" {
		blob = "{}"
	}
	var v any
	if err := json.Unmarshal([]byte(blob), &v); err != nil {
		return nil, errors.New("metadata is not a JSON object")
	}
	m, ok := v.(map[string]any)
	if !ok {
		return nil, errors.New("metadata is not a JSON object")
	}
	return m, nil
}

// parseMetaValue parses a `set` value as JSON, falling back to the raw string (mirror _parse_value);
// --string forces the literal string.
func parseMetaValue(s string, forceString bool) any {
	if forceString {
		return s
	}
	var v any
	if err := json.Unmarshal([]byte(s), &v); err == nil {
		return v
	}
	return s
}

// metaRMW: read blob → mutate(dict) in place → write, with one CAS retry on VersionConflict.
func metaRMW(t metaTarget, mutate func(map[string]any)) error {
	attempt := func() error {
		blob, ver, err := t.read()
		if err != nil {
			return err
		}
		d, err := metaLoad(blob)
		if err != nil {
			return err
		}
		mutate(d)
		js, err := json.Marshal(d)
		if err != nil {
			return err
		}
		return t.write(ver, string(js))
	}
	err := attempt()
	var ae *client.APIError
	if err != nil && errors.As(err, &ae) && ae.Variant == "VersionConflict" {
		return attempt()
	}
	return err
}

// editMetaValue opens a key's current value in the editor. Two modes, matching how the value will
// be read back: --string edits the raw text in a .md buffer (the sane way to write a long note),
// everything else edits pretty-printed JSON in a .json buffer. A key that isn't set yet starts
// empty, and a non-string value under --string starts from its JSON form rather than nothing.
func editMetaValue(cmd *cobra.Command, t metaTarget, key string, asString bool) (editedBuffer, error) {
	blob, _, err := t.read()
	if err != nil {
		return editedBuffer{}, err
	}
	d, err := metaLoad(blob)
	if err != nil {
		return editedBuffer{}, err
	}
	seed, ext := "", ".json"
	if asString {
		ext = ".md"
	}
	if v, ok := d[key]; ok {
		if s, isStr := v.(string); isStr && asString {
			seed = s
		} else {
			js, _ := json.MarshalIndent(v, "", "  ")
			seed = string(js)
		}
	}
	return editBuffer(cmd, "meta-"+key, ext, seed)
}

// metaKeys is the sorted key list — the `-q` view of `meta ls`.
func metaKeys(d map[string]any) []string {
	keys := make([]string, 0, len(d))
	for k := range d {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

// bareValue renders a metadata value for `-q`: a string unquoted (so `$(stx meta get … -q)` is the
// string itself, not `"the string"`), anything else as compact JSON.
func bareValue(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	js, _ := json.Marshal(v)
	return string(js)
}

// renderMeta mirrors render.meta: "k = <json value>" per key (sorted), or "(no metadata)".
func renderMeta(d map[string]any) string {
	if len(d) == 0 {
		return "(no metadata)"
	}
	keys := make([]string, 0, len(d))
	for k := range d {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	lines := make([]string, 0, len(keys))
	for _, k := range keys {
		v, _ := json.Marshal(d[k])
		lines = append(lines, fmt.Sprintf("%s = %s", k, string(v)))
	}
	return joinLines(lines)
}

func newMetaCmd() *cobra.Command {
	meta := &cobra.Command{
		Use:   "meta",
		Short: "get/set/delete an entity's metadata keys",
	}
	meta.PersistentFlags().Int64Var(&metaTask, "task", 0, "target task id")
	meta.PersistentFlags().StringVarP(&metaWs, "workspace", "w", "", "target workspace name or id")
	meta.PersistentFlags().StringVar(&metaTrack, "track", "", "target track (requires -w)")

	ls := &cobra.Command{
		Use: "ls", Short: "list metadata keys", Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, _ []string) error {
			c, err := dial()
			if err != nil {
				return err
			}
			t, err := resolveMetaTarget(c)
			if err != nil {
				return err
			}
			blob, _, err := t.read()
			if err != nil {
				return err
			}
			d, err := metaLoad(blob)
			if err != nil {
				return err
			}
			if len(d) == 0 {
				markEmpty()
			}
			return emitLines(cmd, metaKeys(d), d, renderMeta(d)) // -q lists the keys
		},
	}

	get := &cobra.Command{
		Use: "get <key>", Short: "get one metadata key", Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			c, err := dial()
			if err != nil {
				return err
			}
			t, err := resolveMetaTarget(c)
			if err != nil {
				return err
			}
			blob, _, err := t.read()
			if err != nil {
				return err
			}
			d, err := metaLoad(blob)
			if err != nil {
				return err
			}
			v, ok := d[args[0]]
			if !ok {
				return fmt.Errorf("no metadata key '%s'", args[0])
			}
			one := map[string]any{args[0]: v}
			// -q is the "give me the value for my script" mode: bare, unquoted for strings.
			return emitLines(cmd, []string{bareValue(v)}, one, renderMeta(one))
		},
	}

	var stringFlag, setEditor bool
	set := &cobra.Command{
		Use:   "set <key> <value|->",
		Short: "set a metadata key (value parsed as JSON; `-` reads stdin, `-e` opens $EDITOR)",
		Args:  cobra.RangeArgs(1, 2),
		RunE: func(cmd *cobra.Command, args []string) error {
			if setEditor == (len(args) == 2) {
				return errors.New("pass either a value or -e/--editor, not both")
			}
			c, err := dial()
			if err != nil {
				return err
			}
			t, err := resolveMetaTarget(c)
			if err != nil {
				return err
			}
			key := args[0]

			var raw string
			var buf editedBuffer
			if setEditor {
				if buf, err = editMetaValue(cmd, t, key, stringFlag); err != nil {
					return err
				}
				if !buf.changed {
					return emitLines(cmd, nil, map[string]any{key: nil}, "unchanged "+key)
				}
				raw = buf.text
			} else if raw, err = readValue(cmd, args[1], "<value>"); err != nil {
				return err
			}

			// A typed value falls back to a string when it isn't JSON; an editor buffer doesn't —
			// silently turning a JSON typo into one long string would be a nasty surprise.
			var value any
			if setEditor && !stringFlag {
				if err := json.Unmarshal([]byte(raw), &value); err != nil {
					return fmt.Errorf("not valid JSON: %w%s (use --string for a literal)", err, buf.keep())
				}
			} else {
				value = parseMetaValue(raw, stringFlag)
			}
			if err := metaRMW(t, func(d map[string]any) { d[key] = value }); err != nil {
				return fmt.Errorf("%w%s", err, buf.keep())
			}
			buf.discard()
			js, _ := json.Marshal(value)
			return emitLines(cmd, []string{bareValue(value)}, map[string]any{key: value},
				fmt.Sprintf("%s = %s", key, string(js)))
		},
	}
	set.Flags().BoolVar(&stringFlag, "string", false, "store the value as a literal string")
	set.Flags().BoolVarP(&setEditor, "editor", "e", false, "edit the value in $EDITOR")

	del := &cobra.Command{
		Use: "del <key>", Short: "delete a metadata key", Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			c, err := dial()
			if err != nil {
				return err
			}
			t, err := resolveMetaTarget(c)
			if err != nil {
				return err
			}
			key := args[0]
			blob, _, err := t.read()
			if err != nil {
				return err
			}
			d, err := metaLoad(blob)
			if err != nil {
				return err
			}
			if _, ok := d[key]; !ok {
				return fmt.Errorf("no metadata key '%s'", key)
			}
			if err := metaRMW(t, func(d map[string]any) { delete(d, key) }); err != nil {
				return err
			}
			return emitLines(cmd, []string{key}, map[string]any{"deleted": key}, "deleted "+key)
		},
	}

	meta.AddCommand(ls, get, set, del)
	return meta
}
