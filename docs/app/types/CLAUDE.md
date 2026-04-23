# Frontend Type Definitions

**Purpose**: TypeScript types and runtime validation for the OpenSail frontend, with particular focus on theme types that must stay in sync with the backend.

## When to Load This Context

Load this context when:
- Adding new theme properties
- Debugging theme loading failures
- Working with type validation errors
- Syncing types between frontend and backend

## Key Files

| File | Purpose |
|------|---------|
| `app/src/types/theme.ts` | Theme types and runtime validation |
| `app/src/lib/api.ts` | API response types (source of truth) |
| `orchestrator/app/schemas_theme.py` | Backend Pydantic schemas (must sync) |

## Related Contexts

- **`docs/app/CLAUDE.md`**: Frontend overview
- **`docs/app/state/CLAUDE.md`**: Theme context and state management
- **`docs/orchestrator/services/themes.md`**: Theme API endpoints

## Theme Type Structure

### Type Hierarchy

```
Theme
├── id: string
├── name: string
├── mode: 'dark' | 'light'
├── author?: string
├── version?: string
├── description?: string
├── colors: ThemeColors
│   ├── primary, primaryHover, primaryRgb
│   ├── accent, background, surface, surfaceHover
│   ├── text, textMuted, textSubtle
│   ├── border, borderHover
│   ├── sidebar: SidebarColors
│   ├── input: InputColors
│   ├── scrollbar: ScrollbarColors
│   ├── code: CodeColors
│   ├── status: StatusColors
│   └── shadow: ShadowValues
├── typography: ThemeTypography
│   ├── fontFamily, fontFamilyMono
│   ├── fontSizeBase, lineHeight
├── spacing: ThemeSpacing
│   ├── radiusSmall, radiusMedium
│   ├── radiusLarge, radiusXl
└── animation: ThemeAnimation
    ├── durationFast, durationNormal, durationSlow
    └── easing
```

### Type Exports

Types are re-exported from `api.ts` to centralize definitions:

```typescript
// app/src/types/theme.ts
export type {
  Theme,
  ThemeColors,
  ThemeTypography,
  ThemeSpacing,
  ThemeAnimation,
  ThemeListItem,
} from '../lib/api';
```

### Loading State Types

```typescript
export type ThemeLoadingState = 'idle' | 'loading' | 'success' | 'error';

export interface ThemeState {
  themes: Map<string, Theme>;
  loadingState: ThemeLoadingState;
  error: string | null;
  lastUpdated: number | null;
}
```

## Runtime Validation

### Why Runtime Validation?

TypeScript types are compile-time only. Runtime validation prevents:
- Crashes from malformed API responses
- Silent failures when themes are missing properties
- Undefined behavior when applying incomplete theme CSS

### Basic Validation

```typescript
import { isValidTheme, Theme } from '../types/theme';

const theme = await themesApi.get('my-theme');
if (isValidTheme(theme)) {
  applyThemePreset(theme);  // Safe to use
} else {
  console.error('Invalid theme, using fallback');
  applyThemePreset(DEFAULT_FALLBACK_THEME);
}
```

### Detailed Validation with Error Messages

```typescript
import { validateTheme } from '../types/theme';

const { isValid, error } = validateTheme(theme);
if (!isValid) {
  console.error('Theme validation failed:', error);
  // error: "Theme colors structure is invalid"
}
```

### Validation Functions

| Function | Purpose |
|----------|---------|
| `isValidTheme(theme)` | Returns boolean, fast check |
| `validateTheme(theme)` | Returns `{ isValid, error? }`, detailed |
| `isNonEmptyString(value)` | Internal helper |
| `hasStringProps(obj, props)` | Internal helper |

## Default Fallback Theme

When API themes fail to load or validate, use the hardcoded fallback:

```typescript
import { DEFAULT_FALLBACK_THEME } from '../types/theme';

function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(DEFAULT_FALLBACK_THEME);

  useEffect(() => {
    loadTheme().catch(() => {
      // Already using fallback, no action needed
    });
  }, []);

  return <ThemeContext.Provider value={theme}>{children}</ThemeContext.Provider>;
}
```

The fallback theme is a complete dark theme with all required properties.

## Keeping Types in Sync

### Backend → Frontend Sync

The source of truth is `orchestrator/app/schemas_theme.py`. When adding new theme properties:

1. **Add to Pydantic schema**:
```python
# orchestrator/app/schemas_theme.py
class ThemeColors(BaseModel):
    primary: str
    newProperty: str  # Add here first
```

2. **Add to TypeScript types**:
```typescript
// app/src/lib/api.ts
export interface ThemeColors {
  primary: string;
  newProperty: string;  // Then here
}
```

3. **Add to validation**:
```typescript
// app/src/types/theme.ts
function isValidThemeColors(value: unknown): boolean {
  const requiredColorProps = [
    'primary',
    'newProperty',  // And here
  ];
  // ...
}
```

4. **Add to fallback theme**:
```typescript
// app/src/types/theme.ts
export const DEFAULT_FALLBACK_THEME: Theme = {
  colors: {
    primary: '#F89521',
    newProperty: '#000000',  // And here
  },
  // ...
};
```

### Validation Coverage

Each nested object has its own validator:

```typescript
// Colors sub-objects
isValidSidebarColors()   // sidebar.background, text, border, hover, active
isValidInputColors()     // input.background, border, borderFocus, text, placeholder
isValidScrollbarColors() // scrollbar.thumb, thumbHover, track
isValidCodeColors()      // code.inlineBackground, inlineText, blockBackground, etc.
isValidStatusColors()    // status.error, errorRgb, success, successRgb, etc.
isValidShadowValues()    // shadow.small, medium, large

// Top-level sections
isValidThemeColors()     // All color properties + nested objects
isValidTypography()      // fontFamily, fontFamilyMono, fontSizeBase, lineHeight
isValidSpacing()         // radiusSmall, radiusMedium, radiusLarge, radiusXl
isValidAnimation()       // durationFast, durationNormal, durationSlow, easing
```

## Usage in ThemeContext

```typescript
// app/src/theme/ThemeContext.tsx
import { isValidTheme, DEFAULT_FALLBACK_THEME } from '../types/theme';

async function loadTheme(themeId: string) {
  try {
    const theme = await themesApi.get(themeId);

    if (!isValidTheme(theme)) {
      console.warn(`Theme ${themeId} failed validation, using fallback`);
      return DEFAULT_FALLBACK_THEME;
    }

    return theme;
  } catch (error) {
    console.error('Failed to load theme:', error);
    return DEFAULT_FALLBACK_THEME;
  }
}
```

## Common Issues

### Issue: Theme Partially Applies

**Symptom**: Some CSS variables undefined, causing visual glitches

**Cause**: Theme missing nested properties (e.g., `colors.sidebar.hover`)

**Solution**: Use `validateTheme()` to identify missing properties:
```typescript
const { isValid, error } = validateTheme(theme);
// error: "Theme colors structure is invalid"
```

### Issue: New Theme Property Not Working

**Symptom**: Added property to API response but frontend doesn't use it

**Cause**: Property not in TypeScript interface

**Solution**: Update `api.ts` types and validation in `types/theme.ts`

### Issue: Theme Validation Too Strict

**Symptom**: Valid themes rejected due to optional properties

**Solution**: Validation only checks required properties. Optional properties (like `author`, `description`) are not validated.

## TesslateConfig Types

**File**: `app/src/types/tesslateConfig.ts`

Types for the `.tesslate/config.json` project configuration file, used by the Project Setup wizard and `setupApi`.

### Type Hierarchy

```
TesslateConfig
├── apps: Record<string, AppConfig>
│   └── AppConfig
│       ├── directory: string           # Working directory
│       ├── port: number | null         # Listening port
│       ├── start: string               # Start command
│       ├── env: Record<string, string> # Environment variables
│       ├── x?: number                  # Graph X position
│       └── y?: number                  # Graph Y position
├── infrastructure: Record<string, InfraConfig>
│   └── InfraConfig
│       ├── image: string               # Docker image
│       ├── port: number                # Service port
│       ├── x?: number                  # Graph X position
│       └── y?: number                  # Graph Y position
└── primaryApp: string                  # Name of the primary app
```

### Response Types

```typescript
// GET /api/projects/{slug}/setup-config
interface TesslateConfigResponse extends TesslateConfig {
  exists: boolean;  // Whether config file was found
}

// POST /api/projects/{slug}/setup-config
interface SetupConfigSyncResponse {
  container_ids: string[];           // Created container IDs
  primary_container_id: string | null; // Primary app's container ID
}
```

### Usage

```typescript
import type { TesslateConfig, AppConfig, InfraConfig } from '../types/tesslateConfig';

const config: TesslateConfig = {
  apps: {
    frontend: { directory: '.', port: 3000, start: 'npm run dev', env: {} },
    backend: { directory: 'api/', port: 8000, start: 'python -m uvicorn main:app', env: {} },
  },
  infrastructure: {
    postgres: { image: 'postgres:16', port: 5432 },
  },
  primaryApp: 'frontend',
};
```

## Type Files Overview

```
app/src/
├── types/
│   ├── theme.ts           # Theme types + validation
│   └── tesslateConfig.ts  # TesslateConfig, AppConfig, InfraConfig
├── lib/
│   └── api.ts             # API types (source of truth)
└── theme/
    └── ThemeContext.tsx   # Theme state management
```

## Testing Validation

```typescript
import { isValidTheme, validateTheme, DEFAULT_FALLBACK_THEME } from '../types/theme';

describe('Theme validation', () => {
  it('validates complete themes', () => {
    expect(isValidTheme(DEFAULT_FALLBACK_THEME)).toBe(true);
  });

  it('rejects incomplete themes', () => {
    const { isValid, error } = validateTheme({ id: 'test' });
    expect(isValid).toBe(false);
    expect(error).toContain('mode');
  });

  it('rejects non-objects', () => {
    expect(isValidTheme(null)).toBe(false);
    expect(isValidTheme('string')).toBe(false);
    expect(isValidTheme(123)).toBe(false);
  });
});
```
