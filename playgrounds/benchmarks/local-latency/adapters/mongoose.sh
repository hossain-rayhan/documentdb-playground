#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLAYGROUND_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
MONGOOSE_DIR="$PLAYGROUND_ROOT/mongoose"

for command_name in node npm; do
    command -v "$command_name" >/dev/null || {
        echo "$command_name is required by the Mongoose benchmark adapter" >&2
        exit 1
    }
done

for variable_name in \
    BENCHMARK_ID \
    BENCHMARK_PHASE \
    BENCHMARK_RESULT_FILE; do
    if [ -z "${!variable_name:-}" ]; then
        echo "$variable_name is required by the Mongoose benchmark adapter" >&2
        exit 1
    fi
done

# shellcheck source=../../mongoose/scripts/lib.sh
source "$MONGOOSE_DIR/scripts/lib.sh"

if [ -z "${MONGO_URI:-}" ]; then
    MONGO_URI="$(build_uri)"
    export MONGO_URI
fi
export MONGO_DB="${MONGO_DB:-mongoose_benchmark}"

(cd "$MONGOOSE_DIR/app" && npm install --omit=dev --no-audit --no-fund >/dev/null)
exec node "$MONGOOSE_DIR/app/benchmark.js"