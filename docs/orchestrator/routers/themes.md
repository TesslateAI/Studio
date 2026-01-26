# Themes Router

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/themes.py`

The themes router serves theme configuration data for the frontend UI. Themes are stored in the database and served via these public endpoints.

## Overview

This is a **public API** - no authentication required. This design allows themes to load before user login, ensuring the UI can display correctly during the authentication flow.

Themes define the visual appearance of the Tesslate Studio interface including:
- Color palette (primary, accent, background, text, etc.)
- Typography (font families, sizes, line height)
- Spacing (border radius values)
- Animation timing (duration, easing)

## Base Path

All endpoints are mounted at `/api/themes`

## Response Schemas

### ThemeResponse

Full theme data including all JSON sections. Used when the frontend needs to apply a theme.

```python
class ThemeResponse(BaseModel):
    id: str                      # Unique theme identifier (e.g., "dark-default")
    name: str                    # Display name (e.g., "Dark Default")
    mode: str                    # "dark" or "light"
    author: Optional[str]        # Theme author (default: "Tesslate")
    version: Optional[str]       # Theme version (e.g., "1.0.0")
    description: Optional[str]   # Theme description
    colors: dict                 # Color palette
    typography: dict             # Font settings
    spacing: dict                # Border radius values
    animation: dict              # Animation timing
```

### ThemeListItem

Lightweight theme info for listing themes. Does not include the full JSON sections, reducing payload size.

```python
class ThemeListItem(BaseModel):
    id: str                      # Unique theme identifier
    name: str                    # Display name
    mode: str                    # "dark" or "light"
    author: Optional[str]        # Theme author
    description: Optional[str]   # Theme description
```

## Endpoints

### List Themes (Lightweight)

```
GET /api/themes
```

Returns a lightweight list of all active themes. Use this for theme selection dropdowns where you don't need the full theme JSON.

**Response**: `List[ThemeListItem]`

**Example Response**:
```json
[
  {
    "id": "dark-default",
    "name": "Dark Default",
    "mode": "dark",
    "author": "Tesslate",
    "description": "The default dark theme"
  },
  {
    "id": "light-default",
    "name": "Light Default",
    "mode": "light",
    "author": "Tesslate",
    "description": "The default light theme"
  }
]
```

**Database Query**:
- Filters: `is_active = true`
- Order: `sort_order ASC, name ASC`

---

### List Themes (Full JSON)

```
GET /api/themes/full
```

Returns all active themes with full JSON data. Use this for theme picker previews where you need to apply theme colors.

**Response**: `List[ThemeResponse]`

**Example Response**:
```json
[
  {
    "id": "dark-default",
    "name": "Dark Default",
    "mode": "dark",
    "author": "Tesslate",
    "version": "1.0.0",
    "description": "The default dark theme",
    "colors": {
      "primary": "#f89521",
      "primaryHover": "#ffa940",
      "primaryRgb": "248, 149, 33",
      "accent": "#1a1a2e",
      "background": "#0a0a0f",
      "surface": "#111118",
      "surfaceHover": "#18181f",
      "text": "#ffffff",
      "textMuted": "#a0a0a8",
      "textSubtle": "#6b6b75",
      "border": "#2a2a35",
      "borderHover": "#3a3a45",
      "sidebar": {
        "background": "#0d0d12",
        "text": "#e0e0e5",
        "border": "#1f1f28",
        "hover": "#18181f",
        "active": "#1f1f28"
      },
      "input": {
        "background": "#0f0f14",
        "border": "#2a2a35",
        "borderFocus": "#f89521",
        "text": "#ffffff",
        "placeholder": "#6b6b75"
      },
      "scrollbar": {
        "thumb": "#2a2a35",
        "thumbHover": "#3a3a45",
        "track": "transparent"
      },
      "code": {
        "inlineBackground": "#1a1a22",
        "inlineText": "#f89521",
        "blockBackground": "#0d0d12",
        "blockBorder": "#2a2a35",
        "blockText": "#e0e0e5"
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
        "medium": "0 4px 6px rgba(0, 0, 0, 0.4)",
        "large": "0 10px 15px rgba(0, 0, 0, 0.5)"
      }
    },
    "typography": {
      "fontFamily": "Inter, system-ui, sans-serif",
      "fontFamilyMono": "JetBrains Mono, monospace",
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
]
```

**Note**: Validation is performed on each theme but is non-blocking. Invalid themes are still returned with a warning logged server-side.

---

### Get Single Theme

```
GET /api/themes/{theme_id}
```

Returns a single theme by ID with full JSON data.

**Path Parameters**:
- `theme_id` (string, required): The unique theme identifier

**Response**: `ThemeResponse`

**Example Request**:
```
GET /api/themes/dark-default
```

**Example Response**:
```json
{
  "id": "dark-default",
  "name": "Dark Default",
  "mode": "dark",
  "author": "Tesslate",
  "version": "1.0.0",
  "description": "The default dark theme",
  "colors": { ... },
  "typography": { ... },
  "spacing": { ... },
  "animation": { ... }
}
```

**Errors**:
- `404 Not Found`: Theme with given ID does not exist or is not active

---

### Get Default Theme by Mode

```
GET /api/themes/default/{mode}
```

Returns the default theme for a given mode (dark or light). Useful for initial app load when no user preference is set.

**Path Parameters**:
- `mode` (string, required): Either `dark` or `light`

**Response**: `ThemeResponse`

**Example Request**:
```
GET /api/themes/default/dark
```

**Logic**:
1. First, look for a theme where `mode = {mode}`, `is_default = true`, `is_active = true`
2. If no default found, fall back to the first active theme of that mode (ordered by `sort_order`)
3. If no theme exists for the mode, return 404

**Errors**:
- `400 Bad Request`: Mode must be 'dark' or 'light'
- `404 Not Found`: No theme available for the requested mode

## Validation

Theme JSON is validated using Pydantic schemas defined in `schemas_theme.py`. Validation is **non-blocking** - if a theme fails validation, a warning is logged but the theme is still returned to the frontend.

### Validation Schema Structure

```python
class ThemeJsonSchema(BaseModel):
    colors: ThemeColors         # Complete color palette
    typography: ThemeTypography # Font settings
    spacing: ThemeSpacing       # Border radius values
    animation: ThemeAnimation   # Animation timing
```

### Nested Color Schemas

- `SidebarColors`: sidebar background, text, border, hover, active
- `InputColors`: input background, border, borderFocus, text, placeholder
- `ScrollbarColors`: thumb, thumbHover, track
- `CodeColors`: inline and block code styling
- `StatusColors`: error, success, warning, info (with RGB variants)
- `ShadowValues`: small, medium, large shadow definitions

### Validation Patterns

The schema validates CSS values using regex patterns:

| Pattern | Valid Examples |
|---------|----------------|
| CSS Color | `#f89521`, `rgb(248, 149, 33)`, `rgba(0, 0, 0, 0.5)`, `transparent` |
| RGB String | `248, 149, 33` |
| CSS Size | `8px`, `1rem`, `50%` |
| CSS Duration | `150ms`, `0.3s` |

### Validation Helper Functions

```python
from app.schemas_theme import validate_theme_json, get_theme_validation_errors

# Returns tuple: (is_valid, error_message, validated_schema)
is_valid, error, schema = validate_theme_json(theme.theme_json)
if not is_valid:
    logger.warning(f"Theme validation failed: {error}")

# Get detailed error list
errors = get_theme_validation_errors(theme.theme_json)
# Returns: ["colors.primary: must be a valid CSS color", ...]
```

## Database Model

Themes are stored in the `themes` table with the following columns:

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(100) | Primary key, e.g., "dark-default" |
| `name` | VARCHAR(100) | Display name |
| `mode` | VARCHAR(10) | "dark" or "light" |
| `author` | VARCHAR(100) | Theme author |
| `version` | VARCHAR(20) | Version string |
| `description` | VARCHAR(500) | Theme description |
| `theme_json` | JSONB | Full theme configuration |
| `is_default` | BOOLEAN | Whether this is the default for its mode |
| `is_active` | BOOLEAN | Whether the theme is available |
| `sort_order` | INTEGER | Display order in listings |

## Example Workflows

### Initial App Load

1. Frontend checks localStorage for saved theme preference
2. If no preference, call `GET /api/themes/default/dark` (or detect system preference)
3. Apply returned theme to CSS variables
4. User is presented with styled login page

### Theme Picker

1. Call `GET /api/themes/full` to get all themes with colors
2. Display theme cards with preview colors from each theme's `colors` object
3. User clicks theme to preview
4. On confirm, save theme ID to localStorage and apply theme

### Switching Theme Mode

1. User toggles dark/light mode
2. Call `GET /api/themes/default/{newMode}`
3. Apply returned theme
4. Save preference to localStorage

## Frontend Integration

The frontend theme context (`app/src/theme/ThemeContext.tsx`) consumes these endpoints:

```typescript
// Fetch all themes for picker
const response = await fetch('/api/themes/full');
const themes: ThemePreset[] = await response.json();

// Fetch default theme
const response = await fetch(`/api/themes/default/${mode}`);
const theme: ThemePreset = await response.json();

// Fetch specific theme
const response = await fetch(`/api/themes/${themeId}`);
const theme: ThemePreset = await response.json();
```

## Related Files

- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/themes.py` - Router implementation
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/schemas_theme.py` - Pydantic validation schemas
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/models.py` - Theme database model
- `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/theme/ThemeContext.tsx` - Frontend theme context
- `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/theme/themePresets.ts` - Frontend theme types
- `c:/Users/Smirk/Downloads/Tesslate-Studio/scripts/seed/seed_themes.py` - Database seed script

## Related Contexts

- [models/CLAUDE.md](../models/CLAUDE.md) - Database model documentation
- [services/CLAUDE.md](../services/CLAUDE.md) - Service layer patterns
- [../app/CLAUDE.md](../../app/CLAUDE.md) - Frontend integration
