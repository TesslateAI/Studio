# Enterprise Logging, Audit & Telemetry Plan

## Overview

Add enterprise-grade, vendor-neutral observability to OpenSail. As an open-source product, we emit data in **standard formats** (OpenTelemetry, structured JSON) so self-hosters plug in their own stack (Datadog, Splunk, Grafana, New Relic, etc.). We **don't bundle** a specific observability stack — operators choose their own.

---

## Current State

| Component | Status | Details |
|-----------|--------|---------|
| Python logging | Basic | 1500+ logger calls across 70+ files, plain text format, no correlation IDs |
| Logging config | `main.py:54-57` | `logging.basicConfig()` with `%(asctime)s - %(name)s - %(levelname)s - %(message)s` |
| Log prefixes | Ad-hoc | `[WORKER]`, `[ARQ]`, `[CHAT]`, `[K8S]`, `[StreamAgent]`, `[CLEANUP]`, `[WEBHOOK]`, etc. |
| Request middleware | `main.py:340-353` | Logs method/path and status, no timing, no correlation IDs, no user context |
| Audit tables | Database | `AgentCommandLog`, `PodAccessLog`, `UsageLog`, `ShellSession`, `AgentStep` |
| Log export | None | No CSV/JSON export endpoints |
| Telemetry | None | No OpenTelemetry, no tracing, no metrics |
| Frontend errors | `console.error()` only | 241 `console.error`/`console.warn` calls across 73 files, zero structured reporting |
| PostHog | Partially ready | `posthog-js` installed and initialized in `app/src/lib/posthog.ts`, but no explicit event capture |
| Worker logging | `worker.py:543-546` | Separate `logging.basicConfig()`, no correlation with API pod |
| Task ID flow | Exists but unused | `task_id` generated in `chat.py:1219`, flows through `AgentTaskPayload` to worker, but not used as correlation ID |

### Critical Observability Gaps

1. **No cross-pod tracing** — requests span API pod → Redis → Worker pod with no way to correlate logs
2. **No timing data** — no visibility into how long operations take (agent tasks, container ops, LLM calls)
3. **No error propagation tracking** — errors logged per-layer, impossible to trace origin across services
4. **No frontend error capture** — client-side crashes and API failures go undetected
5. **No audit export** — audit data exists in DB but enterprises can't export it for compliance

---

## Enterprise Features Checklist

### Logging & Observability (This Plan)
- [ ] Phase 1: Structured JSON logging with correlation IDs
- [ ] Phase 2: OpenTelemetry distributed tracing + metrics (vendor-neutral)
- [ ] Phase 3: Audit log export API (CSV, JSON, JSONL)
- [ ] Phase 4: Frontend error tracking + PostHog integration

### Future Phases (Not in This Plan)
- [ ] S3 archival with KMS encryption and date-partitioned paths
- [ ] Retention policies with automated cleanup background tasks
- [ ] SIEM webhook forwarding (generic webhook for Datadog/Splunk)
- [ ] Compliance PDF/HTML reports for auditors

### Other Enterprise Features (Separate Plans)
- [ ] Team/Organization models (multi-user projects)
- [ ] RBAC (role-based access control)
- [ ] SSO/SAML integration
- [ ] API rate limiting
- [ ] 2FA/MFA enforcement
- [ ] GDPR data deletion workflows

---

## Phase 1: Structured Logging + Correlation IDs

**Goal**: Every log line becomes JSON with a `correlation_id` that traces requests from API pod through Redis to Worker pod. **Zero changes** to existing 1500+ logger calls — they get structured output automatically.

**Dependencies**: None (stdlib only)

### New Files

| File | Purpose |
|------|---------|
| `orchestrator/app/logging_config.py` | JSON formatter using stdlib `json.dumps`, `contextvars` for correlation/user/project/task IDs, `setup_logging(service_name)` function |
| `orchestrator/app/middleware/__init__.py` | Package init |
| `orchestrator/app/middleware/correlation.py` | Starlette middleware: reads/generates `X-Request-ID`, sets ContextVars, adds header to response |

### Modified Files

| File | Lines | Change |
|------|-------|--------|
| `orchestrator/app/main.py` | 54-57 | Replace `logging.basicConfig()` with `setup_logging("api")` |
| `orchestrator/app/main.py` | 340-353 | Replace request logger: add timing (`duration_ms`), log level by status code (5xx=ERROR, 4xx=WARN), skip noisy paths (`/health`, `/ready`, `/api/config`) at INFO |
| `orchestrator/app/main.py` | middleware setup | Add `CorrelationIDMiddleware` before CORS middleware |
| `orchestrator/app/worker.py` | 543-546 | Replace `logging.basicConfig()` with `setup_logging("worker")` |
| `orchestrator/app/worker.py` | ~106 | Set ContextVars (`correlation_id`, `user_id`, `project_id`, `task_id`) when picking up agent task from ARQ |
| `orchestrator/app/config.py` | settings | Add `log_format: str = "json"` (supports `"json"` or `"text"` for local dev readability) |
| `orchestrator/app/services/agent_task.py` | dataclass | Add `correlation_id: str = ""` to `AgentTaskPayload` |
| `orchestrator/app/routers/chat.py` | ~1220 | Pass `correlation_id` from ContextVar into `AgentTaskPayload` when enqueuing |
| `orchestrator/app/routers/external_agent.py` | payload construction | Pass `correlation_id` into `AgentTaskPayload` |
| `docker-compose.yml` | env vars | Add `LOG_FORMAT=text` for local dev readability |

### Design Decisions

- **`contextvars`** (not thread-local) — the backend is fully async, `contextvars` propagate correctly through `asyncio`
- **Zero third-party deps** — stdlib `json.dumps` + `logging.Formatter`, no `python-json-logger` or `structlog` needed
- **`X-Request-ID` header** flows: browser → API pod (generates if missing) → Redis payload (`correlation_id` field) → Worker pod (reads from payload) → all worker logs
- **JSON formatter reads ContextVars automatically** — every existing `logger.info("...")` call gains `correlation_id`, `user_id`, `project_id`, `task_id` fields with zero code changes
- **`exc_info` handling** — tracebacks serialized as a `traceback` string field in JSON output
- **Middleware order**: ProxyHeaders → CorrelationID → CORS → CSRF → request logging

### Log Output Format

```json
{
  "timestamp": "2026-03-07T12:00:00.000Z",
  "level": "INFO",
  "logger": "app.routers.chat",
  "correlation_id": "req_abc123",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "project_id": "660e8400-e29b-41d4-a716-446655440001",
  "task_id": "",
  "service": "api",
  "message": "[CHAT] Agent task enqueued"
}
```

Worker logs for the same request:
```json
{
  "timestamp": "2026-03-07T12:00:00.150Z",
  "level": "INFO",
  "logger": "app.worker",
  "correlation_id": "req_abc123",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "project_id": "660e8400-e29b-41d4-a716-446655440001",
  "task_id": "task_xyz789",
  "service": "worker",
  "message": "[WORKER] Agent task started"
}
```

Search all logs for a request: `grep "req_abc123"` across both API and worker pod logs.

---

## Phase 2: OpenTelemetry Tracing + Metrics (Vendor-Neutral)

**Goal**: Emit traces and metrics via OpenTelemetry. Enterprise customers point them at whatever backend they use. **Disabled by default** — self-hosters opt in.

### Dependencies

Add to `orchestrator/pyproject.toml`:
```toml
"opentelemetry-api>=1.22.0",
"opentelemetry-sdk>=1.22.0",
"opentelemetry-instrumentation-fastapi>=0.43b0",
"opentelemetry-instrumentation-sqlalchemy>=0.43b0",
"opentelemetry-instrumentation-httpx>=0.43b0",
"opentelemetry-exporter-otlp>=1.22.0",
```

### New Files

| File | Purpose |
|------|---------|
| `orchestrator/app/telemetry.py` | OTel setup: `TracerProvider`, `MeterProvider`, auto-instrumentation for FastAPI/SQLAlchemy/httpx, custom span helpers, `setup_telemetry()` function |

### Config Additions (`config.py`)

```python
# OpenTelemetry — disabled by default, enterprise self-hosters enable and point to their collector
otel_enabled: bool = False
otel_service_name: str = "tesslate-orchestrator"
otel_exporter_endpoint: str = ""       # e.g., "http://otel-collector:4317" (gRPC)
otel_exporter_protocol: str = "grpc"   # "grpc" or "http/protobuf"
```

### Auto-Instrumentation (zero code changes)

When `otel_enabled=True`, these are instrumented automatically:
- **FastAPI** — every HTTP request becomes a trace span with method, route, status, duration
- **SQLAlchemy** — every DB query becomes a child span with statement and duration
- **httpx** — every outbound HTTP call (LLM API, webhooks) becomes a child span

### Custom Spans (manual instrumentation)

| Location | Span Name | Attributes |
|----------|-----------|------------|
| `worker.py` — `execute_agent_task()` | `agent.task` | `task_id`, `user_id`, `project_id`, `model`, `iterations`, `status` |
| `agent/stream_agent.py` — per iteration | `agent.iteration` | `iteration_number`, `tool_name`, `tokens_used` |
| `agent/tools/*.py` — tool execution | `agent.tool.{name}` | `tool_name`, `duration_ms`, `success` |
| `kubernetes_orchestrator.py` — container ops | `container.{operation}` | `operation`, `namespace`, `container_name`, `status` |
| `docker.py` — container ops | `container.{operation}` | Same as above |
| `snapshot_manager.py` — snapshot ops | `snapshot.{operation}` | `project_id`, `snapshot_id`, `status` |

### Custom Metrics (via OTel MeterProvider)

```
http_request_duration_seconds{method, route, status}
agent_task_duration_seconds{model, status}
agent_iterations{model}
agent_tool_calls_total{tool_name, status}
container_operations_total{operation, status}
container_operation_duration_seconds{operation}
llm_request_duration_seconds{model}
llm_tokens_total{model, type}       # input/output
active_agent_tasks                   # gauge
active_websocket_connections         # gauge
```

### Modified Files

| File | Change |
|------|--------|
| `orchestrator/app/main.py` | Call `setup_telemetry()` at startup if `otel_enabled` |
| `orchestrator/app/config.py` | Add OTel config settings |
| `orchestrator/app/worker.py` | Wrap `execute_agent_task` in custom span; record task metrics |
| `orchestrator/app/agent/stream_agent.py` | Span per agent iteration |
| `orchestrator/app/agent/tools/*.py` | Span per tool execution (decorator pattern) |
| `orchestrator/app/services/orchestration/kubernetes_orchestrator.py` | Span + metrics around container ops |
| `orchestrator/app/services/orchestration/docker.py` | Same instrumentation pattern |
| `orchestrator/pyproject.toml` | Add OTel dependencies |
| `docker-compose.yml` | Add `OTEL_ENABLED=false` (off by default) |

### How Self-Hosters Enable It

```yaml
# In their K8s overlay or docker-compose override:
OTEL_ENABLED: "true"
OTEL_EXPORTER_ENDPOINT: "http://otel-collector:4317"
```

They point their OTel Collector at Datadog, Grafana Tempo, Jaeger, Splunk, New Relic, etc. — **their choice, not ours**.

### Example Trace

```
HTTP POST /api/chat/agent/stream  (12.3s)
├── agent.task  task_id=xyz  (12.1s)
│   ├── agent.iteration #1  (3.2s)
│   │   ├── httpx: POST litellm/chat/completions  (2.8s)
│   │   └── agent.tool.bash  cmd="npm install"  (0.3s)
│   ├── agent.iteration #2  (4.1s)
│   │   ├── httpx: POST litellm/chat/completions  (1.5s)
│   │   └── agent.tool.write  path="src/App.tsx"  (0.01s)
│   └── agent.iteration #3  (4.8s)
│       ├── httpx: POST litellm/chat/completions  (2.2s)
│       └── agent.tool.bash  cmd="npm run build"  (2.5s)
└── sqlalchemy: INSERT agent_steps  (0.05s)
```

---

## Phase 3: Audit Log Export API

**Goal**: Enterprise customers export audit logs for compliance (SOC 2, HIPAA). Uses existing database tables — no new models needed.

### New Files

| File | Purpose |
|------|---------|
| `orchestrator/app/routers/audit.py` | Export endpoints with streaming responses |
| `orchestrator/app/services/audit_export.py` | Query builders + formatters (CSV, JSON, JSONL) |
| `orchestrator/app/schemas_audit.py` | Pydantic schemas for export query params and responses |

### Endpoints

```
GET /api/audit/export/agent-commands?format=csv&start_date=2026-01-01&end_date=2026-01-31
GET /api/audit/export/pod-access?format=json&user_id=xxx
GET /api/audit/export/usage?format=jsonl&project_id=xxx
GET /api/audit/export/shell-sessions?format=csv
```

### Query Parameters

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `format` | `csv` \| `json` \| `jsonl` | `json` | Export format |
| `start_date` | ISO 8601 | none | Start of date range |
| `end_date` | ISO 8601 | none | End of date range |
| `user_id` | UUID | none | Filter by user |
| `project_id` | UUID | none | Filter by project |
| `limit` | int | 10000 | Max records (max: 100000) |
| `cursor` | string | none | Cursor for pagination |

### Implementation Pattern

```python
# Streaming response — non-blocking, handles large datasets
async def stream_export(query, format):
    async for batch in paginate_query(query, batch_size=1000):
        for record in batch:
            yield format_record(record, format)
```

### Existing Audit Tables Used

| Table | Key Fields | Records |
|-------|------------|---------|
| `AgentCommandLog` | user_id, project_id, command, risk_level, timestamp | Agent commands executed |
| `PodAccessLog` | user_id, namespace, pod_name, action, timestamp | Container/pod access |
| `UsageLog` | user_id, event_type, credits, timestamp | Usage for billing |
| `ShellSession` | user_id, project_id, started_at, ended_at | Terminal sessions |
| `AgentStep` | task_id, iteration, tool_name, tokens, timestamp | Agent execution steps |

### Access Control

- Admin-only endpoints (existing admin check middleware)
- Rate limited to prevent abuse
- Export actions logged as audit events themselves (meta-audit)

### Modified Files

| File | Change |
|------|--------|
| `orchestrator/app/main.py` | Register `audit` router |
| `orchestrator/app/config.py` | Add `audit_export_max_records: int = 100000` |

---

## Phase 4: Frontend Error Tracking + PostHog

**Goal**: Capture frontend errors and key user actions via PostHog (already initialized in `app/src/lib/posthog.ts`). Connect frontend to backend via `X-Request-ID` for cross-referencing.

**Dependencies**: None — `posthog-js` already installed and initialized.

### New Files

| File | Purpose |
|------|---------|
| `app/src/lib/errorTracking.ts` | `trackError()` and `trackApiError()` utilities wrapping PostHog `capture()`, null-safe if PostHog not configured |
| `app/src/components/ErrorBoundary.tsx` | React error boundary catching render crashes, reports to PostHog with `componentStack` |

### Modified Files

| File | Change |
|------|--------|
| `app/src/lib/api.ts` | Request interceptor: set `X-Request-ID` header via `crypto.randomUUID()`. Response interceptor: call `trackApiError()` on 5xx responses |
| `app/src/App.tsx` | Wrap app root with `<ErrorBoundary>` |
| `app/src/components/chat/ChatContainer.tsx` | `capture('agent_task_started', { project_id, model })` and `capture('agent_task_completed', { project_id, iterations, duration_ms })` |
| `app/src/components/modals/CreateProjectModal.tsx` | `capture('project_created', { base_id })` |
| `app/src/pages/Project.tsx` | `capture('project_opened', { project_id })` |

### Events Tracked

| Event | Source | Attributes |
|-------|--------|------------|
| `frontend_error` | `errorTracking.ts` | `error_message`, `error_stack`, `url` |
| `react_error_boundary` | `ErrorBoundary.tsx` | `error_message`, `component_stack` |
| `api_error` | `api.ts` interceptor | `endpoint`, `status`, `correlation_id` |
| `agent_task_started` | `ChatContainer.tsx` | `project_id`, `model` |
| `agent_task_completed` | `ChatContainer.tsx` | `project_id`, `iterations`, `duration_ms` |
| `project_created` | `CreateProjectModal.tsx` | `base_id` |
| `project_opened` | `Project.tsx` | `project_id` |

Keep events **sparse and high-signal** — don't track every click.

---

## New Config Settings Summary

```python
# Phase 1: Logging
log_format: str = "json"               # "json" (production) or "text" (local dev)

# Phase 2: OpenTelemetry
otel_enabled: bool = False             # Disabled by default
otel_service_name: str = "tesslate-orchestrator"
otel_exporter_endpoint: str = ""       # Self-hosters set their collector URL
otel_exporter_protocol: str = "grpc"   # "grpc" or "http/protobuf"

# Phase 3: Audit Export
audit_export_max_records: int = 100000
```

---

## New Dependencies

### Backend (`orchestrator/pyproject.toml`)

```toml
# Phase 2 only — Phase 1 and 3 use stdlib
"opentelemetry-api>=1.22.0",
"opentelemetry-sdk>=1.22.0",
"opentelemetry-instrumentation-fastapi>=0.43b0",
"opentelemetry-instrumentation-sqlalchemy>=0.43b0",
"opentelemetry-instrumentation-httpx>=0.43b0",
"opentelemetry-exporter-otlp>=1.22.0",
```

### Frontend (`app/package.json`)

No new dependencies — `posthog-js` already installed.

---

## Files Summary

### New Files (7)

```
orchestrator/app/logging_config.py          # Phase 1
orchestrator/app/middleware/__init__.py      # Phase 1
orchestrator/app/middleware/correlation.py   # Phase 1
orchestrator/app/telemetry.py               # Phase 2
orchestrator/app/routers/audit.py           # Phase 3
orchestrator/app/services/audit_export.py   # Phase 3
orchestrator/app/schemas_audit.py           # Phase 3
app/src/lib/errorTracking.ts                # Phase 4
app/src/components/ErrorBoundary.tsx         # Phase 4
```

### Modified Files (13)

```
orchestrator/app/main.py                    # Phases 1, 2, 3
orchestrator/app/config.py                  # Phases 1, 2, 3
orchestrator/app/worker.py                  # Phases 1, 2
orchestrator/app/services/agent_task.py     # Phase 1
orchestrator/app/routers/chat.py            # Phase 1
orchestrator/app/routers/external_agent.py  # Phase 1
orchestrator/app/agent/stream_agent.py      # Phase 2
orchestrator/app/agent/tools/*.py           # Phase 2
orchestrator/app/services/orchestration/kubernetes_orchestrator.py  # Phase 2
orchestrator/app/services/orchestration/docker.py                  # Phase 2
orchestrator/pyproject.toml                 # Phase 2
docker-compose.yml                          # Phases 1, 2
app/src/lib/api.ts                          # Phase 4
app/src/App.tsx                             # Phase 4
app/src/components/chat/ChatContainer.tsx   # Phase 4
app/src/components/modals/CreateProjectModal.tsx  # Phase 4
app/src/pages/Project.tsx                   # Phase 4
```

---

## Verification

### Phase 1: Structured Logging
1. `docker compose up` — verify logs are JSON (or text if `LOG_FORMAT=text`)
2. Make an API call → find the `correlation_id` in API pod logs
3. Trigger an agent task → find the **same** `correlation_id` in worker pod logs
4. Check response headers include `X-Request-ID`
5. Verify `duration_ms` appears in request logs

### Phase 2: OpenTelemetry
1. Set `OTEL_ENABLED=true` and `OTEL_EXPORTER_ENDPOINT=http://localhost:4317`
2. Run a local OTel Collector (or Jaeger all-in-one: `docker run -p 16686:16686 -p 4317:4317 jaegertracing/all-in-one`)
3. Trigger an agent task → see trace: `HTTP POST /api/chat/agent/stream` → `agent.task` → `agent.iteration` → `agent.tool.bash`
4. Verify metrics via OTel Collector's Prometheus exporter or OTLP backend

### Phase 3: Audit Export
1. `curl localhost:8000/api/audit/export/agent-commands?format=csv > audit.csv` — verify CSV export
2. Test date range filtering: `?start_date=2026-01-01&end_date=2026-01-31`
3. Test user filtering: `?user_id=xxx`
4. Test cursor pagination for large datasets (10k+ records)
5. Verify streaming works without loading entire result set into memory

### Phase 4: Frontend + PostHog
1. Open browser, trigger a JS error → check PostHog dashboard for `frontend_error` event
2. Send a chat message → check PostHog for `agent_task_started` event
3. Check that `X-Request-ID` from response header appears in `api_error` events
4. Verify error boundary catches render crashes

---

## Sequencing & Risk

| Phase | Risk | Effort | Notes |
|-------|------|--------|-------|
| 1: Structured Logging | Zero — additive, no deps | 1-2 days | All existing logger calls work unchanged |
| 2: OpenTelemetry | Low — disabled by default | 2-3 days | No impact unless `otel_enabled=True` |
| 3: Audit Export | Low — new endpoints only | 1-2 days | Read-only queries on existing tables |
| 4: Frontend PostHog | Zero — null-safe captures | 1 day | PostHog already initialized, no-ops if not configured |

Each phase is **independently deployable**. Total: ~5-8 days.

---

## Future Phases (Not in This Plan)

### S3 Archival
- Automatic archival after X days (e.g., 90 days)
- `s3://{bucket}/agent-commands/year=2026/month=01/day=26/*.jsonl.gz`
- Compressed (gzip), encrypted (KMS), date-partitioned
- New `AuditArchive` model for tracking archived batches
- Signed URLs for secure download

### Retention Policies
- Per-table retention: agent commands (365d), pod access (730d), usage (1095d), shell sessions (90d)
- Daily background task to delete archived records past retention
- Batch deletion (10k records per batch) to avoid lock contention

### SIEM Webhook Forwarding
- Generic webhook: `POST https://siem.example.com/webhook`
- Batched delivery with HMAC signing
- Configurable event types: `security`, `audit`, `error`
- For future Datadog/Splunk/ELK integration

### Compliance Reports
- PDF/HTML reports for auditors
- Summary statistics + detailed logs
- Time-boxed (monthly, quarterly)
