#!/usr/bin/env bash
# Uninstall the sticky-notes MCP server (systemd on Linux, launchd on macOS).
# Idempotent — safe to run if MCP was never installed.
set -euo pipefail

OS="$(uname -s)"

echo "=== Sticky Notes MCP Uninstall ==="

# ---- Linux (systemd) ----
if [[ "$OS" == "Linux" ]]; then
    SERVICE="sticky-notes-mcp"
    UNIT_FILE="${HOME}/.config/systemd/user/${SERVICE}.service"

    if systemctl --user is-active --quiet "$SERVICE" 2>/dev/null; then
        echo "Stopping and disabling ${SERVICE}..."
        systemctl --user disable --now "$SERVICE"
    else
        echo "Service ${SERVICE} not running."
    fi

    if [[ -f "$UNIT_FILE" ]]; then
        echo "Removing ${UNIT_FILE}..."
        rm -f "$UNIT_FILE"
        systemctl --user daemon-reload
    fi
fi

# ---- macOS (launchd) ----
if [[ "$OS" == "Darwin" ]]; then
    LABEL="com.codingzen.sticky-notes-mcp"
    GUI_UID="gui/$(id -u)"
    PLIST_DIR="${HOME}/Library/LaunchAgents"
    INSTALL_DIR="${HOME}/.local/lib/sticky-notes-mcp"
    LOG_DIR="${HOME}/Library/Logs/sticky-notes-mcp"

    echo "Stopping MCP server agent..."
    launchctl bootout "${GUI_UID}/${LABEL}" 2>/dev/null || true

    if [[ -f "${PLIST_DIR}/${LABEL}.plist" ]]; then
        echo "Removing plist..."
        rm -f "${PLIST_DIR}/${LABEL}.plist"
    fi

    if [[ -d "$INSTALL_DIR" ]]; then
        echo "Removing installed files..."
        rm -rf "$INSTALL_DIR"
    fi

    if [[ -d "$LOG_DIR" ]]; then
        echo "Removing log directory..."
        rm -rf "$LOG_DIR"
    fi
fi

# ---- Claude Code MCP config ----
CLAUDE_JSON="${HOME}/.claude/claude.json"
if [[ -f "$CLAUDE_JSON" ]] && command -v python3 &>/dev/null; then
    if python3 -c "import json; d=json.load(open('$CLAUDE_JSON')); exit(0 if 'sticky-notes' in d.get('mcpServers',{}) else 1)" 2>/dev/null; then
        echo "Removing sticky-notes from ${CLAUDE_JSON}..."
        python3 -c "
import json, pathlib
p = pathlib.Path('$CLAUDE_JSON')
d = json.loads(p.read_text())
d.get('mcpServers', {}).pop('sticky-notes', None)
p.write_text(json.dumps(d, indent=2) + '\n')
"
    fi
fi

echo ""
echo "Done. To remove the sticky-notes-mcp binary, reinstall the package:"
echo "  pip install -e .    # from the sticky-notes repo root"
echo ""
echo "The sticky-notes database is preserved at:"
echo "  ~/.local/share/sticky-notes/sticky-notes.db"
