# Types

TypeScript definitions in `app/src/types/`. The runtime source of truth for API response shapes is `app/src/lib/api.ts`; the files here are either thin re-exports, frontend-only augmentations, or runtime validators.

## File Index

| File | Purpose |
|------|---------|
| `types/agent.ts` | `ToolCallDetail`, `ChatAttachment`, `SerializedAttachment`, streaming event payloads (`TextDeltaEvent`, `AgentStepEvent`, `ApprovalRequiredEvent`, etc.) |
| `types/assets.ts` | `Asset` shape, `formatFileSize`, `getFileTypeBadgeColor`, `validateFile`, `getAuthenticatedAssetUrl` helpers |
| `types/billing.ts` | `TierConfig`, `SubscriptionResponse`, `CreditBalanceResponse`, `CreditStatusResponse`, `UsageLog`, `Transaction` |
| `types/chat.ts` | `ChatAgent` (lightweight shape used across chat UI; icon, avatar, mode, model, backendId) |
| `types/git-providers.ts` | `GitProvider`, `ConnectedAccount`, `RepoMeta`, `Branch` for unified GitHub/GitLab/Bitbucket UI |
| `types/git.ts` | `GitCommitInfo`, `GitStatus`, `GitDiff`, `GitBranch` for git operations |
| `types/nodeConfig.ts` | `NodeConfigFieldType` union, `FieldSchema`, `FormSchema`, agent-driven node-config event payloads (`UserInputRequiredEvent`, `NodeConfigCancelledEvent`, `NodeConfigResumedEvent`, `SecretRotatedEvent`, `ArchitectureNodeAddedEvent`) |
| `types/project.ts` | `ComputeTier` (`none` / `ephemeral` / `environment`); `getFeatures(tier)` returns feature flags per compute tier |
| `types/tesslateConfig.ts` | `TesslateConfig`, `AppConfig`, `InfraConfig`, `TesslateConfigResponse`, `SetupConfigSyncResponse` for `.tesslate/config.json` |
| `types/theme.ts` | Theme types re-exported from `api.ts`, plus `isValidTheme`, `validateTheme`, `DEFAULT_FALLBACK_THEME` runtime validators |

## Backend Sync

The source of truth for theme properties is `orchestrator/app/schemas_theme.py`. When adding a new color or spacing property, update in order: backend Pydantic schema -> `lib/api.ts` -> `types/theme.ts` validators + `DEFAULT_FALLBACK_THEME`.

Similarly, `types/tesslateConfig.ts` mirrors `.tesslate/config.json` as parsed by the backend's setup-config endpoint.

## Runtime Validation

Themes are validated before application to prevent partial CSS writes. Use `isValidTheme(theme)` for a boolean check or `validateTheme(theme)` for `{ isValid, error }`. Invalid themes fall back to `DEFAULT_FALLBACK_THEME`.

## Related Docs

- `docs/app/api/CLAUDE.md` – `lib/api.ts` is the canonical response type source
- `docs/app/state/theme.md` – theme system internals
- `docs/orchestrator/services/themes.md` – backend theme API
