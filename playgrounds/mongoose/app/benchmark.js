'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const { connect } = require('./db');
const {
  installMongooseTracePropagation,
  shutdownTelemetry,
  traceDocumentDbOperation,
  tracingEnabled,
} = require('./telemetry');
const mongoose = require('mongoose');
const Book = require('./models/book');

const adapter = 'mongoose';
const benchmarkId = requiredString('BENCHMARK_ID');
const phase = requiredChoice('BENCHMARK_PHASE', ['baseline', 'traced']);
const workload = process.env.BENCHMARK_WORKLOAD || 'large-read';
const resultFile = path.resolve(requiredString('BENCHMARK_RESULT_FILE'));
const operations = positiveInteger('BENCHMARK_OPERATIONS', 1000);
const warmup = nonnegativeInteger('BENCHMARK_WARMUP', 50);
const concurrency = positiveInteger('BENCHMARK_CONCURRENCY', 10);
const requestedQueryBytes = positiveInteger('BENCHMARK_QUERY_BYTES', 16384);
const databaseName = process.env.MONGO_DB || 'mongoose_benchmark';

if (workload !== 'large-read') {
  throw new Error(`Unsupported Mongoose benchmark workload: ${workload}`);
}
if (phase === 'traced' && !tracingEnabled) {
  throw new Error('BENCHMARK_PHASE=traced requires OTEL_TRACES_ENABLED=true');
}

function requiredString(name) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function requiredChoice(name, choices) {
  const value = requiredString(name);
  if (!choices.includes(value)) {
    throw new Error(`${name} must be one of: ${choices.join(', ')}`);
  }
  return value;
}

function integer(name, fallback, minimum) {
  const raw = process.env[name] || String(fallback);
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < minimum) {
    throw new Error(`${name} must be an integer greater than or equal to ${minimum}`);
  }
  return value;
}

function positiveInteger(name, fallback) {
  return integer(name, fallback, 1);
}

function nonnegativeInteger(name, fallback) {
  return integer(name, fallback, 0);
}

function percentile(sortedValues, percentage) {
  if (sortedValues.length === 0) return null;
  const index = Math.max(0, Math.ceil((percentage / 100) * sortedValues.length) - 1);
  return sortedValues[index];
}

function buildLargeReadFilter(targetBytes, matchingTitle) {
  const titles = [matchingTitle];
  let filter = { title: { $in: titles } };
  while (mongoose.mongo.BSON.calculateObjectSize(filter) < targetBytes) {
    titles.push(`missing-${String(titles.length).padStart(6, '0')}-${'x'.repeat(32)}`);
    filter = { title: { $in: titles } };
  }
  return {
    filter,
    actualBytes: mongoose.mongo.BSON.calculateObjectSize(filter),
  };
}

async function runBounded(total, workerCount, operation) {
  let nextIndex = 0;
  await Promise.all(
    Array.from({ length: Math.min(total, workerCount) }, async () => {
      while (true) {
        const index = nextIndex;
        nextIndex += 1;
        if (index >= total) return;
        await operation(index);
      }
    })
  );
}

function writeJsonAtomic(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temporary = `${file}.tmp-${process.pid}`;
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  fs.renameSync(temporary, file);
}

async function main() {
  installMongooseTracePropagation(mongoose);
  await connect();
  await Book.init();

  const seedAuthor = `benchmark:${benchmarkId}`;
  await Book.deleteMany({ author: seedAuthor });
  const seeded = await Book.create({
    title: 'documentdb-benchmark-target',
    author: seedAuthor,
    genres: ['benchmark'],
    pages: 1,
  });
  const { filter, actualBytes } = buildLargeReadFilter(requestedQueryBytes, seeded.title);
  const attributes = {
    'benchmark.id': benchmarkId,
    'benchmark.phase': phase,
    'benchmark.query_bytes': actualBytes,
    'benchmark.concurrency': concurrency,
    'benchmark.workload': workload,
    'benchmark.adapter': adapter,
  };
  const runOperation = () =>
    traceDocumentDbOperation(
      'benchmarkFind',
      databaseName,
      () => Book.findOne(filter).lean(),
      attributes
    );

  for (let index = 0; index < warmup; index += 1) {
    const result = await runOperation();
    if (!result) throw new Error('Warm-up query did not return the seeded document');
  }

  const latenciesMs = [];
  let failures = 0;
  let successes = 0;
  const measurementStartUs = Date.now() * 1000;
  const measurementStart = process.hrtime.bigint();
  await runBounded(operations, concurrency, async () => {
    const operationStart = process.hrtime.bigint();
    try {
      const result = await runOperation();
      if (!result) throw new Error('Measured query did not return the seeded document');
      successes += 1;
    } catch (error) {
      failures += 1;
    } finally {
      latenciesMs.push(Number(process.hrtime.bigint() - operationStart) / 1e6);
    }
  });
  const elapsedSeconds = Number(process.hrtime.bigint() - measurementStart) / 1e9;
  const measurementEndUs = Date.now() * 1000;
  latenciesMs.sort((left, right) => left - right);

  writeJsonAtomic(resultFile, {
    schemaVersion: 1,
    adapter,
    benchmarkId,
    phase,
    workload,
    tracingEnabled,
    requestedQueryBytes,
    actualQueryBytes: actualBytes,
    warmupOperations: warmup,
    measuredOperations: operations,
    successfulOperations: successes,
    failedOperations: failures,
    concurrency,
    measurementStartUs,
    measurementEndUs,
    elapsedSeconds,
    throughputOperationsPerSecond: operations / elapsedSeconds,
    latencyMs: {
      minimum: latenciesMs[0],
      mean: latenciesMs.reduce((sum, value) => sum + value, 0) / latenciesMs.length,
      p50: percentile(latenciesMs, 50),
      p95: percentile(latenciesMs, 95),
      p99: percentile(latenciesMs, 99),
      maximum: latenciesMs.at(-1),
    },
    runtime: {
      node: process.version,
      mongoose: mongoose.version,
      platform: `${os.platform()}-${os.arch()}`,
    },
    telemetry: {
      serviceName: process.env.OTEL_SERVICE_NAME || null,
      operationName: 'mongoose.benchmarkFind',
    },
    database: {
      name: databaseName,
      directConnection: true,
      tls: true,
    },
  });

  await Book.deleteMany({ author: seedAuthor });
  if (failures > 0) process.exitCode = 1;
}

async function shutdown() {
  await mongoose.connection.close(false).catch(() => {});
  await shutdownTelemetry().catch(() => {});
}

let shuttingDown = false;
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, async () => {
    if (shuttingDown) return;
    shuttingDown = true;
    await shutdown();
    process.exit(128 + (signal === 'SIGINT' ? 2 : 15));
  });
}

main()
  .catch((error) => {
    console.error(`Mongoose benchmark failed: ${error.message}`);
    process.exitCode = 1;
  })
  .finally(shutdown);