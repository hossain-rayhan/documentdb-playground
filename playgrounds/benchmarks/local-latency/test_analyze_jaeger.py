import unittest

from analyze_jaeger import (
    build_markdown_summary,
    complete_trace_count,
    interval_union_duration,
    percentile,
)


class AnalyzeJaegerTest(unittest.TestCase):
    def test_percentile_uses_nearest_rank(self):
        self.assertEqual(percentile([4, 1, 3, 2], 50), 2)
        self.assertEqual(percentile([4, 1, 3, 2], 99), 4)

    def test_interval_union_merges_overlaps_and_adjacency(self):
        self.assertEqual(
            interval_union_duration([(20, 25), (1, 5), (4, 10), (10, 12)]),
            16,
        )

    def test_interval_union_handles_empty_input(self):
        self.assertEqual(interval_union_duration([]), 0)

    def test_summary_discloses_one_way_latency_limit(self):
        result = {
            "benchmarkId": "test-run",
            "adapter": "test",
            "workload": "large-read",
            "measuredOperations": 10,
            "warmupOperations": 2,
            "concurrency": 1,
            "actualQueryBytes": 1024,
            "throughputOperationsPerSecond": 100,
            "latencyMs": {
                "mean": 1,
                "p50": 1,
                "p95": 2,
                "p99": 3,
                "maximum": 4,
            },
        }
        segment = {"mean": 1, "p50": 1, "p95": 2, "p99": 3, "maximum": 4}
        analysis = {
            "completeTraceCount": 10,
            "returnedTraceCount": 10,
            "segments": {
                "client_total_ms": segment,
                "client_outside_gateway_ms": segment,
                "gateway_total_ms": segment,
                "postgres_union_ms": segment,
                "gateway_residual_ms": segment,
            },
            "representativeTraces": {"median": "http://median", "p99": "http://p99"},
        }

        summary = build_markdown_summary(result, result, analysis)

        self.assertIn("Exact one-way client-to-gateway latency is not available", summary)
        self.assertIn("## Latency by hop", summary)

    def test_complete_trace_count_requires_connected_postgres_span(self):
        result = {
            "benchmarkId": "test-run",
            "measurementStartUs": 100,
            "measurementEndUs": 200,
        }
        trace = {
            "processes": {
                "app": {"serviceName": "client"},
                "gateway": {"serviceName": "documentdb_gateway"},
            },
            "spans": [
                {
                    "processID": "app",
                    "spanID": "client-span",
                    "startTime": 150,
                    "tags": [
                        {"key": "benchmark.id", "value": "test-run"},
                        {"key": "benchmark.phase", "value": "traced"},
                    ],
                },
                {
                    "processID": "gateway",
                    "operationName": "gateway.request",
                    "references": [
                        {"refType": "CHILD_OF", "spanID": "client-span"}
                    ],
                },
                {
                    "processID": "gateway",
                    "operationName": "postgres.execute",
                },
            ],
        }

        self.assertEqual(
            complete_trace_count(
                [trace], result, "client", "documentdb_gateway"
            ),
            1,
        )
        trace["spans"].pop()
        self.assertEqual(
            complete_trace_count(
                [trace], result, "client", "documentdb_gateway"
            ),
            0,
        )


if __name__ == "__main__":
    unittest.main()