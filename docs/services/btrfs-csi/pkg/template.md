# pkg/template

Manages read-only template subvolumes under `/mnt/tesslate-pool/templates/`. Templates are the base for instant CoW project creation.

## File

`manager.go`:

| Method | Purpose |
|--------|---------|
| `EnsureTemplate(name)` | If present, ensure read-only flag in place (no delete + redownload). If missing, download from CAS. |
| `EnsureTemplateByHash(name, hash)` | Hash-verified variant. |
| `UploadTemplate(name)` | Create a read-only snapshot and `btrfs send` it directly to CAS. Updates `index/templates.json`. |
| `RefreshTemplate(name)` | Force re-download from CAS. |
| `MaterialiseBundleTemplate(prefix)` | Multi-layer bundle chain materialisation (see `bundleTemplatePrefix = "bundle:"`). |

## Why send-direct

`UploadTemplate` sends the template directly (no intermediate snapshot) so the btrfs UUID carried in the send stream matches what is used as the `-p` parent for incremental layer sends later. This is the property that lets incremental restore work across nodes: the received UUID on node B is identical to the hash recorded in CAS.

## Bundle templates

Names prefixed with `bundle:` point at published app bundles. Materialisation uses the bundle manifest recipe (base blob + ordered layers) instead of the single-blob template path. This keeps the template index small while allowing incrementally built app templates.

## Concurrency

`sync.Mutex` per template name. Two callers asking for the same template race once, then share the result.
