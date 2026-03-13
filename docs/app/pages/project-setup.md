# Project Setup Page

**File**: `app/src/pages/ProjectSetup.tsx`
**Route**: `/project/:slug/setup`
**Layout**: Standalone (no sidebar)

## Purpose

The Project Setup page is a wizard for configuring `.tesslate/config.json` when a newly created or imported project requires setup. It provides two modes: AI-powered automatic analysis and manual configuration.

## When It Appears

The Dashboard navigates to this page when project creation or import returns `container_id === 'needs_setup'`. This happens for projects that lack a `.tesslate/config.json` file (e.g., imported repos, custom templates without pre-configured containers).

## Key Features

### 1. Tab Switcher (Agent / Manual)
- **Agent Setup**: AI scans project files to detect frameworks, ports, and startup commands automatically
- **Manual Setup**: User configures apps and infrastructure by hand using the `ServiceConfigForm` component

### 2. AI Project Analysis
When using Agent Setup, clicking "Analyze Project" calls `setupApi.analyzeProject(slug)` which:
- Scans the project's file system for known frameworks (Next.js, Vite, FastAPI, etc.)
- Detects port numbers from configuration files
- Infers start commands from `package.json`, `Procfile`, etc.
- Returns a `TesslateConfig` structure with detected apps and infrastructure

### 3. Configuration Editing
After analysis (or immediately in Manual mode), the `ServiceConfigForm` component renders, allowing users to:
- Add, remove, and edit app services (name, directory, port, start command)
- Set a primary app (determines which container is previewed by default)
- Add infrastructure services from a catalog (PostgreSQL, Redis, MySQL, MongoDB, MinIO)
- Manage environment variables per app

### 4. Existing Config Detection
On mount, the page checks for an existing `.tesslate/config.json` via `setupApi.getConfig(slug)`. If found, it pre-populates the form and shows a "Config detected" badge.

### 5. Skip Setup
Users can skip setup entirely, which saves a minimal default config (`sleep infinity` workspace) and navigates to the builder.

## Component Structure

```
ProjectSetup
├── Header
│   ├── Back button (→ Dashboard)
│   ├── Page title + project slug
│   └── "Config detected" badge (conditional)
│
├── Tab Switcher
│   ├── Agent Setup tab
│   └── Manual Setup tab
│
├── Content Area
│   ├── Agent Tab
│   │   ├── Analyze CTA (pre-analysis)
│   │   └── ServiceConfigForm (post-analysis)
│   └── Manual Tab
│       └── ServiceConfigForm
│
└── Bottom Bar
    ├── "Skip setup" link
    └── "Next" save button
```

## State Management

```typescript
type Tab = 'agent' | 'manual';

const [activeTab, setActiveTab] = useState<Tab>('agent');
const [config, setConfig] = useState<TesslateConfig>(DEFAULT_CONFIG);
const [isAnalyzing, setIsAnalyzing] = useState(false);
const [analysisDone, setAnalysisDone] = useState(false);
const [isSaving, setIsSaving] = useState(false);
const [existingConfig, setExistingConfig] = useState(false);
```

## Data Flow

### Loading Existing Config

```typescript
useEffect(() => {
  if (!slug) return;
  setupApi.getConfig(slug).then(res => {
    if (res.exists) {
      setConfig({ apps: res.apps, infrastructure: res.infrastructure, primaryApp: res.primaryApp });
      setExistingConfig(true);
      setAnalysisDone(true);
    }
  }).catch(() => {});
}, [slug]);
```

### Analyzing Project

```typescript
const result = await setupApi.analyzeProject(slug);
if (result.apps && Object.keys(result.apps).length > 0) {
  setConfig({
    apps: result.apps,
    infrastructure: result.infrastructure || {},
    primaryApp: result.primaryApp || Object.keys(result.apps)[0],
  });
  setAnalysisDone(true);
}
```

### Saving Configuration

```typescript
const result = await setupApi.saveConfig(slug, config);
// Navigate to builder with the primary container
if (result.primary_container_id) {
  navigate(`/project/${slug}/builder?container=${result.primary_container_id}`);
} else if (result.container_ids.length > 0) {
  navigate(`/project/${slug}/builder?container=${result.container_ids[0]}`);
} else {
  navigate(`/project/${slug}/builder`);
}
```

## API Endpoints Used

```typescript
// Get existing config
GET /api/projects/{slug}/setup-config
// Response: TesslateConfigResponse { exists, apps, infrastructure, primaryApp }

// Save config (creates/updates containers)
POST /api/projects/{slug}/setup-config
// Body: TesslateConfig { apps, infrastructure, primaryApp }
// Response: SetupConfigSyncResponse { container_ids, primary_container_id }

// AI-powered project analysis
POST /api/projects/{slug}/analyze
// Response: TesslateConfigResponse { exists, apps, infrastructure, primaryApp }
```

## Validation

Before saving, the page validates:
1. At least one app is defined
2. At least one app has a non-empty start command

## Navigation Flow

```
Dashboard
  └─ Create/Import project
      └─ Task returns 'needs_setup'
          └─ /project/:slug/setup
              ├─ Agent analyzes → review config → save → /project/:slug/builder
              ├─ Manual config → save → /project/:slug/builder
              └─ Skip → save default → /project/:slug/builder
```

## Related Components

- **`ServiceConfigForm`**: Reusable form component for editing `TesslateConfig`
- **`setupApi`**: API client module for setup-config and analyze endpoints

## Related Documentation

- **Dashboard**: `docs/app/pages/dashboard.md`
- **Project Builder**: `docs/app/pages/project-builder.md`
- **Setup API**: `docs/app/api/setup-api.md`
- **TesslateConfig Types**: `docs/app/types/CLAUDE.md`
