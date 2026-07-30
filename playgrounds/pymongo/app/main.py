"""Flask + PyMongo demo REST API for DocumentDB.

Run locally with scripts/run-app.sh, or directly:

    MONGO_URI="mongodb://user:pass@localhost:10260/?tls=true&tlsAllowInvalidCertificates=true&directConnection=true" \
        python main.py

Endpoints:
    GET    /health          -> liveness/readiness (checks the gateway ping)
    POST   /books           -> create a book
    GET    /books           -> list books (optional ?author= filter)
    GET    /books/{id}       -> fetch one book by id
    PATCH  /books/{id}       -> update a book
    DELETE /books/{id}       -> delete a book
    GET    /stats/genres    -> aggregation: count of books per genre
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from flask import Flask, jsonify, request

import db
from models import book as book_model

PORT = int(os.environ.get("PORT", "3000"))

app = Flask(__name__)

# Connect once at import/startup and ensure the demo indexes exist.
database = db.connect()
books = database[book_model.COLLECTION_NAME]
books.create_indexes(book_model.INDEXES)
print("Connected to DocumentDB via PyMongo")


def _parse_object_id(book_id: str) -> ObjectId | None:
    try:
        return ObjectId(book_id)
    except (InvalidId, TypeError):
        return None


@app.get("/health")
def health():
    """Return 200 only when the gateway responds to a ping."""
    try:
        if db.ping():
            return jsonify(status="healthy", db="connected")
    except Exception as exc:  # noqa: BLE001 - report any connection error as unhealthy
        return jsonify(status="unhealthy", db=str(exc)), 503
    return jsonify(status="unhealthy", db="disconnected"), 503


@app.post("/books")
def create_book():
    payload = request.get_json(silent=True) or {}
    if not payload.get("title") or not payload.get("author"):
        return jsonify(error="title and author are required"), 400
    doc = book_model.build_document(payload)
    result = books.insert_one(doc)
    created = books.find_one({"_id": result.inserted_id})
    return jsonify(book_model.serialize(created)), 201


@app.get("/books")
def list_books():
    author = request.args.get("author")
    query = {"author": author} if author else {}
    cursor = books.find(query).sort("created_at", -1).limit(100)
    docs = [book_model.serialize(d) for d in cursor]
    return jsonify(count=len(docs), books=docs)


@app.get("/books/<book_id>")
def get_book(book_id: str):
    oid = _parse_object_id(book_id)
    if oid is None:
        return jsonify(error="invalid id"), 400
    doc = books.find_one({"_id": oid})
    if doc is None:
        return jsonify(error="not found"), 404
    return jsonify(book_model.serialize(doc))


@app.patch("/books/<book_id>")
def update_book(book_id: str):
    oid = _parse_object_id(book_id)
    if oid is None:
        return jsonify(error="invalid id"), 400
    changes = request.get_json(silent=True) or {}
    allowed = {"title", "author", "genres", "pages", "published", "in_stock", "rating"}
    updates = {k: v for k, v in changes.items() if k in allowed}
    if updates:
        updates["updated_at"] = datetime.now(timezone.utc)
        result = books.update_one({"_id": oid}, {"$set": updates})
        if result.matched_count == 0:
            return jsonify(error="not found"), 404
    doc = books.find_one({"_id": oid})
    if doc is None:
        return jsonify(error="not found"), 404
    return jsonify(book_model.serialize(doc))


@app.delete("/books/<book_id>")
def delete_book(book_id: str):
    oid = _parse_object_id(book_id)
    if oid is None:
        return jsonify(error="invalid id"), 400
    result = books.delete_one({"_id": oid})
    if result.deleted_count == 0:
        return jsonify(error="not found"), 404
    return "", 204


@app.get("/stats/genres")
def genre_stats():
    pipeline = [
        {"$unwind": "$genres"},
        {"$group": {"_id": "$genres", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    return jsonify(list(books.aggregate(pipeline)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
