# Replica service

`replica` keeps consistent copies of every SQLite database and chapter archive on
every node. A node that already has recent snapshots can be promoted after the
current writer dies, and a brand-new node can bootstrap from any healthy peer.

The service is read-only with respect to the live databases: snapshots are made
with `VACUUM INTO` from a read-only SQLite connection, so writable services never
see a long write transaction. Promotion is explicit and must be run while the
services that own the live files are stopped.

## Environment

All variables are read from the process environment (and `.env` when present).

| Variable | Default | Purpose |
| --- | --- | --- |
| `REPLICA_DIR` | `data/replica` | Snapshots and the pulled archive cache. |
| `REPLICA_DATA_ROOT` | `/opt/mangapoisk-reborn/data` | Root for derived live paths. |
| `CATALOG_DB` | `$REPLICA_DATA_ROOT/catalog.db` | Live catalog database. |
| `LIBRARY_DB` | `$REPLICA_DATA_ROOT/library.db` | Live library database. |
| `CONTROL_DB` | `$REPLICA_DATA_ROOT/control.db` | Live control database. |
| `MEDIA_ARCHIVE_DB` | `$REPLICA_DATA_ROOT/archives.db` | Live chapter archive database. |
| `MEDIA_ARCHIVE_DIR` | `$REPLICA_DATA_ROOT/chapter-archives` | Live chapter ZIP directory. |
| `REGISTRY_URL` | `http://85.192.37.58:8088/api/v1/registry` | Registry endpoint. |
| `REPLICA_SYNC_SECONDS` | `10` | Background sync interval. |
| `REPLICA_SELF_URL` | unset | Public base URL of this replica, for example `http://85.192.37.58:8108`. |
| `REPLICA_SYNC_DISABLED` | `false` | Disable only the background loop; manual endpoints still work. |
| `INTERNAL_TOKEN` | inherited | Sent as `X-Internal-Token` and required on every route. |

`CATALOG_DB`, `LIBRARY_DB`, `CONTROL_DB`, `MEDIA_ARCHIVE_DB` and
`MEDIA_ARCHIVE_DIR` accept absolute paths and can be used independently of
`REPLICA_DATA_ROOT`.

Snapshot layout:

```text
$REPLICA_DIR/
  snapshots/catalog.db
  snapshots/catalog.meta.json
  snapshots/library.db
  ...
  chapter-archives/<chapter>.zip
```

## Sync model

Every `REPLICA_SYNC_SECONDS` the service fetches `REGISTRY_URL` with the internal
token. The registry payload is expected to contain:

```json
{
  "services": {
    "catalog": [
      {"server_id": "...", "server_name": "...", "url": "http://host:8002",
       "healthy": true, "is_fallback": false}
    ],
    "replica": [
      {"server_id": "...", "server_name": "...", "url": "http://host:8108",
       "healthy": true, "is_fallback": false}
    ]
  }
}
```

Store to writer mapping: `catalog -> catalog`, `library -> library`,
`control -> control`, `media -> media` (the archive database and all ZIPs).
The first healthy non-fallback writer is selected in registry order; the
`replica` endpoint with the same `server_id` is used as the peer. If that replica
URL equals `REPLICA_SELF_URL`, the store is skipped because this node is the
source. Snapshots are only downloaded when the peer checksum differs from the
local one; archives are downloaded when missing or when their size/checksum
changed. Registry failures never remove local snapshots, so a node keeps serving
its last good copies.

## Internal API

All routes require `X-Internal-Token` and live under `/internal/replica`.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/status` | Snapshot size/checksum/time per store, archive count/bytes, last sync report and per-store errors, self URL. |
| `GET` | `/db/{store}` | Snapshot file (`application/octet-stream`) with `X-Checksum`, `X-Size`, `X-Updated-At`. |
| `GET` | `/db/{store}/meta` | Snapshot metadata JSON. |
| `POST` | `/sync` | `{"peers": ["http://node:8108"], "stores": ["catalog"]}`. With no peers, use the registry. |
| `POST` | `/bootstrap` | `{"source": "http://node:8108", "stores": [...], "promote": true}` pulls everything from one peer. |
| `POST` | `/promote` | `{"stores": ["catalog"]}` copies the latest snapshots over the live files. |
| `GET` | `/archives` | Manifest of live and replicated ZIPs with size and SHA-256. |
| `GET` | `/archives/{name}` | Download one ZIP. Names are validated; traversal is rejected. |

`store` is one of `catalog`, `library`, `control`, `media`. Unknown stores return
`404` (path) or `422` (request body validation).

## Promotion flow

1. Stop the services that write the databases being replaced (and media when the
   archive database is promoted).
2. Confirm the node has a recent snapshot with `GET /internal/replica/status`.
3. `POST /internal/replica/promote` with the desired stores.
4. Promotion verifies the snapshot checksum, copies the current live file to
   `<name>.bak`, then atomically replaces it with a copy of the snapshot. The
   snapshot remains available for other nodes.
5. Start the services again. Use `/bootstrap` with `"promote": true` on a new
   node to pull every store plus archives, replace the live databases and copy
   the archive cache into `MEDIA_ARCHIVE_DIR`.

## Integration assumptions

* The registry URL must return the control registry JSON and accept
  `X-Internal-Token`. The default points at the gateway; the gateway must expose
  that registry route (the control service itself serves `/internal/registry`).
* Every server that should serve as a sync source needs a `replica` service
  entry (port `8108`) registered in the control inventory.
* `REPLICA_SELF_URL` must match the `replica` endpoint URL published in the
  registry, otherwise a node cannot detect that it is the source.
* Production paths default under `/opt/mangapoisk-reborn/data`; deployments that
  keep media data in `/data` must set `REPLICA_DATA_ROOT=/data` or the individual
  `*_DB`/`MEDIA_ARCHIVE_DIR` variables.
* Snapshotting and promotion support SQLite files. A deployment that stores
  catalog/library/control in PostgreSQL must point these settings at SQLite
  copies before enabling the background loop.
