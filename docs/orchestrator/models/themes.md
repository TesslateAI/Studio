# Theme System Models

This document covers the Theme model and related database schema for OpenSail's theming system. The theme system enables customizable UI themes stored in the database and served via API.

## Overview

OpenSail uses a database-driven theme system where themes are:
1. Stored as JSON in PostgreSQL
2. Seeded from JSON files in `scripts/themes/`
3. Served via public API endpoints (no auth required)
4. Applied as CSS variables in the frontend

---

## Theme Model

**File**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\models.py`

The Theme model stores complete UI theme definitions including colors, typography, spacing, and animations.

### Schema

```python
class Theme(Base):
    """UI themes stored as JSON. Loaded from scripts/themes/ and served via API."""
    __tablename__ = "themes"

    # Primary key - human-readable ID (e.g., "midnight-dark", "ocean-light")
    id = Column(String(100), primary_key=True, index=True)

    # Display information
    name = Column(String(100), nullable=False)       # "Midnight", "Ocean", "Forest"
    mode = Column(String(10), nullable=False)        # "dark" or "light"
    author = Column(String(100), default="Tesslate")
    version = Column(String(20), default="1.0.0")
    description = Column(Text, nullable=True)

    # Full theme JSON (colors, typography, spacing, animation)
    theme_json = Column(JSON, nullable=False)

    # Theme metadata
    is_default = Column(Boolean, default=False)      # Default theme for new users
    is_active = Column(Boolean, default=True)        # Can be disabled without deletion
    sort_order = Column(Integer, default=0)          # For ordering in UI picker

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

### Field Details

| Field | Type | Description |
|-------|------|-------------|
| `id` | String(100) | Primary key, human-readable ID like `default-dark` or `midnight` |
| `name` | String(100) | Display name shown in theme picker (e.g., "Midnight") |
| `mode` | String(10) | Theme mode: `dark` or `light` |
| `author` | String(100) | Theme creator, defaults to "Tesslate" |
| `version` | String(20) | Semantic version for theme updates |
| `description` | Text | Optional description shown in theme picker |
| `theme_json` | JSON | Complete theme definition (see structure below) |
| `is_default` | Boolean | If true, this is the default theme for new users |
| `is_active` | Boolean | If false, theme is hidden but not deleted |
| `sort_order` | Integer | Lower numbers appear first in theme picker |

### Indexes

- **Primary Key Index**: `id` column is indexed for fast lookups by theme ID
- No additional indexes needed as theme queries are simple and infrequent

### Constraints

- `id` must be unique (primary key constraint)
- `name` is required (NOT NULL)
- `mode` is required (NOT NULL)
- `theme_json` is required (NOT NULL)

---

## User Theme Preference

**File**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\models_auth.py`

Users can set their preferred theme via the `theme_preset` field on the User model.

### User.theme_preset Field

```python
class User(SQLAlchemyBaseUserTable[uuid.UUID], Base):
    __tablename__ = "users"

    # ... other fields ...

    # User preferences
    theme_preset: Mapped[Optional[str]] = mapped_column(
        String, nullable=True, default="default-dark"
    )  # References Theme.id
```

### Field Details

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `theme_preset` | String | `default-dark` | References `Theme.id`, stores user's selected theme |

### Relationship Notes

- This is a **soft reference** (no foreign key constraint) to allow flexibility
- If a theme is deleted, users retain their preference string (frontend falls back to default)
- No cascade delete - user preferences are independent of theme existence

---

## Theme JSON Structure

The `theme_json` column stores a comprehensive theme definition. The structure is validated by Pydantic schemas in `schemas_theme.py`.

### Complete Structure

```json
{
  "colors": {
    "primary": "#F89521",
    "primaryHover": "#fa9f35",
    "primaryRgb": "248, 149, 33",
    "accent": "#00D9FF",

    "background": "#111113",
    "surface": "#0a0a0a",
    "surfaceHover": "#1a1a1a",

    "text": "#ffffff",
    "textMuted": "rgba(255, 255, 255, 0.6)",
    "textSubtle": "rgba(255, 255, 255, 0.4)",

    "border": "rgba(255, 255, 255, 0.1)",
    "borderHover": "rgba(255, 255, 255, 0.2)",

    "sidebar": {
      "background": "#0a0a0a",
      "text": "#ffffff",
      "border": "rgba(255, 255, 255, 0.06)",
      "hover": "rgba(255, 255, 255, 0.05)",
      "active": "rgba(248, 149, 33, 0.15)"
    },

    "input": {
      "background": "#1a1a1a",
      "border": "rgba(255, 255, 255, 0.1)",
      "borderFocus": "#F89521",
      "text": "#ffffff",
      "placeholder": "rgba(255, 255, 255, 0.4)"
    },

    "scrollbar": {
      "thumb": "rgba(255, 255, 255, 0.2)",
      "thumbHover": "rgba(255, 255, 255, 0.3)",
      "track": "transparent"
    },

    "code": {
      "inlineBackground": "rgba(248, 149, 33, 0.1)",
      "inlineText": "#F89521",
      "blockBackground": "rgba(0, 0, 0, 0.4)",
      "blockBorder": "rgba(255, 255, 255, 0.1)",
      "blockText": "#e2e2e2"
    },

    "status": {
      "error": "#ef4444",
      "errorRgb": "239, 68, 68",
      "success": "#22c55e",
      "successRgb": "34, 197, 94",
      "warning": "#f59e0b",
      "warningRgb": "245, 158, 11",
      "info": "#3b82f6",
      "infoRgb": "59, 130, 246"
    },

    "shadow": {
      "small": "0 1px 2px rgba(0, 0, 0, 0.3)",
      "medium": "0 4px 6px rgba(0, 0, 0, 0.3)",
      "large": "0 10px 15px rgba(0, 0, 0, 0.3)"
    }
  },

  "typography": {
    "fontFamily": "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    "fontFamilyMono": "JetBrains Mono, Menlo, Monaco, 'Courier New', monospace",
    "fontSizeBase": "14px",
    "lineHeight": "1.5"
  },

  "spacing": {
    "radiusSmall": "4px",
    "radiusMedium": "6px",
    "radiusLarge": "8px",
    "radiusXl": "12px"
  },

  "animation": {
    "durationFast": "150ms",
    "durationNormal": "200ms",
    "durationSlow": "300ms",
    "easing": "cubic-bezier(0.4, 0, 0.2, 1)"
  }
}
```

### Color Sections

| Section | Purpose | Example Variables |
|---------|---------|-------------------|
| Core colors | Primary brand colors | `primary`, `primaryHover`, `accent` |
| Backgrounds | Page and surface backgrounds | `background`, `surface`, `surfaceHover` |
| Text | Text colors at different emphasis levels | `text`, `textMuted`, `textSubtle` |
| Borders | Border colors for containers and dividers | `border`, `borderHover` |
| Sidebar | Navigation sidebar specific colors | `sidebar.background`, `sidebar.active` |
| Input | Form input field colors | `input.background`, `input.borderFocus` |
| Scrollbar | Custom scrollbar styling | `scrollbar.thumb`, `scrollbar.track` |
| Code | Code block and inline code styling | `code.inlineBackground`, `code.blockBorder` |
| Status | Semantic status colors | `status.error`, `status.success`, `status.warning` |
| Shadow | Box shadow definitions | `shadow.small`, `shadow.medium`, `shadow.large` |

### Typography Section

| Field | Purpose | Example |
|-------|---------|---------|
| `fontFamily` | Primary font stack | `Inter, -apple-system, sans-serif` |
| `fontFamilyMono` | Monospace font for code | `JetBrains Mono, Menlo, monospace` |
| `fontSizeBase` | Base font size | `14px` |
| `lineHeight` | Default line height | `1.5` |

### Spacing Section

| Field | Purpose | Example |
|-------|---------|---------|
| `radiusSmall` | Small border radius (buttons, inputs) | `4px` |
| `radiusMedium` | Medium border radius (cards) | `6px` |
| `radiusLarge` | Large border radius (modals) | `8px` |
| `radiusXl` | Extra large radius (panels) | `12px` |

### Animation Section

| Field | Purpose | Example |
|-------|---------|---------|
| `durationFast` | Quick transitions (hover) | `150ms` |
| `durationNormal` | Standard transitions | `200ms` |
| `durationSlow` | Slower animations (modals) | `300ms` |
| `easing` | Cubic bezier easing function | `cubic-bezier(0.4, 0, 0.2, 1)` |

---

## Database Migrations

### Migration 0002: Add theme_preset to Users

**File**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\alembic\versions\0002_add_theme_preset.py`

```python
"""Add theme_preset column to users table

Revision ID: 0002_theme_preset
Revises: 0001_initial
Create Date: 2025-01-25
"""

revision: str = '0002_theme_preset'
down_revision: Union[str, Sequence[str], None] = '0001_initial'

def upgrade() -> None:
    """Add theme_preset column to users table."""
    op.add_column('users', sa.Column('theme_preset', sa.String(), nullable=True))

def downgrade() -> None:
    """Remove theme_preset column from users table."""
    op.drop_column('users', 'theme_preset')
```

### Migration 0003: Create themes Table

**File**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\alembic\versions\0003_add_themes_table.py`

```python
"""Add themes table

Revision ID: 0003_add_themes_table
Revises: 0002_theme_preset
Create Date: 2024-01-25
"""

revision: str = '0003_add_themes_table'
down_revision: Union[str, None] = '0002_theme_preset'

def upgrade() -> None:
    op.create_table(
        'themes',
        sa.Column('id', sa.String(100), primary_key=True, index=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('mode', sa.String(10), nullable=False),
        sa.Column('author', sa.String(100), server_default='Tesslate'),
        sa.Column('version', sa.String(20), server_default='1.0.0'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('theme_json', postgresql.JSON(), nullable=False),
        sa.Column('is_default', sa.Boolean(), server_default='false'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('sort_order', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

def downgrade() -> None:
    op.drop_table('themes')
```

### Running Migrations

```bash
# Apply all migrations
docker exec tesslate-orchestrator alembic upgrade head

# Check current migration version
docker exec tesslate-orchestrator alembic current

# Rollback one migration
docker exec tesslate-orchestrator alembic downgrade -1
```

---

## Seeding Themes

Themes are seeded from JSON files using the seed script.

**Seed Script**: `c:\Users\Smirk\Downloads\Tesslate-Studio\scripts\seed\seed_themes.py`

**Theme Files**: `c:\Users\Smirk\Downloads\Tesslate-Studio\scripts\themes\`

### Available Themes

| Theme ID | Name | Mode | Description |
|----------|------|------|-------------|
| `default-dark` | Default Dark | dark | The default Tesslate dark theme with orange accents |
| `default-light` | Default Light | light | Light version of the default theme |
| `midnight` | Midnight | dark | Deep blue dark theme |
| `ocean` | Ocean | dark | Cool blue ocean-inspired theme |
| `forest` | Forest | dark | Green nature-inspired theme |
| `rose` | Rose | dark | Pink/rose accent theme |
| `sunset` | Sunset | dark | Warm orange/red sunset theme |

### Running the Seed Script

```bash
# Connect to Docker postgres directly (from project root)
python scripts/seed/seed_themes.py

# Or with custom DATABASE_URL
DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/db" python scripts/seed/seed_themes.py
```

### Seed Script Behavior

- Uses **upsert pattern**: existing themes are updated, new themes are inserted
- Sets `sort_order` based on theme name (default themes first)
- Marks `default-dark` and `default-light` as `is_default=True`
- All seeded themes have `is_active=True`

---

## API Endpoints

**Router File**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\routers\themes.py`

### Endpoints

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/api/themes` | List all themes (lightweight, no JSON) | No |
| GET | `/api/themes/full` | List all themes with full JSON | No |
| GET | `/api/themes/{theme_id}` | Get single theme by ID | No |
| GET | `/api/themes/default/{mode}` | Get default theme for mode | No |

### Response Models

**ThemeListItem** (lightweight listing):
```python
class ThemeListItem(BaseModel):
    id: str
    name: str
    mode: str  # "dark" or "light"
    author: Optional[str] = None
    description: Optional[str] = None
```

**ThemeResponse** (full theme with JSON):
```python
class ThemeResponse(BaseModel):
    id: str
    name: str
    mode: str  # "dark" or "light"
    author: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None
    colors: dict
    typography: dict
    spacing: dict
    animation: dict
```

### Example API Calls

```bash
# List all themes (lightweight)
curl http://localhost:8000/api/themes

# List all themes with full JSON
curl http://localhost:8000/api/themes/full

# Get a specific theme
curl http://localhost:8000/api/themes/midnight

# Get default dark theme
curl http://localhost:8000/api/themes/default/dark
```

---

## Theme Validation

**Validation Schemas**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\schemas_theme.py`

Theme JSON is validated using Pydantic models to ensure all required fields are present and properly formatted.

### Validation Patterns

- **CSS Colors**: Hex, rgb(), rgba(), hsl(), hsla(), or `transparent`
- **RGB Strings**: Format like `"248, 149, 33"`
- **CSS Sizes**: Values like `"8px"`, `"1rem"`, `"50%"`
- **CSS Durations**: Values like `"150ms"`, `"0.3s"`

### Validation Functions

```python
from app.schemas_theme import validate_theme_json

# Returns (is_valid: bool, error_message: str | None, schema: ThemeJsonSchema | None)
is_valid, error, schema = validate_theme_json(theme.theme_json)

if not is_valid:
    logger.warning(f"Theme validation failed: {error}")
```

### Validation in API

Theme JSON is validated on API responses. Invalid themes are logged but still returned (non-blocking):

```python
# In themes.py router
is_valid, error, _ = validate_theme_json(theme.theme_json)
if not is_valid:
    logger.warning(f"Theme validation failed: theme_id={theme.id}, error={error}")
```

---

## Common Queries

### Get all active themes ordered for picker

```python
result = await db.execute(
    select(Theme)
    .where(Theme.is_active == True)
    .order_by(Theme.sort_order, Theme.name)
)
themes = result.scalars().all()
```

### Get theme by ID

```python
result = await db.execute(
    select(Theme)
    .where(Theme.id == theme_id, Theme.is_active == True)
)
theme = result.scalar_one_or_none()
```

### Get default theme for a mode

```python
# Try default theme first
result = await db.execute(
    select(Theme)
    .where(Theme.mode == "dark", Theme.is_default == True, Theme.is_active == True)
    .limit(1)
)
theme = result.scalar_one_or_none()

# Fallback to first theme of that mode
if not theme:
    result = await db.execute(
        select(Theme)
        .where(Theme.mode == "dark", Theme.is_active == True)
        .order_by(Theme.sort_order)
        .limit(1)
    )
    theme = result.scalar_one_or_none()
```

### Update user's theme preference

```python
user.theme_preset = "midnight"
await db.commit()
```

### Disable a theme (soft delete)

```python
theme.is_active = False
await db.commit()
```

---

## Frontend Integration

**Frontend File**: `c:\Users\Smirk\Downloads\Tesslate-Studio\app\src\theme\themePresets.ts`

### Theme Loading

Themes are loaded from the API once on app startup and cached in memory:

```typescript
import { loadThemes, getThemePreset, applyThemePreset } from '../theme/themePresets';

// Load themes on app init
await loadThemes();

// Get and apply a theme
const theme = getThemePreset('midnight');
applyThemePreset(theme);
```

### CSS Variable Mapping

The `applyThemePreset` function sets CSS custom properties on the document root:

| Theme Property | CSS Variable |
|----------------|--------------|
| `colors.primary` | `--primary` |
| `colors.background` | `--bg` |
| `colors.sidebar.background` | `--sidebar-bg` |
| `colors.input.borderFocus` | `--input-border-focus` |
| `typography.fontFamily` | `--font-family` |
| `spacing.radiusLarge` | `--radius-large` |
| `animation.durationFast` | `--duration-fast` |

---

## Related Files

| File | Purpose |
|------|---------|
| `orchestrator/app/models.py` | Theme model definition |
| `orchestrator/app/models_auth.py` | User.theme_preset field |
| `orchestrator/app/routers/themes.py` | Theme API endpoints |
| `orchestrator/app/schemas_theme.py` | Theme JSON validation schemas |
| `orchestrator/alembic/versions/0002_add_theme_preset.py` | User migration |
| `orchestrator/alembic/versions/0003_add_themes_table.py` | Theme table migration |
| `scripts/seed/seed_themes.py` | Theme seeding script |
| `scripts/themes/*.json` | Theme definition files |
| `app/src/theme/themePresets.ts` | Frontend theme loading and application |
| `app/src/theme/ThemeContext.tsx` | React theme context provider |
| `app/src/lib/api.ts` | API client with `themesApi` methods |

---

## Summary

The Theme system provides:

- **Theme Model**: Stores complete theme definitions with colors, typography, spacing, and animations
- **User Preference**: `theme_preset` field on User model for persisting user's selected theme
- **Public API**: Unauthenticated endpoints for theme loading (enables theme before login)
- **Validation**: Pydantic schemas ensure theme JSON structure is correct
- **Seeding**: JSON files in `scripts/themes/` can be seeded to database
- **Frontend Integration**: Themes applied as CSS custom properties

Key design decisions:
- Theme IDs are human-readable strings (not UUIDs) for easier debugging and configuration
- No foreign key constraint between User.theme_preset and Theme.id for flexibility
- Theme endpoints are public to allow theme loading before authentication
- Validation is non-blocking (invalid themes logged but still served)
