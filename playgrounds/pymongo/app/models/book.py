"""Example "book" collection helpers for the PyMongo demo.

PyMongo is a **raw driver**, not an ODM: there is no schema class. Instead this
module centralizes everything the app and tests need to treat a plain BSON
document as a "Book":

  - the collection name,
  - the index definitions (no ``collation`` — DocumentDB does not implement it),
  - a builder that applies defaults + timestamps to a create payload, and
  - a JSON serializer that makes ``_id``/``datetime`` values response-friendly.

It mirrors the Mongoose/Beanie ``Book`` models in the sibling playgrounds so the
three demos are directly comparable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from pymongo import ASCENDING, IndexModel

COLLECTION_NAME = "books"

# Compound index: exercises DocumentDB index creation via PyMongo.
# No `collation` option here; DocumentDB does not implement it.
INDEXES = [
    IndexModel([("author", ASCENDING), ("title", ASCENDING)], name="author_title"),
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_document(payload: Mapping[str, Any]) -> dict:
    """Apply defaults + timestamps to a create payload, returning a new dict."""
    now = _utcnow()
    return {
        "title": payload["title"],
        "author": payload["author"],
        "genres": list(payload.get("genres", [])),
        "pages": payload.get("pages"),
        "published": payload.get("published"),
        "in_stock": payload.get("in_stock", True),
        "rating": payload.get("rating"),
        "created_at": now,
        "updated_at": now,
    }


def serialize(doc: Mapping[str, Any] | None) -> dict | None:
    """Convert a BSON document into a JSON-serializable dict."""
    if doc is None:
        return None
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    for key in ("published", "created_at", "updated_at"):
        value = out.get(key)
        if isinstance(value, datetime):
            out[key] = value.isoformat()
    return out
