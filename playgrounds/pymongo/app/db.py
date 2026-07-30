"""PyMongo connection helpers for DocumentDB.

DocumentDB exposes a single gateway endpoint that speaks the MongoDB wire
protocol but advertises itself as a *standalone* server (not a replica set).
PyMongo therefore needs three tweaks when creating the ``MongoClient``:

  - directConnection=True         -> don't attempt replica-set topology
                                     discovery (the gateway is standalone).
  - tls=True                      -> the gateway only accepts TLS.
  - tlsAllowInvalidCertificates   -> the default install uses a self-signed
                                     cert. Set TLS_INSECURE=false and mount a
                                     CA bundle (tlsCAFile) for production-grade
                                     verification.

The connection string itself (MONGO_URI) carries the credentials. If it still
contains ``replicaSet=rs0`` we strip it here so the driver does not try to match
a replica-set name the gateway never advertises.
"""

from __future__ import annotations

import os
import re

from pymongo import MongoClient
from pymongo.database import Database

_client: MongoClient | None = None


def sanitize_uri(uri: str | None) -> str:
    """Remove ``replicaSet=...`` from a DocumentDB connection string.

    ``replicaSet`` is incompatible with a direct connection to the gateway; the
    driver raises "client is configured to connect to a replica set named 'rs0'
    but this node belongs to a set named 'None'" otherwise.
    """
    if not uri:
        raise ValueError("MONGO_URI is not set. Provide a DocumentDB connection string.")
    return re.sub(r"[?&]replicaSet=[^&]*", "", uri)


def build_client_kwargs() -> dict:
    """Return the MongoClient kwargs DocumentDB's gateway requires."""
    tls_insecure = os.environ.get("TLS_INSECURE", "true").lower() != "false"
    return {
        "directConnection": True,
        "tls": True,
        "tlsAllowInvalidCertificates": tls_insecure,
        "serverSelectionTimeoutMS": int(os.environ.get("SERVER_SELECTION_TIMEOUT_MS", "10000")),
    }


def connect(uri: str | None = None, db_name: str | None = None) -> Database:
    """Create the shared MongoClient and return the target database."""
    global _client
    clean_uri = sanitize_uri(uri or os.environ.get("MONGO_URI"))
    database_name = db_name or os.environ.get("MONGO_DB", "pymongo_demo")

    _client = MongoClient(clean_uri, **build_client_kwargs())
    return _client[database_name]


def get_client() -> MongoClient | None:
    return _client


def ping() -> bool:
    """Return True if the gateway responds to an admin ``ping``."""
    if _client is None:
        return False
    result = _client.admin.command("ping")
    return result.get("ok") == 1


def close() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
