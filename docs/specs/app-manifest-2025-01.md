# Tesslate App Manifest — v1 (2025-01)

**Status:** Frozen. Any change to this version is a breaking change; new fields
or semantics go in a new schema file (`app_manifest_YYYY_MM.schema.json`).

**Authoritative schema:** `orchestrator/app/services/apps/app_manifest_2025_01.schema.json`
**Typed Pydantic mirror:** `orchestrator/app/services/apps/app_manifest.py`
**Parser:** `orchestrator/app/services/apps/manifest_parser.py`
**Hash-pin test:** `orchestrator/tests/apps/test_manifest_schema_frozen.py`

The schema file is the source of truth for structural validation. The Pydantic
model exists for typed access from Python and must be kept in lockstep. The
hash-pin test blocks merges that mutate the frozen schema file without renaming
it to a new version.

## Top-level shape

```yaml
manifest_schema_version: "2025-01"
app: { id, name, slug, version, description?, category?, icon_ref?, changelog?, forkable?, forked_from? }
source_visibility: { level, excluded_paths, manifest_always_public }
compatibility: { studio: { min, max? }, manifest_schema, runtime_api, required_features[] }
surfaces: [ { kind, entrypoint, tool_schema? } ]
compute: { tier, compute_model, containers[], hosted_agents[] }
state: { model, volume_size?, byo_database? }
connectors: [ { id, kind, scopes, required, oauth?, secret_key? } ]
schedules: [ { name, entrypoint, default_cron?, editable?, optional? } ]
migrations: [ { from, to, auto_safe?, up?, down? } ]
billing:
  ai_compute: { payer, markup_pct?, cap_usd_per_session?, cap_usd_per_month_per_install?, on_cap?, free_tier? }
  general_compute: { ... same shape ... }
  platform_fee: { model, price_usd?, billing_period?, trial_days? }
  promotional_budget?: { fund_usd, covers, on_exhaust }
listing: { visibility, update_policy_default?, minimum_rollback_version? }
eval_scenarios: [ { entrypoint, input, expected_behavior } ]
```

## Required top-level fields

`manifest_schema_version`, `app`, `compatibility`, `surfaces`, `state`, `billing`, `listing`.

All others default to empty/sensible values per the schema.

## Surface matrix

| Kind | Meaning | State compatibility |
|---|---|---|
| `ui` | Web UI served via iframe with signed install URL | any |
| `chat` | Scoped agent session in Studio chat pane | any |
| `scheduled` | Headless cron-triggered entrypoint | any |
| `triggered` | Webhook or event entrypoint | any |
| `mcp-tool` | App callable by other agents as an MCP tool | stateless or shared-db recommended |

A surface's `entrypoint` is a path within the bundle. For `mcp-tool`, `tool_schema`
is required (JSON Schema for the tool input).

## State matrix

| Model | Meaning | Persistence |
|---|---|---|
| `stateless` | No persistence across invocations | none |
| `per-install-volume` | btrfs subvolume per install | Volume Hub |
| `byo-database` | Creator provides external DB connection string | creator-managed |

## Billing

Per-dimension (`ai_compute`, `general_compute`, `platform_fee`) payer routing.
Payers: `creator`, `platform`, `installer`, `byok`.

**BYOK** is valid only on `ai_compute` (platform policy). `general_compute`
payer must be one of creator/platform/installer regardless of BYOK on AI.

`on_cap` behaviors:
- `ai_compute` default: `pause`
- `general_compute` default: `degrade`
- `platform_fee` default: `pause`

## Source visibility

`level: public | installers | private` (default: `installers`).
`excluded_paths` are always excluded regardless of level. `manifest_always_public`
means the manifest itself is readable even when source is private (installers
must see what they installed).

## Fork policy

`forkable: true | restricted | no` (default: `restricted`). `restricted` requires
creator approval. `no` disables fork regardless of source visibility. Forks
re-bind hosted-agent tools and MCPs — a fork does not inherit consents.

## Eval scenarios

At least 3 happy-path scenarios per entrypoint are required for public
marketplace listings (enforced at publish-time preflight; this schema marks
the array as `minItems: 3` only when `listing.visibility == "public"`
— enforcement lives in `services/apps/publisher.py` rather than the schema).

## Worked example (minimal)

```yaml
manifest_schema_version: "2025-01"

app:
  id: com.example.hello-app
  name: Hello App
  slug: hello-app
  version: 0.1.0
  description: Smallest valid manifest.

compatibility:
  studio: { min: "3.2.0" }
  manifest_schema: "2025-01"
  runtime_api: "^1.0"
  required_features: []

surfaces:
  - kind: ui
    entrypoint: index.html

state:
  model: stateless

billing:
  ai_compute:    { payer: installer }
  general_compute: { payer: installer }
  platform_fee:  { model: free, price_usd: 0 }

listing:
  visibility: public
```

## Worked example (hosted agent + chat)

```yaml
manifest_schema_version: "2025-01"

app:
  id: com.example.redline
  name: Email Redline
  slug: email-redline
  version: 1.4.2
  forkable: "true"

source_visibility:
  level: installers

compatibility:
  studio: { min: "3.2.0", max: "4.x" }
  manifest_schema: "2025-01"
  runtime_api: "^1.2"
  required_features: ["hosted_agent", "cas_bundle"]

surfaces:
  - kind: chat
    entrypoint: agents/primary
  - kind: mcp-tool
    entrypoint: tools/redline
    tool_schema:
      type: object
      properties:
        document_ref: { type: string }
      required: [document_ref]

compute:
  tier: 1
  compute_model: per-invocation
  hosted_agents:
    - id: primary
      model_pref: claude-sonnet-4-6
      system_prompt_ref: prompts/primary.md
      tools_ref: ["tools/redline"]
      mcps_ref: ["gmail", "gdrive"]

state:
  model: per-install-volume
  volume_size: 2Gi

connectors:
  - { id: gmail, kind: mcp, scopes: [read, send_drafts], required: true, oauth: true }
  - { id: gdrive, kind: mcp, scopes: [read], required: false, oauth: true }

billing:
  ai_compute:      { payer: installer, cap_usd_per_session: 1.00, cap_usd_per_month_per_install: 50.00 }
  general_compute: { payer: installer, cap_usd_per_month_per_install: 10.00, on_cap: degrade }
  platform_fee:    { model: subscription, price_usd: 9.00, billing_period: monthly, trial_days: 7 }

listing:
  visibility: public
  update_policy_default: patch-auto
  minimum_rollback_version: "1.3.0"

eval_scenarios:
  - entrypoint: agents/primary
    input: "draft a redline of the attached MSA"
    expected_behavior: "returns a set of tracked-change suggestions scoped to risk clauses"
  - entrypoint: agents/primary
    input: "summarize this contract in 5 bullets"
    expected_behavior: "returns 5-bullet summary without modifying the document"
  - entrypoint: tools/redline
    input: { document_ref: "gdrive://fake-id" }
    expected_behavior: "returns list of suggested edits as JSON"
```

## Compatibility semantics

- `compatibility.studio.min`: minimum deployment version that can install this app.
- `compatibility.studio.max`: maximum supported version (optional).
- `compatibility.manifest_schema`: must be `"2025-01"` for v1 manifests.
- `compatibility.runtime_api`: npm-style range over the runtime API contract.
- `compatibility.required_features`: platform features the app uses.
  Each must appear in `GET /api/version` `features[]` of the target deployment.

## Change discipline

- Never mutate `app_manifest_2025_01.schema.json` after it lands in `main`. Renaming the file
  is a breaking change; add a sibling `app_manifest_YYYY_MM.schema.json` for any new schema.
- `manifest_schema_version` is pinned to `"2025-01"` in both the JSON Schema
  (as `const`) and the Pydantic `AppManifest` (as `Literal`).
- The hash-pin test in `tests/apps/test_manifest_schema_frozen.py` fails if
  the schema file bytes change. Update the pinned hash ONLY when intentionally
  publishing a new version (which requires a new filename and schema id, and
  a new Pydantic class).
