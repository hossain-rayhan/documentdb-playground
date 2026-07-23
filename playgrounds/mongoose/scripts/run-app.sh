#!/usr/bin/env bash
# Run the Mongoose demo API locally against a local DocumentDB container.
#
# Starts DocumentDB in Docker (if not already running), installs the app's
# Node dependencies, then runs the Express + Mongoose server on your machine.
#
# Prerequisites: docker, node, npm.
set -euo pipefail

command -v node >/dev/null || { echo "node is required" >&2; exit 1; }
command -v npm >/dev/null || { echo "npm is required" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

APP_DIR="$SCRIPT_DIR/../app"
PORT="${PORT:-3000}"

ensure_documentdb

echo "Installing app dependencies (express, mongoose)..."
(cd "$APP_DIR" && npm install --omit=dev --no-audit --no-fund >/dev/null)

echo ""
echo "=== Mongoose demo API running locally ==="
echo "API:    http://localhost:${PORT}"
echo "Health: curl http://localhost:${PORT}/health"
echo "Create: curl -X POST http://localhost:${PORT}/books -H 'Content-Type: application/json' \\"
echo "          -d '{\"title\":\"Dune\",\"author\":\"Herbert\",\"genres\":[\"sci-fi\"],\"pages\":412}'"
echo "Press Ctrl-C to stop (DocumentDB keeps running; stop it with ./scripts/stop-documentdb.sh)."
echo ""

MONGO_URI="$(build_uri)" PORT="$PORT" node "$APP_DIR/server.js"
