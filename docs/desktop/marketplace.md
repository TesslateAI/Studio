# Desktop marketplace

Dual-source (local + cloud) marketplace with a stale-while-revalidate cache
and a SHA-256-verified install pipeline.

## Items

Four `kind` values: `agent`, `skill`, `base`, `theme`. Each installed item
lives under `$OPENSAIL_HOME/{kind}s/{slug}/manifest.json`.

Sources:

| `source` tag | Origin                                                              |
| ------------ | ------------------------------------------------------------------- |
| `"local"`    | Scanned from `$OPENSAIL_HOME/{kind}s/*/manifest.json`.       |
| `"cloud"`    | Fetched via `CloudClient.get("/api/public/marketplace/{kind}s")`.   |

Router: `/orchestrator/app/routers/marketplace_local.py`. Installer service:
`/orchestrator/app/services/marketplace_installer.py`.

## Listing: `GET /api/desktop/marketplace/items`

Query: `kind=agent|skill|base|theme` (required).

Response: `{kind, items: [...], cached: bool, stale?: true}`. Each item
carries `kind`, `source`, plus whatever the manifest or cloud response
contains. Local items also expose `install_path`.

### Merge

`_merge(local, cloud)`: local wins by `slug`; cloud items with a slug already
present in local are dropped.

### Cache (stale-while-revalidate)

- Path: `$OPENSAIL_HOME/cache/marketplace.json`.
- TTL: `_CACHE_TTL_SECONDS = 3600` (1h).
- Writes atomic (`.tmp` + `replace`).
- Fresh cache → served directly (`cached: true`).
- Stale cache + cloud enabled → served stale (`cached: true, stale: true`)
  and `BackgroundTasks.add_task(_refresh_cache_in_background, kind)` re-fetches.
- No cache + cloud disabled → local scan only, written to cache.
- No cache + cloud enabled → synchronous fetch + merge + cache write.

Cloud is considered enabled when `settings.pull_from_cloud` AND
`token_store.is_paired()`.

### Failure behavior

`_fetch_cloud` swallows `NotPairedError`, `CircuitOpenError`, HTTP ≥ 400,
non-JSON bodies, and any other `Exception` — all degrade to `[]`. The listing
endpoint itself **never raises from a cloud failure**; it falls back to
local-only items.

## Install: `POST /api/desktop/marketplace/install`

Body (`InstallRequest`): `{kind: ItemKind, slug: str}` (slug 1–200 chars).

Pipeline (`marketplace_installer.install`):

1. **Initiate** — `CloudClient.post("/api/v1/marketplace/install", json={kind, slug})`.
   Response body must contain `install_id: str`, `download_urls: [{name, url, sha256}]`,
   `manifest: dict`. Missing/malformed fields → `InstallError`.
2. **Stream-download + verify** — each `download_urls[].url` is fetched with a
   **dedicated bearer-less `httpx.AsyncClient`** (signed S3/R2 URLs must not
   carry the cloud bearer). Bytes stream in 64 KiB chunks into a
   `{slug}.installing/{name}.part` tmp file while a `hashlib.sha256` hasher
   updates incrementally. Mismatched digest → `InstallError`.
3. **Manifest write** — `manifest.json` inside the staging dir gets
   `{...cloud_manifest, source: "local", installed_from: "cloud", install_id}`.
4. **Atomic commit** — `{slug}.installing/` renames to `{slug}/`.
5. **Ack** — best-effort `POST /api/v1/marketplace/install/{install_id}/ack`.
   Ack failures log `warning` and **never** raise.

On any exception the `.installing/` staging directory is `shutil.rmtree`'d so
the target only appears on full success.

Slug guard: `/` or `..` in the slug → `InstallError("invalid slug: ...")`.

### Status-code map (router)

| Status | Condition                                                        |
| ------ | ---------------------------------------------------------------- |
| 201    | Install succeeded — `{kind, slug, install_id, path}`.            |
| 409    | Target directory already exists (`install_path(...).exists()`).  |
| 401    | `NotPairedError` during initiate.                                |
| 502    | `CircuitOpenError` or `InstallError` with "cloud"/"transport".   |
| 400    | Any other `InstallError` (invalid slug, bad cloud payload, SHA mismatch, …). |

Success invalidates the `marketplace.json` cache entry for that `kind` via
`_invalidate_cache(kind)`.

## Uninstall: `DELETE /api/desktop/marketplace/install/{kind}/{slug}`

Calls `marketplace_installer.uninstall(kind, slug)` — `shutil.rmtree` of the
install dir.

| Status | Condition                                         |
| ------ | ------------------------------------------------- |
| 204    | Directory removed.                                |
| 404    | Nothing was installed (`uninstall` returned False).|
| 400    | `InstallError` (invalid slug, etc.).              |

Cache is invalidated on success.

## Related

- `/docs/desktop/cloud.md` — `CloudClient`, token store, breaker.
- `/docs/orchestrator/agent/CLAUDE.md` — how installed skills load.
