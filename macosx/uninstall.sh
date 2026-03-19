#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${HOME}/.local/lib/sticky-notes-mcp"
PLIST_DIR="${HOME}/Library/LaunchAgents"
LOG_DIR="${HOME}/Library/Logs/sticky-notes-mcp"

echo "Stopping MCP server agent..."
launchctl bootout "gui/$(id -u)/com.codingzen.sticky-notes-mcp" 2>/dev/null || true

echo "Removing plist..."
rm -f "${PLIST_DIR}/com.codingzen.sticky-notes-mcp.plist"

echo "Removing installed files..."
rm -rf "${INSTALL_DIR}"

echo "Removing log directory..."
rm -rf "${LOG_DIR}"

echo "Uninstall complete."
