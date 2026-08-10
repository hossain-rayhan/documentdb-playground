# DocumentDB local latency benchmark

This playground runs the same driver-native workload twice: once without
application tracing and once with a connected application-to-gateway trace. It
stores client percentiles, throughput, trace-segment percentiles, and direct
Jaeger links in a durable experiment directory.

The initial adapter uses Mongoose. Shared orchestration invokes adapters as
processes and does not import Node.js or Python application code.

## Workload data

The `large-read` workload creates one book before measurement:

```json
{
  "title": "documentdb-benchmark-target",
  "author": "benchmark:<experiment-id>",
  "genres": ["benchmark"],
  "pages": 1
}
```

It builds a deterministic `$in` query containing that title followed by
nonmatching strings until the driver's BSON serializer reports at least
`BENCHMARK_QUERY_BYTES`. Seeding, index initialization, cleanup, and warm-up are
outside the measured interval. No production or external data is ingested.

## Concurrency

`BENCHMARK_CONCURRENCY` is the maximum number of in-flight database operations.
Each adapter uses a bounded worker pool: a worker starts its next operation only
after its previous operation finishes. Client latency uses a monotonic clock.

## Run

```bash
BENCHMARK_OPERATIONS=100 \
BENCHMARK_WARMUP=20 \
BENCHMARK_CONCURRENCY=4 \
BENCHMARK_QUERY_BYTES=4096 \
  ./playgrounds/benchmarks/local-latency/benchmark.sh
```

For a higher-volume experiment, increase operations, warm-up, concurrency, and
query size. Repeat longer runs before drawing conclusions from tail percentiles.

| Variable | Default | Meaning |
| --- | --- | --- |
| `BENCHMARK_ADAPTER` | `mongoose` | Adapter under `adapters/`. |
| `BENCHMARK_ID` | generated | Experiment and trace correlation ID. |
| `BENCHMARK_OPERATIONS` | `1000` | Measured operations per phase. |
| `BENCHMARK_WARMUP` | `50` | Unmeasured operations per phase. |
| `BENCHMARK_CONCURRENCY` | `10` | Maximum in-flight operations. |
| `BENCHMARK_QUERY_BYTES` | `16384` | Minimum serialized BSON query size. |
| `BENCHMARK_WORKLOAD` | `large-read` | Portable workload name. |
| `BENCHMARK_RESULTS_DIR` | `results/` | Artifact parent directory. |
| `DOCUMENTDB_IMAGE` | `ghcr.io/documentdb/documentdb/documentdb-local:trace-4fbbfcb8` | Official tracing-enabled image. |

## Artifacts and Jaeger

Every run creates an ignored `results/<experiment-id>/` directory:

| File | Contents |
| --- | --- |
| `experiment.json` | Image identity and artifact manifest. |
| `summary.md` | Human-readable client and hop summary with measurement limitations. |
| `baseline.json` | Client results with application tracing disabled. |
| `traced.json` | Client results with application tracing enabled. |
| `trace-analysis.json` | Jaeger counts, exclusions, percentiles, and links. |
| `trace-segments.csv` | One row per complete connected trace. |

The analysis includes client total, client time outside the gateway, gateway
total, PostgreSQL duration sum and interval union, and gateway residual. The
residual subtracts the interval union so overlapping database spans are not
double-counted. Open the median and p99 links and compare the client span with
`gateway.request`, `gateway.process_request`, and `postgres.execute`.

Cross-process clocks can be slightly skewed, so the analyzer does not claim to
split request and response transport accurately. `client_outside_gateway`
includes driver work, pool wait, serialization, TLS, network time, and response
decoding. Nested duration subtraction is not CPU profiling. Jaeger storage is
ephemeral; retain the JSON and CSV artifacts after stopping the stack.

The benchmark Collector profile omits the verbose debug exporter. Leave SQL
commenter disabled unless SQL-log correlation is the experiment.

## Add an adapter

Add executable `adapters/<name>.sh` plus driver-native workload code in that
driver's playground. The adapter receives the `BENCHMARK_*` variables and must
atomically write `BENCHMARK_RESULT_FILE` according to
`schemas/adapter-result.schema.json`.

For each measured traced operation, emit a client span with `benchmark.id`,
`benchmark.phase`, `benchmark.query_bytes`, `benchmark.concurrency`,
`benchmark.workload`, and `benchmark.adapter`. Inject W3C `traceparent` into the
MongoDB command `comment` so `gateway.request` becomes its child. Reusing the
shared containers alone does not provide driver-side instrumentation.