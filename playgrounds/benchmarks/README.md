# DocumentDB benchmarks

This directory contains repeatable synthetic performance experiments. Each
benchmark documents its workload, controls, measurement boundaries, artifacts,
and interpretation limits. Results are diagnostic and are not production
capacity claims.

## Available benchmarks

| Benchmark | Purpose |
| --- | --- |
| [Local latency](local-latency/) | Compare untraced and traced client latency, then decompose connected traces into client, gateway, and PostgreSQL segments. |