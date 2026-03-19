#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${HOME}/.local/lib/sticky-notes-mcp"
PLIST_DIR="${HOME}/Library/LaunchAgents"
LOG_DIR="${HOME}/Library/Logs/sticky-notes-mcp"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

STICKY_NOTES_MCP_BIN="$(command -v sticky-notes-mcp || true)"
if [[ -z "${STICKY_NOTES_MCP_BIN}" ]]; then
    echo "Error: sticky-notes-mcp not found on PATH" >&2
    echo "Install it first: pip install --user ." >&2
    exit 1
fi
echo "Using sticky-notes-mcp: ${STICKY_NOTES_MCP_BIN}"

# Install launcher script with binary path substituted
echo "Installing launcher script to ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}"
sed -e "s|@STICKY_NOTES_MCP_BIN@|${STICKY_NOTES_MCP_BIN}|g" \
    "${SCRIPT_DIR}/sticky-notes-mcp-launcher.sh" \
    > "${INSTALL_DIR}/sticky-notes-mcp-launcher.sh"
chmod +x "${INSTALL_DIR}/sticky-notes-mcp-launcher.sh"

# Install LaunchAgent plist
echo "Installing LaunchAgent plist..."
mkdir -p "${PLIST_DIR}"
mkdir -p "${LOG_DIR}"

sed -e "s|@INSTALL_DIR@|${INSTALL_DIR}|g" \
    -e "s|@LOG_DIR@|${LOG_DIR}|g" \
    "${SCRIPT_DIR}/com.codingzen.sticky-notes-mcp.plist" \
    > "${PLIST_DIR}/com.codingzen.sticky-notes-mcp.plist"

# Unload existing agent if present
GUI_UID="gui/$(id -u)"
launchctl bootout "${GUI_UID}/com.codingzen.sticky-notes-mcp" 2>/dev/null || true

# Load agent
launchctl bootstrap "${GUI_UID}" "${PLIST_DIR}/com.codingzen.sticky-notes-mcp.plist"

echo ""
echo "Done. Verify with:"
echo "  launchctl print ${GUI_UID}/com.codingzen.sticky-notes-mcp"
