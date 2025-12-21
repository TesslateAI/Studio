# Dependency Installation Map

Complete map of everywhere dependency installation (npm install, pip install, go mod) happens in the codebase.

---

## Overview Flow

```
User adds container to project
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 1: File Initialization (when container added to graph)  │
│  Location: container_initializer.py → kubernetes_orchestrator  │
│  Trigger: POST /api/projects/{slug}/containers                 │
│                                                                 │
│  install_deps=True → generate_git_clone_script()               │
│  ├── if package.json → npm install                             │
│  ├── if requirements.txt → pip install                         │
│  └── if go.mod → go mod download                               │
│                                                                 │
│  TIME: ~45 seconds for Next.js                                 │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 2: Container Start (when user clicks Start)             │
│  Location: kubernetes_orchestrator.py → helpers.py             │
│  Trigger: POST /api/projects/{slug}/containers/{id}/start      │
│                                                                 │
│  Deployment command (HARDCODED):                                │
│  "cd {dir} && ([ -d node_modules ] || npm install) && tmux..." │
│                                                                 │
│  ⚠️  ONLY checks node_modules, NOT pip/go!                     │
│  ⚠️  Should be SKIPPED if Phase 1 ran correctly                │
│                                                                 │
│  TIME: <1 second (skipped because node_modules exists)         │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 3: Agent Runtime (when AI modifies package.json)        │
│  Location: stream_agent.py                                     │
│  Trigger: Agent writes to package.json                         │
│                                                                 │
│  Automatically runs npm install if package.json was modified   │
│                                                                 │
│  TIME: Varies based on new dependencies                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Detailed File Locations

### 1. File Initialization (PHASE 1)

**Trigger Chain:**
```
POST /api/projects/{slug}/containers
    → routers/projects.py (add_container endpoint)
    → container_initializer.py:133 (initialize_container)
    → kubernetes_orchestrator.py:267 (initialize_container_files)
    → kubernetes_orchestrator.py:356 (generate_git_clone_script)
    → helpers.py:688 (generate_git_clone_script function)
```

**File: `orchestrator/app/services/orchestration/kubernetes_orchestrator.py`**
```python
# Line 356-361
script = generate_git_clone_script(
    git_url=git_url,
    branch=branch,
    target_dir=f"/app/{container_directory}",
    install_deps=True  # ← THIS TRIGGERS DEPENDENCY INSTALL
)
```

**File: `orchestrator/app/services/orchestration/kubernetes/helpers.py`**
```python
# Lines 688-725
def generate_git_clone_script(
    git_url: str,
    branch: str,
    target_dir: str,
    install_deps: bool = True  # ← DEFAULT IS TRUE
) -> str:

    install_section = """
# Install dependencies based on project type
if [ -f "package.json" ]; then
    echo "[CLONE] Installing Node.js dependencies..."
    npm install --prefer-offline --no-audit 2>&1 || echo "[CLONE] npm install completed with warnings"
fi

if [ -f "requirements.txt" ]; then
    echo "[CLONE] Installing Python dependencies..."
    pip install -r requirements.txt 2>&1 || echo "[CLONE] pip install completed with warnings"
fi

if [ -f "go.mod" ]; then
    echo "[CLONE] Downloading Go modules..."
    go mod download 2>&1 || echo "[CLONE] go mod download completed with warnings"
fi
""" if install_deps else ""
```

**Multi-framework: YES** - Handles Node.js, Python, Go

---

### 2. Container Start / Deployment Command (PHASE 2)

**Trigger Chain:**
```
POST /api/projects/{slug}/containers/{id}/start
    → routers/projects.py (start_container endpoint)
    → kubernetes_orchestrator.py:397 (start_container)
    → kubernetes_orchestrator.py:503 (create_container_deployment)
    → helpers.py:262 (create_container_deployment function)
```

**File: `orchestrator/app/services/orchestration/kubernetes/helpers.py`**
```python
# Line 323 - DEPLOYMENT COMMAND
args=[f"cd {working_dir} && ([ -d node_modules ] || npm install) && tmux new-session -d -s main '{startup_command}' && exec tail -f /dev/null"],
```

**Multi-framework: NO** - Only checks `node_modules`, hardcoded to npm!

**Issues:**
- ⚠️ Inconsistent with Phase 1 (which handles all frameworks)
- ⚠️ Python/Go containers will try to run `npm install` (will fail silently due to ||)
- ⚠️ `startup_command` comes from TESSLATE.md but install is hardcoded

---

### 3. Agent Runtime (PHASE 3)

**File: `orchestrator/app/agent/stream_agent.py`**
```python
# Lines 173-193
# Run npm install if package.json was modified (K8s only)
if "package.json" in modified_files:
    logger.info("[StreamAgent] package.json modified, running npm install")
    try:
        # ... runs npm install via kubectl exec
    except Exception as e:
        logger.warning(f"[StreamAgent] npm install failed: {e}")
```

**Multi-framework: NO** - Only handles package.json/npm

---

### 4. Base Config Parser (Startup Commands)

**File: `orchestrator/app/services/base_config_parser.py`**
```python
# Lines 369-383 - DEPENDENCY INSTALLATION IN STARTUP COMMAND GENERATION
# For multi-directory projects:

'  [ ! -d "node_modules" ] && echo "[TESSLATE] Installing Node.js dependencies..." && npm install || true; '
'  [ ! -d "frontend/node_modules" ] && echo "[TESSLATE] Installing frontend dependencies..." && cd frontend && npm install && cd .. || true; '
'  echo "[TESSLATE] Installing Python dependencies..." && pip install --user -r requirements.txt || true; '
'  echo "[TESSLATE] Installing backend dependencies..." && cd backend && pip install --user -r requirements.txt && cd .. || true; '
'  echo "[TESSLATE] Downloading Go dependencies..." && go mod download || true; '
```

**Multi-framework: YES** - But only for multi-directory project structures

---

### 5. Base Cache Manager (Pre-caching)

**File: `orchestrator/app/services/base_cache_manager.py`**
```python
# Lines 221-233 - Pre-caching dependencies for bases
if framework == "node":
    commands.append("npm install --unsafe-perm")
elif framework == "python":
    commands.extend([
        ".venv/bin/pip install --upgrade pip",
        ".venv/bin/pip install -r requirements.txt"
    ])
elif framework == "go":
    commands.append("go mod download")
```

**Purpose:** Pre-cache dependencies for marketplace bases (NOT used during user container startup)

---

### 6. Tmux Session Manager (Docker Mode)

**File: `orchestrator/app/services/tmux_session_manager.py`**
```python
# Line 57 - Default install command
install_cmd = kwargs.get('install_cmd', 'npm install --silent')

# Line 79 - Full-stack frontend
f"'cd /app/frontend && npm install --silent && npm run dev -- --port {frontend_port} --host 0.0.0.0' \\; "

# Line 81 - Full-stack backend
f"'cd /app/backend && pip install -r requirements.txt --quiet && uvicorn main:app --host 0.0.0.0 --port {backend_port} --reload'"

# Line 113 - Mobile/Expo
f"'npm install --silent && npx expo start --port {port}'"

# Line 201 - Example in docstring
tmux new-session -d -s main -x 120 -y 30 'npm install --silent && npm run dev'
```

**Mode:** Docker Compose mode (local dev), NOT Kubernetes

---

### 7. Tesslate Parser (Legacy Defaults)

**File: `orchestrator/app/services/tesslate_parser.py`**
```python
# Lines 43-58 - HARDCODED FRAMEWORK DEFAULTS WITH npm install IN start_command!
FRAMEWORK_DEFAULTS = {
    "vite": TesslateConfig(
        start_command="npm install\nnpm run dev -- --host 0.0.0.0 --port 5173"
    ),
    "nextjs": TesslateConfig(
        start_command="npm install\nnpm run dev -- --hostname 0.0.0.0 --port 3000"
    ),
    "express": TesslateConfig(
        start_command="npm install\nnpm start"
    ),
    "expo": TesslateConfig(
        start_command="npm install\nnpx expo start --web"
    ),
}

# Line 182 - Default fallback
return "npm install\nnpm run dev -- --host 0.0.0.0 --port 5173"
```

**Issues:**
- ⚠️ npm install is INSIDE the start_command
- ⚠️ This means npm install runs EVERY time container starts
- ⚠️ Only Node.js frameworks, no Python/Go

---

### 8. Deployment Service (External Deploys)

**File: `orchestrator/app/services/deployment/base.py`**
```python
# Lines 208-253 - FRAMEWORK_CONFIGS for external deployment (Vercel/Netlify)
FRAMEWORK_CONFIGS = {
    "vite": {"install_command": "npm install", ...},
    "nextjs": {"install_command": "npm install", ...},
    "remix": {"install_command": "npm install", ...},
    "gatsby": {"install_command": "npm install", ...},
    "astro": {"install_command": "npm install", ...},
    "go": {"install_command": "go mod download", ...},
    "flask": {"install_command": "pip install -r requirements.txt", ...},
}
```

**Purpose:** External deployment to Vercel/Netlify/Cloudflare (NOT internal container startup)

---

### 9. Git Import (Repository Import)

**File: `orchestrator/app/routers/projects.py`**
```python
# Line 274 - When importing from GitHub/GitLab
install_deps=False  # Don't install deps during import - user can do this when they start container
```

**Behavior:** Explicitly SKIPS dependency installation during git import

---

## Summary Table

| Location | When | Multi-Framework | Actually Runs |
|----------|------|-----------------|---------------|
| `helpers.py:688` (generate_git_clone_script) | File init | ✅ Yes | ✅ Yes (~45s) |
| `helpers.py:323` (deployment command) | Container start | ❌ npm only | ⚠️ Skipped if node_modules exists |
| `stream_agent.py:173` | Agent modifies package.json | ❌ npm only | ✅ Yes |
| `base_config_parser.py:369` | Multi-dir projects | ✅ Yes | ⚠️ Depends on project structure |
| `tesslate_parser.py:43` | Legacy defaults | ❌ npm only | ⚠️ May run every start! |
| `tmux_session_manager.py` | Docker mode | ⚠️ Partial | ✅ In Docker mode |
| `base_cache_manager.py` | Base pre-caching | ✅ Yes | ✅ Background job |
| `deployment/base.py` | External deploy | ✅ Yes | ✅ Vercel/Netlify |

---

## Recommendations

### 1. Remove Hardcoded npm install from Deployment Command ✅ DONE
**File:** `helpers.py:323`
**Change:** Remove `([ -d node_modules ] || npm install) &&` from deployment args

```python
# BEFORE (line 323)
args=[f"cd {working_dir} && ([ -d node_modules ] || npm install) && tmux new-session -d -s main '{startup_command}' && exec tail -f /dev/null"],

# AFTER
args=[f"cd {working_dir} && tmux new-session -d -s main '{startup_command}' && exec tail -f /dev/null"],
```

**Reason:** Dependencies are already installed during file init. This is redundant and Node.js-only.

### 2. Fix tesslate_parser.py Defaults ✅ DONE
**File:** `tesslate_parser.py:43-58`
**Change:** Remove `npm install\n` from start_command defaults

```python
# BEFORE
start_command="npm install\nnpm run dev -- --host 0.0.0.0 --port 5173"

# AFTER
start_command="npm run dev -- --host 0.0.0.0 --port 5173"
```

**Reason:** npm install should NOT be in the startup command - it should only run during file init.

### 3. Add setup_command to TESSLATE.md Format (Future)
Allow bases to define their own setup command in TESSLATE.md:

```markdown
## Setup Command
```bash
npm install
```
```

Then parse this in `base_config_parser.py` and use it during file init instead of auto-detecting.

---

## Simplified Target Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  SINGLE PLACE: File Initialization                                 │
│  When: Container added to graph                                    │
│  How: TESSLATE.md defines setup_command OR auto-detect from files │
│                                                                    │
│  package.json    → npm install                                     │
│  requirements.txt → pip install -r requirements.txt                │
│  go.mod          → go mod download                                 │
│  Cargo.toml      → cargo fetch                                     │
│  composer.json   → composer install                                │
└────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────────────────┐
│  Container Start: Just run the dev server                         │
│  Command from TESSLATE.md: npm run dev, python app.py, etc.       │
│  NO dependency installation                                        │
└────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌────────────────────────────────────────────────────────────────────┐
│  Agent Runtime: Re-install if manifest file modified              │
│  Detect changes to: package.json, requirements.txt, go.mod, etc.  │
│  Run appropriate install command                                   │
└────────────────────────────────────────────────────────────────────┘
```
