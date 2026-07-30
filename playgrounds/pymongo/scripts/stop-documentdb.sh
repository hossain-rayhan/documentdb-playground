#!/usr/bin/env bash
# Stop and remove the DocumentDB local emulator container.
#
# This removes the container and all data it held (the emulator stores data
# inside the container, so this is a full reset).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

stop_documentdb
