# documentdb-playground

A collection of small, self-contained **playgrounds** that show how to use
[DocumentDB](https://github.com/documentdb/documentdb) — the MongoDB-compatible,
open-source database engine built on PostgreSQL — from popular MongoDB drivers
and ODMs.

Each playground is a quick, hands-on test guide. Most run DocumentDB **locally
in Docker** — everything on your machine, no cloud required — so you can validate
that your driver of choice behaves the way you expect. Others may target
different environments (for example Kubernetes or a cloud deployment); each
playground's README states what it needs.

## Playgrounds

| Playground                        | Language / Stack       | What it shows                                                              |
| --------------------------------- | ---------------------- | ------------------------------------------------------------------------- |
| [mongoose](playgrounds/mongoose/) | Node.js — Mongoose ODM | Express REST API + a CRUD/compatibility test suite using the Mongoose ODM. |

More playgrounds are planned (for example **PyMongo**, **Beanie**, and other
MongoDB drivers). Contributions are welcome.

## Getting Started

Pick a playground from the table above and follow its README. As a rule, each
one only needs:

- **Docker** (Docker Desktop or a Docker daemon) — to run DocumentDB locally
- The language runtime for that playground (for example Node.js for `mongoose`)

For example, to try the Mongoose playground:

```bash
cd playgrounds/mongoose
./scripts/run-test.sh   # start DocumentDB locally and run the compatibility suite
./scripts/run-app.sh    # or run the demo REST API
```

## Repository Layout

```
documentdb-playground/
├── README.md
├── LICENSE
└── playgrounds/
    └── mongoose/     # Node.js + Mongoose ODM
```

## License

See [LICENSE](LICENSE).