#!/usr/bin/env bash
# Start the DocumentDB local emulator in Docker on your machine.
#
# Idempotent: if the container is already running, this just verifies readiness.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

ensure_documentdb

echo ""
echo "=== DocumentDB local emulator is ready ==="
echo "Container: $DOCUMENTDB_CONTAINER  (image: $DOCUMENTDB_IMAGE)"
echo "Connection string:"
echo "  $(build_uri)"
echo ""
echo "Next:"
echo "  ./scripts/run-test.sh          # start DocumentDB if needed, then run tests"
echo "  ./scripts/run-app.sh           # start DocumentDB if needed, then run API"
echo "  ./scripts/stop-documentdb.sh   # stop + remove the emulator"
