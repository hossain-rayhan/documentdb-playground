#!/usr/bin/env python3

import argparse
import csv
import json
import math
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


def percentile(values, percentage):
    ordered = sorted(values)
    if not ordered:
        return None
    index = max(0, math.ceil(percentage / 100 * len(ordered)) - 1)
    return ordered[index]


def summarize(values):
    if not values:
        return None
    return {
        "count": len(values),
        "minimum": min(values),
        "mean": sum(values) / len(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "maximum": max(values),
    }


def interval_union_duration(intervals):
    if not intervals:
        return 0
    ordered = sorted(intervals)
    start, end = ordered[0]
    total = 0
    for next_start, next_end in ordered[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            total += end - start
            start, end = next_start, next_end
    return total + end - start


def tags(span):
    return {tag.get("key"): tag.get("value") for tag in span.get("tags", [])}


def child_of(span, parent_span_id):
    return any(
        reference.get("refType") == "CHILD_OF"
        and reference.get("spanID") == parent_span_id
        for reference in span.get("references", [])
    )


def is_descendant(span, ancestor_span_id, spans_by_id, max_depth=64):
    # Walk CHILD_OF links up to the selected gateway so sibling branches
    # (retries, multi-command traces) are not mixed into the metrics.
    current = span
    seen = set()
    for _ in range(max_depth):
        parent_id = next(
            (
                reference.get("spanID")
                for reference in current.get("references", [])
                if reference.get("refType") == "CHILD_OF"
            ),
            None,
        )
        if parent_id is None or parent_id in seen:
            return False
        if parent_id == ancestor_span_id:
            return True
        seen.add(parent_id)
        current = spans_by_id.get(parent_id)
        if current is None:
            return False
    return False


def complete_trace_count(traces, result, service_name, gateway_service):
    count = 0
    for trace in traces:
        processes = trace.get("processes", {})

        def service(span):
            return processes.get(span.get("processID"), {}).get("serviceName")

        spans = trace.get("spans", [])
        application = next(
            (
                span
                for span in spans
                if service(span) == service_name
                and tags(span).get("benchmark.id") == result["benchmarkId"]
                and tags(span).get("benchmark.phase") == "traced"
                and result["measurementStartUs"]
                <= int(span.get("startTime", 0))
                <= result["measurementEndUs"]
            ),
            None,
        )
        if application is None:
            continue
        gateway = next(
            (
                span
                for span in spans
                if service(span) == gateway_service
                and span.get("operationName") == "gateway.request"
                and child_of(span, application.get("spanID"))
            ),
            None,
        )
        if gateway is None:
            continue
        spans_by_id = {span.get("spanID"): span for span in spans}
        if any(
            service(span) == gateway_service
            and span.get("operationName") == "postgres.execute"
            and is_descendant(span, gateway.get("spanID"), spans_by_id)
            for span in spans
        ):
            count += 1
    return count


def write_json_atomic(file_name, value):
    directory = os.path.dirname(os.path.abspath(file_name))
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".analysis-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2)
            handle.write("\n")
        os.replace(temporary, file_name)
    except Exception:
        os.unlink(temporary)
        raise


def write_text_atomic(file_name, value):
    directory = os.path.dirname(os.path.abspath(file_name))
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".summary-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
        os.replace(temporary, file_name)
    except Exception:
        os.unlink(temporary)
        raise


def build_markdown_summary(baseline, traced, analysis):
    def client_row(label, value):
        latency = value["latencyMs"]
        return (
            f"| {label} | {value['throughputOperationsPerSecond']:.1f} | "
            f"{latency['mean']:.3f} | {latency['p50']:.3f} | "
            f"{latency['p95']:.3f} | {latency['p99']:.3f} | "
            f"{latency['maximum']:.3f} |"
        )

    segment_labels = {
        "client_total_ms": "Full client operation",
        "client_outside_gateway_ms": "Client/driver/transport outside gateway",
        "gateway_total_ms": "Gateway total",
        "postgres_union_ms": "PostgreSQL interval union",
        "gateway_residual_ms": "Gateway excluding PostgreSQL",
    }
    hop_rows = []
    for segment_name, label in segment_labels.items():
        segment = analysis["segments"][segment_name]
        hop_rows.append(
            f"| {label} | {segment['mean']:.3f} | {segment['p50']:.3f} | "
            f"{segment['p95']:.3f} | {segment['p99']:.3f} | "
            f"{segment['maximum']:.3f} |"
        )

    traces = analysis["representativeTraces"]
    return "\n".join(
        [
            f"# Benchmark summary: {traced['benchmarkId']}",
            "",
            f"- Adapter: `{traced['adapter']}`",
            f"- Workload: `{traced['workload']}`",
            f"- Operations per phase: `{traced['measuredOperations']}`",
            f"- Warm-up operations per phase: `{traced['warmupOperations']}`",
            f"- Concurrency: `{traced['concurrency']}`",
            f"- Query BSON size: `{traced['actualQueryBytes']}` bytes",
            f"- Connected traces: `{analysis['completeTraceCount']}/{analysis['returnedTraceCount']}`",
            "",
            "> [!IMPORTANT]",
            "> Exact one-way client-to-gateway latency is not available because the client and gateway use different wall clocks. `Client/driver/transport outside gateway` is clock-robust, but combines client processing, pool wait, serialization, TLS, both network directions, and response decoding.",
            "",
            "## Client results",
            "",
            "| Phase | Throughput (ops/s) | Mean (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Max (ms) |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            client_row("Baseline", baseline),
            client_row("Traced", traced),
            "",
            "## Latency by hop",
            "",
            "| Segment | Mean (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Max (ms) |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
            *hop_rows,
            "",
            "## Representative traces",
            "",
            f"- [Median trace]({traces['median']})",
            f"- [p99 trace]({traces['p99']})",
            "",
        ]
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True, help="Baseline adapter result JSON")
    parser.add_argument("--result", required=True, help="Traced adapter result JSON")
    parser.add_argument("--output", required=True, help="Analysis JSON output")
    parser.add_argument("--csv", required=True, help="Per-trace CSV output")
    parser.add_argument("--summary", required=True, help="Markdown summary output")
    parser.add_argument("--jaeger-url", default="http://localhost:16686")
    parser.add_argument("--gateway-service", default="documentdb_gateway")
    parser.add_argument("--search-attempts", type=int, default=15)
    parser.add_argument("--search-delay", type=float, default=1.0)
    args = parser.parse_args()

    with open(args.baseline, encoding="utf-8") as handle:
        baseline = json.load(handle)
    with open(args.result, encoding="utf-8") as handle:
        result = json.load(handle)
    service_name = result.get("telemetry", {}).get("serviceName")
    if not service_name:
        raise SystemExit("Adapter result does not contain telemetry.serviceName")

    query = urllib.parse.urlencode(
        {
            "service": service_name,
            "start": result["measurementStartUs"],
            "end": result["measurementEndUs"] + 5_000_000,
            "limit": max(100, result["measuredOperations"] * 2),
        }
    )
    traces = []
    for attempt in range(args.search_attempts):
        try:
            with urllib.request.urlopen(
                f"{args.jaeger_url}/api/traces?{query}", timeout=15
            ) as response:
                traces = json.load(response).get("data", [])
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == args.search_attempts - 1:
                raise SystemExit(
                    f"Could not query Jaeger at {args.jaeger_url}: {error}"
                )
        if complete_trace_count(
            traces, result, service_name, args.gateway_service
        ) >= result["successfulOperations"]:
            break
        if attempt < args.search_attempts - 1:
            time.sleep(args.search_delay)

    excluded = {
        "missing_application_span": 0,
        "outside_measurement_window": 0,
        "missing_gateway_span": 0,
        "missing_postgres_span": 0,
        "unexpected_parent_relationship": 0,
        "negative_derived_duration": 0,
    }
    rows = []
    response_boundary_clock_skew = []
    for trace in traces:
        processes = trace.get("processes", {})

        def service(span):
            return processes.get(span.get("processID"), {}).get("serviceName")

        spans = trace.get("spans", [])
        application = next(
            (
                span
                for span in spans
                if service(span) == service_name
                and tags(span).get("benchmark.id") == result["benchmarkId"]
                and tags(span).get("benchmark.phase") == "traced"
            ),
            None,
        )
        if application is None:
            excluded["missing_application_span"] += 1
            continue
        if not (
            result["measurementStartUs"]
            <= int(application.get("startTime", 0))
            <= result["measurementEndUs"]
        ):
            excluded["outside_measurement_window"] += 1
            continue
        gateway = next(
            (
                span
                for span in spans
                if service(span) == args.gateway_service
                and span.get("operationName") == "gateway.request"
            ),
            None,
        )
        if gateway is None:
            excluded["missing_gateway_span"] += 1
            continue
        if not child_of(gateway, application.get("spanID")):
            excluded["unexpected_parent_relationship"] += 1
            continue
        spans_by_id = {span.get("spanID"): span for span in spans}
        postgres = [
            span
            for span in spans
            if service(span) == args.gateway_service
            and span.get("operationName") == "postgres.execute"
            and is_descendant(span, gateway.get("spanID"), spans_by_id)
        ]
        if not postgres:
            excluded["missing_postgres_span"] += 1
            continue

        client_total = int(application["duration"])
        gateway_total = int(gateway["duration"])
        postgres_sum = sum(int(span["duration"]) for span in postgres)
        postgres_union = interval_union_duration(
            [
                (
                    int(span["startTime"]),
                    int(span["startTime"]) + int(span["duration"]),
                )
                for span in postgres
            ]
        )
        row = {
            "trace_id": trace.get("traceID"),
            "client_total_ms": client_total / 1000,
            "client_outside_gateway_ms": (client_total - gateway_total) / 1000,
            "gateway_total_ms": gateway_total / 1000,
            "postgres_sum_ms": postgres_sum / 1000,
            "postgres_union_ms": postgres_union / 1000,
            "gateway_residual_ms": (gateway_total - postgres_union) / 1000,
        }
        if any(value < 0 for key, value in row.items() if key.endswith("_ms")):
            excluded["negative_derived_duration"] += 1
            continue

        response_return = (
            int(application["startTime"])
            + client_total
            - int(gateway["startTime"])
            - gateway_total
        )
        if response_return < 0:
            response_boundary_clock_skew.append(response_return)
        rows.append(row)

    if not rows:
        raise SystemExit(
            "No complete connected benchmark traces found; "
            f"excluded={json.dumps(excluded, sort_keys=True)}"
        )
    if len(rows) < result["successfulOperations"]:
        raise SystemExit(
            "Incomplete connected benchmark traces after waiting for Jaeger; "
            f"expected={result['successfulOperations']} complete={len(rows)} "
            f"excluded={json.dumps(excluded, sort_keys=True)}"
        )

    segment_names = [
        "client_total_ms",
        "client_outside_gateway_ms",
        "gateway_total_ms",
        "postgres_sum_ms",
        "postgres_union_ms",
        "gateway_residual_ms",
    ]
    summaries = {
        name: summarize([row[name] for row in rows]) for name in segment_names
    }
    ordered = sorted(rows, key=lambda row: row["client_total_ms"])
    median_row = ordered[max(0, math.ceil(0.50 * len(ordered)) - 1)]
    p99_row = ordered[max(0, math.ceil(0.99 * len(ordered)) - 1)]
    analysis = {
        "schemaVersion": 1,
        "benchmarkId": result["benchmarkId"],
        "adapter": result["adapter"],
        "jaegerUrl": args.jaeger_url,
        "returnedTraceCount": len(traces),
        "completeTraceCount": len(rows),
        "excluded": excluded,
        "clockSkew": {
            "negativeResponseBoundaryCount": len(response_boundary_clock_skew),
            "minimumResponseBoundaryUs": min(response_boundary_clock_skew, default=0),
            "note": "Cross-process timestamps cannot reliably split request and response transport. Use client_outside_gateway_ms.",
        },
        "measurementScope": {
            "oneWayClientToGatewayAvailable": False,
            "clientOutsideGatewayIncludes": [
                "client processing",
                "connection pool wait",
                "serialization",
                "TLS",
                "client-to-gateway transport",
                "gateway-to-client transport",
                "response decoding",
            ],
            "note": "Client and gateway wall clocks are not synchronized; use client_outside_gateway_ms as the clock-robust combined measurement.",
        },
        "segments": summaries,
        "representativeTraces": {
            "median": f"{args.jaeger_url}/trace/{median_row['trace_id']}",
            "p99": f"{args.jaeger_url}/trace/{p99_row['trace_id']}",
        },
    }
    write_json_atomic(args.output, analysis)
    write_text_atomic(args.summary, build_markdown_summary(baseline, result, analysis))
    with open(args.csv, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Connected traces: {len(rows)}/{len(traces)}")
    print("segment\tp50_ms\tp95_ms\tp99_ms")
    for name in segment_names:
        summary = summaries[name]
        print(
            f"{name}\t{summary['p50']:.3f}\t{summary['p95']:.3f}\t{summary['p99']:.3f}"
        )
    print(f"Median trace: {analysis['representativeTraces']['median']}")
    print(f"P99 trace: {analysis['representativeTraces']['p99']}")


if __name__ == "__main__":
    main()