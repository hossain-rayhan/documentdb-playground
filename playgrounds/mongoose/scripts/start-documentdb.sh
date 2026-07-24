#!/usr/bin/env bash
# Start a local DocumentDB instance in Docker and wait until it is ready.
#
# Idempotent: if the container is already running it just verifies readiness.
# Configure credentials/port via the env vars documented in lib.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

ensure_documentdb

echo ""
echo "DocumentDB is running locally."
echo "  Connection string: $(build_uri)"
echo "  Stop it with:      ./scripts/stop-documentdb.sh"
