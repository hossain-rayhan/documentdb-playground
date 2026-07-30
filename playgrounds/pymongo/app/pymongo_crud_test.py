"""PyMongo CRUD/compatibility test against DocumentDB.

Usage:
    MONGO_URI="mongodb://user:pass@host:10260/?tls=true&tlsAllowInvalidCertificates=true&directConnection=true" \
        python pymongo_crud_test.py

Or pass the URI as the first argument:
    python pymongo_crud_test.py "mongodb://user:pass@host:10260/?..."

Exercises connect, index creation, insert, find, update, aggregation,
unique-index enforcement, and delete using the raw PyMongo driver against the
DocumentDB gateway. Exits non-zero on the first real failure.
"""

from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime, timezone

from pymongo import ASCENDING, DESCENDING, IndexModel, MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError

URI = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("MONGO_URI")
DB_NAME = os.environ.get("MONGO_DB", "pymongo_test")
TLS_INSECURE = os.environ.get("TLS_INSECURE", "true").lower() != "false"

passed = 0
failed = 0


def _ok(name: str) -> None:
    global passed
    passed += 1
    print(f"  \u2705 {name}")


def _fail(name: str, err: object) -> None:
    global failed
    failed += 1
    print(f"  \u274C {name}: {err}", file=sys.stderr)


def step(name: str, fn) -> None:
    try:
        fn()
        _ok(name)
    except Exception as err:  # noqa: BLE001 - report any failure and continue
        _fail(name, err)


def sanitize_uri(uri: str) -> str:
    return re.sub(r"[?&]replicaSet=[^&]*", "", uri)


def run() -> int:
    if not URI:
        print("MONGO_URI not provided. Pass it as $1 or set MONGO_URI.", file=sys.stderr)
        return 2

    print("PyMongo DocumentDB compatibility test")
    print("=====================================")

    # Fresh collection per run keeps the test idempotent.
    coll_name = f"widgets_{int(time.time() * 1000)}"

    client: MongoClient | None = None
    state: dict = {"coll": None, "created_id": None}

    def _connect() -> None:
        nonlocal client
        client = MongoClient(
            sanitize_uri(URI),
            directConnection=True,
            tls=True,
            tlsAllowInvalidCertificates=TLS_INSECURE,
            serverSelectionTimeoutMS=15000,
        )
        ping = client.admin.command("ping")
        if ping.get("ok") != 1:
            raise RuntimeError("ping did not return ok:1")
        state["coll"] = client[DB_NAME][coll_name]

    step("connect", _connect)

    if client is None or state["coll"] is None:
        print("\nConnection failed; aborting remaining steps.", file=sys.stderr)
        return 1

    coll = state["coll"]

    def _create_indexes() -> None:
        coll.create_indexes(
            [
                IndexModel([("sku", ASCENDING)], unique=True),
                IndexModel([("name", ASCENDING), ("price", DESCENDING)]),
            ]
        )

    step("create indexes", _create_indexes)

    def _insert_one() -> None:
        res = coll.insert_one(
            {
                "sku": "SKU-001",
                "name": "Gizmo",
                "tags": ["alpha", "beta"],
                "price": 9.99,
                "active": True,
                "created_at": datetime.now(timezone.utc),
            }
        )
        state["created_id"] = res.inserted_id
        if state["created_id"] is None:
            raise RuntimeError("no _id returned")

    step("insert_one", _insert_one)

    def _insert_many() -> None:
        res = coll.insert_many(
            [
                {"sku": "SKU-002", "name": "Gadget", "tags": ["beta"], "price": 19.5},
                {"sku": "SKU-003", "name": "Widget", "tags": ["alpha", "gamma"], "price": 4.25},
            ]
        )
        if len(res.inserted_ids) != 2:
            raise RuntimeError(f"expected 2 inserted, got {len(res.inserted_ids)}")

    step("insert_many", _insert_many)

    def _get_by_id() -> None:
        doc = coll.find_one({"_id": state["created_id"]})
        if doc is None or doc.get("sku") != "SKU-001":
            raise RuntimeError("document not found or mismatched")

    step("find_one by _id", _get_by_id)

    def _find_filter_sort_limit() -> None:
        docs = list(coll.find({"price": {"$gte": 5}}).sort("price", DESCENDING).limit(10))
        if len(docs) != 2:
            raise RuntimeError(f"expected 2 docs, got {len(docs)}")
        if docs[0]["price"] < docs[1]["price"]:
            raise RuntimeError("sort order incorrect")

    step("find with filter + sort + limit", _find_filter_sort_limit)

    def _count() -> None:
        n = coll.count_documents({})
        if n != 3:
            raise RuntimeError(f"expected 3 docs, got {n}")

    step("count_documents", _count)

    def _update_one() -> None:
        res = coll.update_one({"sku": "SKU-002"}, {"$set": {"price": 21}})
        if res.modified_count != 1:
            raise RuntimeError(f"expected 1 modified, got {res.modified_count}")

    step("update_one ($set)", _update_one)

    def _find_one_and_update() -> None:
        doc = coll.find_one_and_update(
            {"sku": "SKU-003"},
            {"$push": {"tags": "delta"}},
            return_document=ReturnDocument.AFTER,
        )
        if not doc or "delta" not in doc.get("tags", []):
            raise RuntimeError("update not applied")

    step("find_one_and_update (returns new)", _find_one_and_update)

    def _aggregate() -> None:
        stats = list(
            coll.aggregate(
                [
                    {"$unwind": "$tags"},
                    {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
                    {"$sort": {"count": -1}},
                ]
            )
        )
        if not stats:
            raise RuntimeError("aggregation returned no results")

    step("aggregation ($unwind/$group)", _aggregate)

    def _unique_index() -> None:
        try:
            coll.insert_one({"sku": "SKU-001", "name": "Duplicate"})
        except DuplicateKeyError:
            return
        raise RuntimeError("duplicate insert was not rejected")

    step("unique index enforcement (duplicate sku rejected)", _unique_index)

    def _delete_one() -> None:
        res = coll.delete_one({"sku": "SKU-002"})
        if res.deleted_count != 1:
            raise RuntimeError(f"expected 1 deleted, got {res.deleted_count}")

    step("delete_one", _delete_one)

    # Vector search: DocumentDB supports a `cosmosSearch` vector index and the
    # `$vectorSearch` aggregation stage. The index is created with the raw
    # `createIndexes` command since it is not a standard MongoDB index type.
    db_ref = client[DB_NAME]
    vec_name = f"vectors_{int(time.time() * 1000)}"
    vectors = db_ref[vec_name]

    def _vector_index_insert() -> None:
        vectors.insert_many(
            [
                {"name": "a", "v": [1, 0, 0]},
                {"name": "b", "v": [0.9, 0.1, 0]},
                {"name": "c", "v": [0, 0, 1]},
            ]
        )
        res = db_ref.command(
            {
                "createIndexes": vec_name,
                "indexes": [
                    {
                        "name": "v_ivf",
                        "key": {"v": "cosmosSearch"},
                        "cosmosSearchOptions": {
                            "kind": "vector-ivf",
                            "numLists": 1,
                            "similarity": "COS",
                            "dimensions": 3,
                        },
                    }
                ],
            }
        )
        if res.get("ok") != 1:
            raise RuntimeError("createIndexes did not return ok:1")

    step("vector index + insert (cosmosSearch vector-ivf)", _vector_index_insert)

    def _vector_search() -> None:
        hits = list(
            vectors.aggregate(
                [
                    {
                        "$vectorSearch": {
                            "index": "v_ivf",
                            "path": "v",
                            "queryVector": [1, 0, 0],
                            "numCandidates": 10,
                            "limit": 2,
                        }
                    },
                    {"$project": {"name": 1, "_id": 0}},
                ]
            )
        )
        if not hits:
            raise RuntimeError("vector search returned no results")
        if hits[0].get("name") != "a":
            raise RuntimeError(f"expected nearest 'a', got {hits[0].get('name')!r}")

    step("$vectorSearch returns nearest neighbor", _vector_search)

    def _vector_cleanup() -> None:
        vectors.drop()

    step("vector cleanup (drop collection)", _vector_cleanup)

    def _drop() -> None:
        coll.drop()

    step("cleanup (drop collection)", _drop)

    client.close()

    print("\n=====================================")
    print(f"Passed: {passed}  Failed: {failed}")
    return 0 if failed == 0 else 1


def main() -> None:
    try:
        code = run()
    except Exception as err:  # noqa: BLE001
        print(f"Unexpected error: {err}", file=sys.stderr)
        sys.exit(1)
    sys.exit(code)


if __name__ == "__main__":
    main()
