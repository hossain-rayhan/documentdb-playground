#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
TELEMETRY_DIR="$REPO_ROOT/shared/telemetry"
ADAPTER="${BENCHMARK_ADAPTER:-mongoose}"
ADAPTER_SCRIPT="$SCRIPT_DIR/adapters/$ADAPTER.sh"
BENCHMARK_ID="${BENCHMARK_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$ADAPTER-$$}"
RESULTS_ROOT="${BENCHMARK_RESULTS_DIR:-$SCRIPT_DIR/results}"
RESULT_DIR="$RESULTS_ROOT/$BENCHMARK_ID"
BASELINE_RESULT="$RESULT_DIR/baseline.json"
TRACED_RESULT="$RESULT_DIR/traced.json"
ANALYSIS_RESULT="$RESULT_DIR/trace-analysis.json"
TRACE_CSV="$RESULT_DIR/trace-segments.csv"
SUMMARY_RESULT="$RESULT_DIR/summary.md"
EXPERIMENT_RESULT="$RESULT_DIR/experiment.json"

if [ ! -x "$ADAPTER_SCRIPT" ]; then
    echo "Unknown or non-executable benchmark adapter: $ADAPTER" >&2
    echo "Expected: $ADAPTER_SCRIPT" >&2
    exit 1
fi
for command_name in docker curl python3; do
    command -v "$command_name" >/dev/null || {
        echo "$command_name is required" >&2
        exit 1
    }
done
if [ -e "$RESULT_DIR" ]; then
    echo "Benchmark result directory already exists: $RESULT_DIR" >&2
    exit 1
fi
mkdir -p "$RESULT_DIR"

export BENCHMARK_ID
export BENCHMARK_OPERATIONS="${BENCHMARK_OPERATIONS:-1000}"
export BENCHMARK_WARMUP="${BENCHMARK_WARMUP:-50}"
export BENCHMARK_CONCURRENCY="${BENCHMARK_CONCURRENCY:-10}"
export BENCHMARK_QUERY_BYTES="${BENCHMARK_QUERY_BYTES:-16384}"
export BENCHMARK_WORKLOAD="${BENCHMARK_WORKLOAD:-large-read}"
export DOCUMENTDB_IMAGE="${DOCUMENTDB_IMAGE:-ghcr.io/documentdb/documentdb/documentdb-local:trace-4fbbfcb8}"
export OTEL_COLLECTOR_CONFIG_FILE="${OTEL_COLLECTOR_CONFIG_FILE:-./otel-collector-benchmark.yaml}"
export OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:${OTEL_COLLECTOR_GRPC_PORT:-4317}}"
export OTEL_SERVICE_NAME="${OTEL_SERVICE_NAME:-documentdb-benchmark-$ADAPTER}"

echo "Starting benchmark telemetry stack with $DOCUMENTDB_IMAGE"
"$TELEMETRY_DIR/scripts/up.sh"

run_phase() {
    local phase="$1"
    local tracing_enabled="$2"
    local result_file="$3"
    echo "Running $phase phase: operations=$BENCHMARK_OPERATIONS warmup=$BENCHMARK_WARMUP concurrency=$BENCHMARK_CONCURRENCY query_bytes=$BENCHMARK_QUERY_BYTES"
    BENCHMARK_PHASE="$phase" \
    BENCHMARK_RESULT_FILE="$result_file" \
    OTEL_TRACES_ENABLED="$tracing_enabled" \
        "$ADAPTER_SCRIPT"
}

run_phase baseline false "$BASELINE_RESULT"
run_phase traced true "$TRACED_RESULT"

python3 "$SCRIPT_DIR/analyze_jaeger.py" \
    --baseline "$BASELINE_RESULT" \
    --result "$TRACED_RESULT" \
    --output "$ANALYSIS_RESULT" \
    --csv "$TRACE_CSV" \
    --summary "$SUMMARY_RESULT" \
    --jaeger-url "${JAEGER_URL:-http://localhost:${JAEGER_UI_PORT:-16686}}"

IMAGE_ID="$(docker image inspect "$DOCUMENTDB_IMAGE" --format '{{.Id}}')"
IMAGE_CREATED="$(docker image inspect "$DOCUMENTDB_IMAGE" --format '{{.Created}}')"
python3 - \
    "$EXPERIMENT_RESULT" \
    "$BENCHMARK_ID" \
    "$ADAPTER" \
    "$DOCUMENTDB_IMAGE" \
    "$IMAGE_ID" \
    "$IMAGE_CREATED" \
    "$BASELINE_RESULT" \
    "$TRACED_RESULT" \
    "$ANALYSIS_RESULT" \
    "$TRACE_CSV" \
    "$SUMMARY_RESULT" <<'PY'
import json
import os
import sys
import tempfile

output, benchmark_id, adapter, image, image_id, image_created, baseline, traced, analysis, trace_csv, summary = sys.argv[1:]
value = {
    "schemaVersion": 1,
    "benchmarkId": benchmark_id,
    "adapter": adapter,
    "documentdbImage": {
        "name": image,
        "id": image_id,
        "created": image_created,
    },
    "artifacts": {
        "baseline": os.path.basename(baseline),
        "traced": os.path.basename(traced),
        "traceAnalysis": os.path.basename(analysis),
        "traceSegments": os.path.basename(trace_csv),
        "summary": os.path.basename(summary),
    },
}
directory = os.path.dirname(output)
descriptor, temporary = tempfile.mkstemp(prefix=".experiment-", dir=directory)
with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
    json.dump(value, handle, indent=2)
    handle.write("\n")
os.replace(temporary, output)
PY

echo ""
echo "Benchmark complete: $RESULT_DIR"
echo "  Baseline: $BASELINE_RESULT"
echo "  Traced:   $TRACED_RESULT"
echo "  Analysis: $ANALYSIS_RESULT"
echo "  CSV:      $TRACE_CSV"
echo "  Summary:  $SUMMARY_RESULT"