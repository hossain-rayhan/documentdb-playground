'use strict';

const express = require('express');
const { ObjectId } = require('mongodb');

const db = require('./db');

const app = express();
app.use(express.json());

const PORT = Number(process.env.PORT || 3000);
let database;
let books;

function parseObjectId(value) {
  return ObjectId.isValid(value) ? new ObjectId(value) : null;
}

function serialize(document) {
  if (!document) return document;
  return { ...document, _id: document._id.toHexString() };
}

app.get('/health', async (_req, res) => {
  try {
    const result = await database.command({ ping: 1 });
    if (result.ok === 1) return res.json({ status: 'healthy', db: 'connected' });
  } catch (error) {
    return res.status(503).json({ status: 'unhealthy', db: error.message });
  }
  return res.status(503).json({ status: 'unhealthy', db: 'disconnected' });
});

app.post('/books', async (req, res) => {
  try {
    if (!req.body.title || !req.body.author) {
      return res.status(400).json({ error: 'title and author are required' });
    }
    const now = new Date();
    const document = {
      ...req.body,
      genres: req.body.genres || [],
      inStock: req.body.inStock ?? true,
      createdAt: now,
      updatedAt: now,
    };
    const result = await books.insertOne(document);
    res.status(201).json(serialize({ ...document, _id: result.insertedId }));
  } catch (error) {
    res.status(400).json({ error: error.message });
  }
});

app.get('/books', async (req, res) => {
  try {
    const filter = req.query.author ? { author: req.query.author } : {};
    const documents = await books.find(filter).sort({ createdAt: -1 }).limit(100).toArray();
    res.json({ count: documents.length, books: documents.map(serialize) });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.get('/books/:id', async (req, res) => {
  try {
    const id = parseObjectId(req.params.id);
    if (!id) return res.status(400).json({ error: 'invalid id' });
    const book = await books.findOne({ _id: id });
    if (!book) return res.status(404).json({ error: 'not found' });
    res.json(serialize(book));
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.patch('/books/:id', async (req, res) => {
  try {
    const id = parseObjectId(req.params.id);
    if (!id) return res.status(400).json({ error: 'invalid id' });
    const allowed = ['title', 'author', 'genres', 'pages', 'published', 'inStock', 'rating'];
    const changes = Object.fromEntries(
      Object.entries(req.body).filter(([key]) => allowed.includes(key))
    );
    changes.updatedAt = new Date();
    const result = await books.findOneAndUpdate(
      { _id: id },
      { $set: changes },
      { returnDocument: 'after' }
    );
    if (!result) return res.status(404).json({ error: 'not found' });
    res.json(serialize(result));
  } catch (error) {
    res.status(400).json({ error: error.message });
  }
});

app.delete('/books/:id', async (req, res) => {
  try {
    const id = parseObjectId(req.params.id);
    if (!id) return res.status(400).json({ error: 'invalid id' });
    const result = await books.deleteOne({ _id: id });
    if (result.deletedCount === 0) return res.status(404).json({ error: 'not found' });
    res.status(204).end();
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.get('/stats/genres', async (_req, res) => {
  try {
    const stats = await books
      .aggregate([
        { $unwind: '$genres' },
        { $group: { _id: '$genres', count: { $sum: 1 } } },
        { $sort: { count: -1 } },
      ])
      .toArray();
    res.json(stats);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

async function main() {
  database = await db.connect();
  books = database.collection('books');
  await books.createIndex({ author: 1, title: 1 });

  console.log('Connected to DocumentDB via the MongoDB Node.js driver');
  const server = app.listen(PORT, () =>
    console.log(`MongoDB Node.js driver demo API listening on :${PORT}`)
  );

  const shutdown = (signal) => {
    console.log(`Received ${signal}, shutting down...`);
    server.close(() => db.close().finally(() => process.exit(0)));
  };
  ['SIGTERM', 'SIGINT'].forEach((signal) =>
    process.on(signal, () => shutdown(signal))
  );
}

main().catch((error) => {
  console.error('Fatal startup error:', error.message);
  process.exit(1);
});