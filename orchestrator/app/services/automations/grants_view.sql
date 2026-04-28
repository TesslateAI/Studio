-- =============================================================================
-- automation_grants — unified view over the scattered "permission" stores.
--
-- Background
-- ----------
-- The plan's `Grant` primitive collapses five existing tables into a single
-- conceptual shape::
--
--     Grant:
--       subject:   { kind, id }
--       resource:  { kind, id }
--       capability
--       constraints
--       granted_at
--       revoked_at
--
-- This VIEW projects today's underlying tables into that shape. The
-- `grant_resolver.preflight_check()` helper joins against this VIEW for
-- "does this subject have this (capability, resource) right now?" queries
-- — keeping every preflight on a single SQL surface even while the
-- backing storage stays scattered.
--
-- `contract.allowed_*` is intentionally NOT projected here. Those values
-- are not persistent rows — they live inline on AutomationDefinition.contract
-- JSON. `grant_resolver.py` reads them directly off the run's automation
-- alongside the VIEW lookup. Once Phase 7 lands the canonical `grants`
-- table, contract.allowed_* will normalize into rows and join cleanly,
-- but until then the resolver bridges the two surfaces.
--
-- Design notes
-- ------------
-- * Pure projection — no joins to the subject / resource side, no expensive
--   fan-out. Each underlying table contributes exactly one row to the
--   union per (subject, capability, resource) tuple.
-- * `revoked_at` filtering is the caller's job. Most callers will
--   `WHERE revoked_at IS NULL`, but Phase 7 needs to walk the full history
--   for audit replays so the VIEW exposes both columns.
-- * `subject_id` and `resource_id` are TEXT, not UUID, because some sources
--   key by string identifiers (e.g., `mcp_server_id` is a slug, `connector_id`
--   is the manifest's connector slug). Callers cast back when they know
--   the kind.
-- * `constraints` is JSONB so callers can filter on inline scope/exposure
--   data without a second lookup.
-- =============================================================================

DROP VIEW IF EXISTS automation_grants CASCADE;

CREATE VIEW automation_grants AS
-- 1) UserMcpConfig → "user holds the right to call this MCP server".
SELECT
    'user'::text                       AS subject_kind,
    user_id::text                      AS subject_id,
    'use'::text                        AS capability,
    'mcp_server'::text                 AS resource_kind,
    COALESCE(marketplace_agent_id::text, id::text) AS resource_id,
    jsonb_build_object(
        'scope_level', scope_level,
        'project_id', project_id,
        'team_id',    team_id,
        'is_active',  is_active
    )                                  AS constraints,
    created_at                         AS granted_at,
    NULL::timestamptz                  AS revoked_at
FROM user_mcp_configs
WHERE is_active = true

UNION ALL

-- 2) McpConsentRecord → "this app install consented to invoke this MCP tool".
SELECT
    'app_instance'::text               AS subject_kind,
    app_instance_id::text              AS subject_id,
    'invoke'::text                     AS capability,
    'mcp_tool_call'::text              AS resource_kind,
    mcp_server_id::text                AS resource_id,
    jsonb_build_object(
        'scopes', COALESCE(scopes, '[]'::jsonb)
    )                                  AS constraints,
    granted_at                         AS granted_at,
    revoked_at                         AS revoked_at
FROM mcp_consent_records

UNION ALL

-- 3) ChannelConfig → "user holds the right to send via this channel".
SELECT
    'user'::text                       AS subject_kind,
    user_id::text                      AS subject_id,
    'send'::text                       AS capability,
    'channel'::text                    AS resource_kind,
    id::text                           AS resource_id,
    jsonb_build_object(
        'channel_type', channel_type,
        'team_id',      team_id,
        'is_active',    is_active
    )                                  AS constraints,
    created_at                         AS granted_at,
    NULL::timestamptz                  AS revoked_at
FROM channel_configs
WHERE is_active = true

UNION ALL

-- 4) DeploymentCredential → "user holds the right to deploy via this provider".
--    There is no `scopes` column today; constraints exposes provider_metadata
--    so callers can filter on (account_id, team_id, etc.) without a second
--    lookup.
SELECT
    'user'::text                       AS subject_kind,
    user_id::text                      AS subject_id,
    'deploy'::text                     AS capability,
    'deployment_provider'::text        AS resource_kind,
    provider::text                     AS resource_id,
    jsonb_build_object(
        'project_id',        project_id,
        'provider_metadata', metadata
    )                                  AS constraints,
    created_at                         AS granted_at,
    NULL::timestamptz                  AS revoked_at
FROM deployment_credentials

UNION ALL

-- 5) AppConnectorGrant → "this app install consented to call this connector".
SELECT
    'app_instance'::text               AS subject_kind,
    app_instance_id::text              AS subject_id,
    'use'::text                        AS capability,
    'connector'::text                  AS resource_kind,
    requirement_id::text               AS resource_id,
    jsonb_build_object(
        'exposure_at_grant', exposure_at_grant
    )                                  AS constraints,
    granted_at                         AS granted_at,
    revoked_at                         AS revoked_at
FROM app_connector_grants;

COMMENT ON VIEW automation_grants IS
    'Phase 1 unified projection of the scattered permission tables into the '
    'conceptual Grant shape. contract.allowed_tools/skills/mcps/apps is read '
    'directly by grant_resolver.py (it lives on AutomationDefinition.contract '
    'JSON, not as rows). Phase 7 swaps this VIEW for a real grants table '
    'without changing the grant_resolver interface.';
