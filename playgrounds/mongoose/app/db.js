'use strict';

const mongoose = require('mongoose');

// Default connection string for a DocumentDB instance started locally with
// `scripts/start-documentdb.sh` (or `docker run ... documentdb-local`) using the
// default credentials. Override by setting MONGO_URI.
const DEFAULT_URI =
  'mongodb://docdbadmin:Documentdb!Local1@localhost:10260/?tls=true&tlsAllowInvalidCertificates=true&directConnection=true';

/**
 * Build the Mongoose connection options that DocumentDB's gateway requires.
 *
 * DocumentDB exposes a single gateway endpoint that speaks the MongoDB wire
 * protocol but advertises itself as a standalone server (not a replica set).
 * Mongoose / the Node driver therefore needs:
 *
 *   - directConnection: true        -> don't attempt replica-set topology
 *                                      discovery (the gateway is standalone).
 *   - tls: true                     -> the gateway only accepts TLS.
 *   - tlsAllowInvalidCertificates   -> the default install uses a self-signed
 *                                      cert. Set TLS_INSECURE=false and mount a
 *                                      CA bundle for production-grade verification.
 *
 * The connection string itself (MONGO_URI) carries the credentials. If it still
 * contains `replicaSet=rs0`, strip it here so the driver does not try to match a
 * replica-set name the gateway never advertises.
 */
function sanitizeUri(uri) {
  if (!uri) {
    uri = DEFAULT_URI;
  }
  // Remove replicaSet=... (incompatible with directConnection against the gateway).
  return uri.replace(/([?&])replicaSet=[^&]*(&|$)/g, (_match, lead, trail) =>
    lead === '?' && trail === '&' ? '?' : trail === '&' ? lead : ''
  );
}

function buildOptions() {
  const tlsInsecure = (process.env.TLS_INSECURE || 'true').toLowerCase() !== 'false';
  return {
    directConnection: true,
    tls: true,
    tlsAllowInvalidCertificates: tlsInsecure,
    serverSelectionTimeoutMS: Number(process.env.SERVER_SELECTION_TIMEOUT_MS || 10000),
    // DocumentDB does not support server-side index collation. Mongoose's
    // autoIndex is fine as long as schemas avoid `collation` on indexes.
    autoIndex: true,
  };
}

async function connect() {
  const uri = sanitizeUri(process.env.MONGO_URI);
  const dbName = process.env.MONGO_DB || 'mongoose_demo';

  mongoose.set('strictQuery', true);

  await mongoose.connect(uri, { ...buildOptions(), dbName });
  return mongoose.connection;
}

module.exports = { connect, sanitizeUri, buildOptions, DEFAULT_URI };
