#!/usr/bin/env bash
# Run the PyMongo demo API locally against a local DocumentDB container.
#
# Starts DocumentDB in Docker (if not already running), sets up the app's
# Python virtualenv/dependencies, then runs the Flask + PyMongo server.
#
# Prerequisites: docker, python3.
set -euo pipefail

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

APP_DIR="$SCRIPT_DIR/../app"
PORT="${PORT:-3000}"

ensure_documentdb

echo "Setting up Python virtualenv and installing dependencies..."
VENV_PY=$(setup_venv "$APP_DIR")

echo ""
echo "=== PyMongo demo API running locally ==="
echo "API:    http://localhost:${PORT}"
echo "Health: curl http://localhost:${PORT}/health"
echo "Create: curl -X POST http://localhost:${PORT}/books -H 'Content-Type: application/json' \\"
echo "          -d '{\"title\":\"Dune\",\"author\":\"Herbert\",\"genres\":[\"sci-fi\"],\"pages\":412}'"
echo "Press Ctrl-C to stop (DocumentDB keeps running; stop it with ./scripts/stop-documentdb.sh)."
echo ""

cd "$APP_DIR"
MONGO_URI="$(build_uri)" PORT="$PORT" "$VENV_PY" main.py
