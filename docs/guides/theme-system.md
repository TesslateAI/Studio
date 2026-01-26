# Theme System Guide

This guide covers Tesslate Studio's theme system, which allows users to customize the application's visual appearance through database-stored themes served via API.

## Overview

The theme system provides:

- **Database-stored themes**: Themes are stored as JSON in PostgreSQL and served via REST API
- **CSS variable-based application**: Themes are applied by setting CSS custom properties on the document root
- **Dual-mode support**: Each theme has a mode (`dark` or `light`)
- **Runtime validation**: Both backend (Pydantic) and frontend (TypeScript) validation ensure theme integrity
- **Fallback handling**: A hardcoded fallback theme ensures the app works even if the API fails
- **User preference persistence**: The user's selected theme is saved to their profile

### Architecture Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Theme System Flow                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  scripts/themes/*.json  ──seed_themes.py──>  PostgreSQL (themes table)     │
│                                                        │                    │
│                                                        │                    │
│                                              GET /api/themes/full           │
│                                                        │                    │
│                                                        v                    │
│                                              ThemeContext.tsx               │
│                                                        │                    │
│                                                        v                    │
│                                              applyThemePreset()             │
│                                              (CSS variables)                │
│                                                        │                    │
│                                                        v                    │
│                                              document.documentElement       │
│                                              --primary, --bg, etc.          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Backend Theme API

**Router file**: `orchestrator/app/routers/themes.py`

The theme API is **public** (no authentication required) so themes can load before user login.

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/themes` | List all active themes (lightweight, no full JSON) |
| GET | `/api/themes/full` | List all active themes with full JSON data |
| GET | `/api/themes/{theme_id}` | Get a single theme by ID with full JSON |
| GET | `/api/themes/default/{mode}` | Get the default theme for a mode (`dark` or `light`) |

### Response Schemas

**ThemeListItem** (lightweight listing):
```json
{
  "id": "default-dark",
  "name": "Default Dark",
  "mode": "dark",
  "author": "Tesslate",
  "description": "The default Tesslate dark theme"
}
```

**ThemeResponse** (full theme):
```json
{
  "id": "default-dark",
  "name": "Default Dark",
  "mode": "dark",
  "author": "Tesslate",
  "version": "1.0.0",
  "description": "The default Tesslate dark theme with orange accents",
  "colors": { ... },
  "typography": { ... },
  "spacing": { ... },
  "animation": { ... }
}
```

### API Usage Examples

```bash
# List all themes (lightweight)
curl http://localhost:8000/api/themes

# List all themes with full JSON
curl http://localhost:8000/api/themes/full

# Get a specific theme
curl http://localhost:8000/api/themes/default-dark

# Get the default dark theme
curl http://localhost:8000/api/themes/default/dark
```

## Theme Model (Database Schema)

**File**: `orchestrator/app/models.py` (Theme class)

```python
class Theme(Base):
    __tablename__ = "themes"

    id = Column(String(100), primary_key=True, index=True)  # e.g., "midnight-dark"
    name = Column(String(100), nullable=False)              # Display name: "Midnight"
    mode = Column(String(10), nullable=False)               # "dark" or "light"
    author = Column(String(100), default="Tesslate")
    version = Column(String(20), default="1.0.0")
    description = Column(Text, nullable=True)

    # Full theme JSON (colors, typography, spacing, animation)
    theme_json = Column(JSON, nullable=False)

    # Theme metadata
    is_default = Column(Boolean, default=False)   # Default theme for new users
    is_active = Column(Boolean, default=True)     # Can be disabled without deletion
    sort_order = Column(Integer, default=0)       # For ordering in UI

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

### Column Details

| Column | Type | Description |
|--------|------|-------------|
| `id` | String(100) | Primary key, kebab-case identifier (e.g., `midnight-dark`) |
| `name` | String(100) | Human-readable display name |
| `mode` | String(10) | Either `"dark"` or `"light"` |
| `author` | String(100) | Theme creator name (default: "Tesslate") |
| `version` | String(20) | Semantic version (default: "1.0.0") |
| `description` | Text | Optional description shown in theme picker |
| `theme_json` | JSON | Complete theme data (colors, typography, spacing, animation) |
| `is_default` | Boolean | If true, this is the default for new users of this mode |
| `is_active` | Boolean | Soft-delete flag; inactive themes are hidden from API |
| `sort_order` | Integer | Display order in theme picker UI |

## Theme JSON Structure

**Location**: `scripts/themes/*.json`

A theme JSON file contains metadata and four sections: `colors`, `typography`, `spacing`, and `animation`.

### Complete JSON Structure

```json
{
  "id": "my-theme-dark",
  "name": "My Theme",
  "mode": "dark",
  "author": "Your Name",
  "version": "1.0.0",
  "description": "A custom theme description",

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

### Color Values

The following color formats are supported:

| Format | Example |
|--------|---------|
| Hex (3-8 digits) | `#F89521`, `#fff`, `#ffffff80` |
| RGB | `rgb(248, 149, 33)` |
| RGBA | `rgba(255, 255, 255, 0.6)` |
| HSL | `hsl(32, 94%, 55%)` |
| HSLA | `hsla(32, 94%, 55%, 0.8)` |
| Transparent | `transparent` |

**RGB strings** (used for `primaryRgb`, status `*Rgb` values) use the format `"R, G, B"` (e.g., `"248, 149, 33"`).

### CSS Variable Mapping

When a theme is applied, values map to CSS variables:

| JSON Path | CSS Variable |
|-----------|--------------|
| `colors.primary` | `--primary` |
| `colors.primaryHover` | `--primary-hover` |
| `colors.primaryRgb` | `--primary-rgb` |
| `colors.background` | `--bg`, `--bg-dark` |
| `colors.surface` | `--surface` |
| `colors.text` | `--text` |
| `colors.sidebar.background` | `--sidebar-bg` |
| `colors.input.borderFocus` | `--input-border-focus` |
| `colors.status.error` | `--status-error`, `--status-red` |
| `typography.fontFamily` | `--font-family` |
| `spacing.radiusSmall` | `--radius-small` |
| `animation.durationFast` | `--duration-fast` |

See `app/src/theme/themePresets.ts` function `applyThemePreset()` for the complete mapping.

## How to Add New Themes

### Step 1: Create the Theme JSON File

Create a new file in `scripts/themes/` following the naming convention `{theme-name}.json`:

```bash
# Example: scripts/themes/cyberpunk.json
```

Start by copying an existing theme and modifying the values:

```json
{
  "id": "cyberpunk-dark",
  "name": "Cyberpunk",
  "mode": "dark",
  "author": "Your Name",
  "version": "1.0.0",
  "description": "Neon-inspired cyberpunk theme",

  "colors": {
    "primary": "#ff00ff",
    "primaryHover": "#ff33ff",
    "primaryRgb": "255, 0, 255",
    "accent": "#00ffff",
    ...
  },
  ...
}
```

### Step 2: Validate the Theme (Optional but Recommended)

You can validate your theme JSON before seeding:

```python
# Quick validation script
import json
from orchestrator.app.schemas_theme import validate_theme_json

with open("scripts/themes/cyberpunk.json") as f:
    theme_data = json.load(f)

is_valid, error, _ = validate_theme_json({
    "colors": theme_data.get("colors", {}),
    "typography": theme_data.get("typography", {}),
    "spacing": theme_data.get("spacing", {}),
    "animation": theme_data.get("animation", {}),
})

if is_valid:
    print("Theme is valid!")
else:
    print(f"Validation error: {error}")
```

### Step 3: Run the Seed Script

**Docker mode:**
```bash
python scripts/seed/seed_themes.py
```

**Kubernetes mode:**
```bash
# Port-forward to the database first
kubectl port-forward -n tesslate svc/tesslate-postgres 5432:5432

# Run the seed script
DATABASE_URL="postgresql+asyncpg://tesslate_user:your_password@localhost:5432/tesslate_dev" \
  python scripts/seed/seed_themes.py
```

### Step 4: Verify in the Application

1. Refresh the Tesslate Studio frontend
2. Open Settings > Appearance
3. Your new theme should appear in the theme picker

### Theme Naming Conventions

- **ID**: Lowercase kebab-case with mode suffix: `{name}-{mode}` (e.g., `cyberpunk-dark`)
- **Name**: Human-readable title case (e.g., "Cyberpunk")
- **Mode**: Must be either `"dark"` or `"light"`

### Creating Light/Dark Variants

For a complete theme, create both variants:

- `scripts/themes/cyberpunk-dark.json` (mode: "dark")
- `scripts/themes/cyberpunk-light.json` (mode: "light")

The theme toggle button will switch between variants with matching base names.

## Frontend Integration

### ThemeContext

**File**: `app/src/theme/ThemeContext.tsx`

The `ThemeProvider` component manages theme state and provides it via React context.

```tsx
import { ThemeProvider, useTheme } from './theme/ThemeContext';

// In your app root:
<ThemeProvider>
  <App />
</ThemeProvider>

// In any component:
function MyComponent() {
  const {
    theme,            // "dark" | "light"
    themePresetId,    // e.g., "default-dark"
    themePreset,      // Full theme object
    toggleTheme,      // Switch between dark/light variants
    setThemePreset,   // Set a specific theme by ID
    availablePresets, // Array of all loaded themes
    isLoading,        // True while loading from API
    isReady,          // True when themes are usable
  } = useTheme();

  return (
    <select
      value={themePresetId}
      onChange={(e) => setThemePreset(e.target.value)}
    >
      {availablePresets.map((preset) => (
        <option key={preset.id} value={preset.id}>
          {preset.name}
        </option>
      ))}
    </select>
  );
}
```

### themePresets Module

**File**: `app/src/theme/themePresets.ts`

Key functions:

| Function | Description |
|----------|-------------|
| `loadThemes()` | Fetch themes from API and cache in memory |
| `getThemePreset(id)` | Get a theme by ID (with fallback) |
| `getThemePresetsByMode()` | Get themes grouped by mode |
| `applyThemePreset(theme)` | Apply a theme's CSS variables to the document |
| `areThemesLoaded()` | Check if themes have been loaded |

### Using CSS Variables in Components

Once a theme is applied, use the CSS variables in your styles:

```css
.my-component {
  background-color: var(--surface);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius-medium);
  transition: all var(--duration-normal) var(--easing);
}

.my-component:hover {
  background-color: var(--surface-hover);
  border-color: var(--border-hover);
}

.primary-button {
  background-color: var(--primary);
  color: var(--text);
}

.primary-button:hover {
  background-color: var(--primary-hover);
}
```

### Using Theme Values in JavaScript

```tsx
const { themePreset } = useTheme();

// Access theme values directly
const primaryColor = themePreset.colors.primary;
const fontFamily = themePreset.typography.fontFamily;
```

## Validation

### Backend Validation (Pydantic)

**File**: `orchestrator/app/schemas_theme.py`

The backend validates theme JSON using Pydantic schemas with comprehensive type checking.

#### Schema Structure

The validation uses nested Pydantic models:

```python
ThemeJsonSchema              # Root schema
├── ThemeColors              # colors.*
│   ├── SidebarColors        # colors.sidebar.*
│   ├── InputColors          # colors.input.*
│   ├── ScrollbarColors      # colors.scrollbar.*
│   ├── CodeColors           # colors.code.*
│   ├── StatusColors         # colors.status.*
│   └── ShadowValues         # colors.shadow.*
├── ThemeTypography          # typography.*
├── ThemeSpacing             # spacing.*
└── ThemeAnimation           # animation.*
```

#### Using Validation

```python
from orchestrator.app.schemas_theme import (
    validate_theme_json,
    get_theme_validation_errors,
    ThemeJsonSchema,
    ThemeCreateRequest,
    ThemeUpdateRequest,
)

# Simple validation (returns tuple)
is_valid, error, schema = validate_theme_json(theme_data)
if not is_valid:
    print(f"Invalid: {error}")

# Get detailed errors as list
errors = get_theme_validation_errors(theme_data)
for err in errors:
    print(err)  # e.g., "colors.primary: field required"

# Create request validation (for admin API)
request = ThemeCreateRequest(
    id="my-theme-dark",
    name="My Theme",
    mode="dark",
    theme_json={...}
)
```

#### Validation Patterns

| Pattern | Validates | Example |
|---------|-----------|---------|
| `CSS_COLOR_PATTERN` | Hex, rgb(), rgba(), hsl(), hsla(), transparent | `#F89521`, `rgba(255,255,255,0.6)` |
| `RGB_STRING_PATTERN` | RGB string format | `"248, 149, 33"` |
| `CSS_SIZE_PATTERN` | Size values | `"8px"`, `"1rem"`, `"50%"` |
| `CSS_DURATION_PATTERN` | Duration values | `"150ms"`, `"0.3s"` |

#### Admin Request Schemas

For theme creation/update endpoints (admin only):

```python
class ThemeCreateRequest(BaseModel):
    id: str              # kebab-case, e.g., "my-theme-dark"
    name: str            # Display name
    mode: "dark" | "light"
    author: str = "Tesslate"
    version: str = "1.0.0"
    description: str | None
    theme_json: ThemeJsonSchema  # Full validated theme
    is_default: bool = False
    is_active: bool = True
    sort_order: int = 99

class ThemeUpdateRequest(BaseModel):
    # All fields optional for partial updates
    name: str | None
    mode: "dark" | "light" | None
    theme_json: ThemeJsonSchema | None
    ...
```

### Frontend Validation (TypeScript)

**File**: `app/src/types/theme.ts`

Runtime validation prevents malformed themes from crashing the frontend:

```typescript
import { isValidTheme, validateTheme, DEFAULT_FALLBACK_THEME } from '../types/theme';

// Simple boolean check
if (isValidTheme(theme)) {
  applyThemePreset(theme);
} else {
  applyThemePreset(DEFAULT_FALLBACK_THEME);
}

// Get detailed validation result
const { isValid, error } = validateTheme(theme);
if (!isValid) {
  console.error('Theme validation failed:', error);
}
```

The frontend validation checks:

- Top-level fields (`id`, `name`, `mode`)
- All nested color structures (sidebar, input, scrollbar, code, status, shadow)
- Typography, spacing, and animation objects
- All required properties are non-empty strings

## Seed Script Usage

**File**: `scripts/seed/seed_themes.py`

### Basic Usage

```bash
# From project root, connects to Docker postgres on localhost:5432
python scripts/seed/seed_themes.py
```

### Custom Database URL

```bash
DATABASE_URL="postgresql+asyncpg://user:password@host:5432/dbname" \
  python scripts/seed/seed_themes.py
```

### What the Script Does

1. Connects to the database
2. Reads all `*.json` files from `scripts/themes/`
3. For each theme file:
   - Extracts metadata (id, name, mode, author, etc.)
   - Separates theme_json (colors, typography, spacing, animation)
   - Uses UPSERT to insert or update the theme
4. Sets `is_default=true` for `default-dark` and `default-light`
5. Assigns sort_order based on predefined values

### Sort Order

The seed script assigns sort order based on theme base name:

| Theme | Sort Order |
|-------|------------|
| default-dark/light | 0, 1 |
| midnight | 2 |
| ocean | 3 |
| forest | 4 |
| rose | 5 |
| sunset | 6 |
| (others) | 99 |

To customize sort order for new themes, modify the `sort_orders` dict in `seed_themes.py`.

## Troubleshooting

### Theme Not Appearing in UI

**Problem**: New theme doesn't show up in the theme picker.

**Solutions**:

1. **Check if seeded**: Run the seed script and verify success message
2. **Check is_active**: Ensure the theme has `is_active = true` in the database
3. **Check validation**: Theme JSON may have validation errors (check backend logs)
4. **Clear cache**: Hard refresh the frontend (Ctrl+Shift+R)

```sql
-- Check themes in database
SELECT id, name, is_active FROM themes;
```

### Theme Validation Failed

**Problem**: Backend logs show "Theme validation failed" warnings.

**Solutions**:

1. Check all required fields are present
2. Verify color format (use hex, rgb, rgba, hsl, hsla, or transparent)
3. Verify RGB strings use "R, G, B" format
4. Check for typos in property names (they are case-sensitive)

```python
# Get detailed validation errors
from orchestrator.app.schemas_theme import get_theme_validation_errors
errors = get_theme_validation_errors(theme_json)
print(errors)
```

### CSS Variables Not Applied

**Problem**: Theme loads but colors don't change.

**Solutions**:

1. Verify `applyThemePreset()` is called after theme selection
2. Check browser dev tools for CSS variable values on `:root`
3. Ensure components use `var(--variable-name)` not hardcoded colors

### Theme Fallback Being Used

**Problem**: Console shows "using fallback theme" even when themes exist.

**Solutions**:

1. Check API is accessible: `curl http://localhost:8000/api/themes`
2. Check for network errors in browser console
3. Verify database has themes seeded

### Database Migration Required

**Problem**: Seed script fails with "themes table doesn't exist".

**Solution**: Run Alembic migrations first:

```bash
# Docker
docker exec tesslate-orchestrator alembic upgrade head

# Kubernetes
kubectl exec -n tesslate deployment/tesslate-backend -- alembic upgrade head
```

### Theme Toggle Not Working

**Problem**: Toggle button doesn't switch between dark/light.

**Cause**: The toggle looks for a theme with the opposite mode suffix.

**Solution**: Ensure you have both variants:
- `my-theme-dark` (mode: "dark")
- `my-theme-light` (mode: "light")

If only one variant exists, toggle falls back to `default-dark` or `default-light`.

## Related Files

| File | Purpose |
|------|---------|
| `orchestrator/app/routers/themes.py` | Theme API endpoints |
| `orchestrator/app/schemas_theme.py` | Pydantic validation schemas |
| `orchestrator/app/models.py` | Theme database model |
| `app/src/theme/ThemeContext.tsx` | React context provider |
| `app/src/theme/themePresets.ts` | Theme loading and application |
| `app/src/types/theme.ts` | TypeScript types and validation |
| `scripts/seed/seed_themes.py` | Database seeding script |
| `scripts/themes/*.json` | Theme definition files |
| `orchestrator/alembic/versions/0003_add_themes_table.py` | Database migration |
