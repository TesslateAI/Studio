# Pydantic Schemas

Request/response schemas used by FastAPI routers. Kept separate from SQLAlchemy models to decouple wire format from persistence.

## Files

| File | Contents |
|------|----------|
| `app/schemas.py` | Core schemas: `UserBase`, `UserCreate`, `UserRead`, `ProjectCreate`, `ProjectRead`, `ContainerCreate`, `ContainerRead`, `ChatCreate`, `MessageRead`, `MarketplaceAgentRead`, deployment, billing, `AgentStep`, and everything else the main routers take or return. |
| `app/schemas_auth.py` | fastapi-users compatible schemas: `UserRead` (extends `fastapi_users.schemas.BaseUser[UUID]`), `UserCreate`, `UserUpdate`. These are the ones fastapi-users' auto-generated routes use. |
| `app/schemas_team.py` | Team RBAC: `TeamCreate`, `TeamRead`, `TeamMembershipCreate`, `TeamMembershipRead`, `ProjectMembershipRead`, `TeamInvitationCreate`, `AuditLogRead`. Slug field has explicit length + regex validation. |
| `app/schemas_feedback.py` | Feedback board: `FeedbackPostCreate/Read`, `FeedbackCommentCreate/Read`, upvote payloads. |
| `app/schemas_theme.py` | Theme JSON validation. Mirrors `app/src/types/theme.ts`. Validates structure before DB storage and on API responses; prevents malformed themes from reaching the frontend. |

## Conventions

- Every schema inherits from `BaseModel`.
- Read schemas use `model_config = ConfigDict(from_attributes=True)` (formerly `orm_mode=True`) to allow `ModelRead.from_orm(sqla_row)`.
- Use `Field(..., min_length=1, max_length=N)` and `@field_validator` / `@model_validator` for structural validation rather than rolling it in router bodies.
- UUIDs use `uuid.UUID` so they serialize to canonical string form.
- Dates are `datetime`; Pydantic serializes to ISO 8601.

## Cross-File Relationships

- `schemas_auth.UserRead` is the wire shape; `models_auth.User` is the DB row; `schemas.UserRead` wraps the DB with OpenSail-specific fields (subscription tier, credits, theme preset).
- Team routers return composite shapes that mix `schemas_team.*` with nested project summaries from `schemas.*`.
- Theme validation (`schemas_theme.py`) runs before `Theme.theme_json` is written; any malformed theme is rejected before it can break the frontend.

## Related

- `docs/orchestrator/models/README.md`: DB model docs. Each schema doc mirrors a model or a composition of models.
- `docs/guides/theme-system.md`: theme JSON shape and frontend consumption.
