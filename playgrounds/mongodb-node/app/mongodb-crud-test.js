'use strict';

const { MongoClient } = require('mongodb');

const { DEFAULT_URI, buildOptions, sanitizeUri } = require('./db');

const URI = process.argv[2] || process.env.MONGO_URI || DEFAULT_URI;
const DB_NAME = process.env.MONGO_DB || 'mongodb_node_test';

let passed = 0;
let failed = 0;

async function step(name, action) {
  try {
    await action();
    passed += 1;
    console.log(`  \u2705 ${name}`);
  } catch (error) {
    failed += 1;
    console.error(`  \u274C ${name}: ${error.message}`);
  }
}

async function run() {
  console.log('MongoDB Node.js driver DocumentDB compatibility test');
  console.log('====================================================');

  const client = new MongoClient(sanitizeUri(URI), {
    ...buildOptions(),
    serverSelectionTimeoutMS: 15000,
  });
  let connected = false;

  await step('connect', async () => {
    await client.connect();
    const ping = await client.db('admin').command({ ping: 1 });
    if (ping.ok !== 1) throw new Error('ping did not return ok:1');
    connected = true;
  });

  if (!connected) {
    console.error('\nConnection failed; aborting remaining steps.');
    process.exitCode = 1;
    return;
  }

  const database = client.db(DB_NAME);
  const collectionName = `widgets_${Date.now()}`;
  const collection = database.collection(collectionName);
  const vectorCollectionName = `vectors_${Date.now()}`;
  const vectors = database.collection(vectorCollectionName);
  let createdId;

  await step('create indexes', async () => {
    await collection.createIndexes([
      { key: { sku: 1 }, name: 'sku_unique', unique: true },
      { key: { name: 1, price: -1 }, name: 'name_price' },
    ]);
  });

  await step('insertOne', async () => {
    const result = await collection.insertOne({
      sku: 'SKU-001',
      name: 'Gizmo',
      tags: ['alpha', 'beta'],
      price: 9.99,
      active: true,
      createdAt: new Date(),
    });
    createdId = result.insertedId;
    if (!createdId) throw new Error('no _id returned');
  });

  await step('insertMany', async () => {
    const result = await collection.insertMany([
      { sku: 'SKU-002', name: 'Gadget', tags: ['beta'], price: 19.5 },
      { sku: 'SKU-003', name: 'Widget', tags: ['alpha', 'gamma'], price: 4.25 },
    ]);
    if (result.insertedCount !== 2) {
      throw new Error(`expected 2 inserted, got ${result.insertedCount}`);
    }
  });

  await step('findOne by _id', async () => {
    const document = await collection.findOne({ _id: createdId });
    if (!document || document.sku !== 'SKU-001') {
      throw new Error('document not found or mismatched');
    }
  });

  await step('find with filter + sort + limit', async () => {
    const documents = await collection
      .find({ price: { $gte: 5 } })
      .sort({ price: -1 })
      .limit(10)
      .toArray();
    if (documents.length !== 2) throw new Error(`expected 2 docs, got ${documents.length}`);
    if (documents[0].price < documents[1].price) throw new Error('sort order incorrect');
  });

  await step('countDocuments', async () => {
    const count = await collection.countDocuments({});
    if (count !== 3) throw new Error(`expected 3 docs, got ${count}`);
  });

  await step('updateOne ($set)', async () => {
    const result = await collection.updateOne({ sku: 'SKU-002' }, { $set: { price: 21 } });
    if (result.modifiedCount !== 1) {
      throw new Error(`expected 1 modified, got ${result.modifiedCount}`);
    }
  });

  await step('findOneAndUpdate (returns new)', async () => {
    const document = await collection.findOneAndUpdate(
      { sku: 'SKU-003' },
      { $push: { tags: 'delta' } },
      { returnDocument: 'after' }
    );
    if (!document || !document.tags.includes('delta')) throw new Error('update not applied');
  });

  await step('aggregation ($unwind/$group)', async () => {
    const stats = await collection
      .aggregate([
        { $unwind: '$tags' },
        { $group: { _id: '$tags', count: { $sum: 1 } } },
        { $sort: { count: -1 } },
      ])
      .toArray();
    if (stats.length === 0) throw new Error('aggregation returned no results');
  });

  await step('unique index enforcement (duplicate sku rejected)', async () => {
    try {
      await collection.insertOne({ sku: 'SKU-001', name: 'Duplicate' });
    } catch (error) {
      if (error.code === 11000) return;
      throw error;
    }
    throw new Error('duplicate insert was not rejected');
  });

  await step('deleteOne', async () => {
    const result = await collection.deleteOne({ sku: 'SKU-002' });
    if (result.deletedCount !== 1) {
      throw new Error(`expected 1 deleted, got ${result.deletedCount}`);
    }
  });

  await step('vector index + insert (cosmosSearch vector-ivf)', async () => {
    await vectors.insertMany([
      { name: 'a', vector: [1, 0, 0] },
      { name: 'b', vector: [0.9, 0.1, 0] },
      { name: 'c', vector: [0, 0, 1] },
    ]);
    const result = await database.command({
      createIndexes: vectorCollectionName,
      indexes: [
        {
          name: 'vector_ivf',
          key: { vector: 'cosmosSearch' },
          cosmosSearchOptions: {
            kind: 'vector-ivf',
            numLists: 1,
            similarity: 'COS',
            dimensions: 3,
          },
        },
      ],
    });
    if (result.ok !== 1) throw new Error('createIndexes did not return ok:1');
  });

  await step('$vectorSearch returns nearest neighbor', async () => {
    const hits = await vectors
      .aggregate([
        {
          $vectorSearch: {
            index: 'vector_ivf',
            path: 'vector',
            queryVector: [1, 0, 0],
            numCandidates: 10,
            limit: 2,
          },
        },
        { $project: { name: 1, _id: 0 } },
      ])
      .toArray();
    if (hits.length === 0) throw new Error('vector search returned no results');
    if (hits[0].name !== 'a') throw new Error(`expected nearest 'a', got '${hits[0].name}'`);
  });

  await step('vector cleanup (drop collection)', async () => vectors.drop());
  await step('cleanup (drop collection)', async () => collection.drop());

  await client.close();

  console.log('\n====================================================');
  console.log(`Passed: ${passed}  Failed: ${failed}`);
  process.exitCode = failed === 0 ? 0 : 1;
}

run().catch((error) => {
  console.error('Unexpected error:', error);
  process.exitCode = 1;
});