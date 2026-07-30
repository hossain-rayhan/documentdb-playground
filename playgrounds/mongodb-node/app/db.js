'use strict';

const { MongoClient } = require('mongodb');

const DEFAULT_URI =
  'mongodb://docdbadmin:Documentdb!Local1@localhost:10260/?tls=true&tlsAllowInvalidCertificates=true&directConnection=true';

let client;
let database;

function sanitizeUri(uri = DEFAULT_URI) {
  return uri.replace(/([?&])replicaSet=[^&]*(&|$)/g, (_match, lead, trail) =>
    lead === '?' && trail === '&' ? '?' : trail === '&' ? lead : ''
  );
}

function buildOptions() {
  return {
    directConnection: true,
    tls: true,
    tlsAllowInvalidCertificates:
      (process.env.TLS_INSECURE || 'true').toLowerCase() !== 'false',
    serverSelectionTimeoutMS: Number(process.env.SERVER_SELECTION_TIMEOUT_MS || 10000),
  };
}

async function connect() {
  if (database) return database;

  client = new MongoClient(sanitizeUri(process.env.MONGO_URI), buildOptions());
  await client.connect();
  database = client.db(process.env.MONGO_DB || 'mongodb_node_demo');
  await database.command({ ping: 1 });
  return database;
}

async function close() {
  if (client) await client.close();
  client = undefined;
  database = undefined;
}

module.exports = { connect, close, sanitizeUri, buildOptions, DEFAULT_URI };