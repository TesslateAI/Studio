# Node.js Dependency Management in Docker

## Overview

This document explains how OpenSail handles Node.js dependencies (`node_modules`) in Docker containers across all platforms.

**Source File**: `orchestrator/app/services/base_config_parser.py`

---

## Design Principle: Never Copy node_modules

OpenSail **never copies `node_modules`** between filesystems. Instead, dependencies are always installed fresh inside the container on first boot.

**Why?**

1. **Cross-platform safety**: Copying `node_modules` between Windows, macOS, and Linux breaks symlinks in `node_modules/.bin/`
2. **Correctness**: Native addons compiled on one OS won't work on another
3. **Simplicity**: No detection logic, no repair scripts, no platform-specific workarounds
4. **Speed**: Modern package managers (bun, pnpm) install from cache in seconds

---

## How It Works

### 1. Base Cache Preparation

When a marketplace base is cached (e.g., `nextjs-16`), dependencies are installed inside a Linux container and stored in the `tesslate-base-cache` Docker volume.

### 2. Project Creation (File Copy)

When a user creates a project from a base, the orchestrator copies files from cache to the project volume but **skips generated directories**:

```python
# orchestrator/app/routers/projects.py
_SKIP_DIRS = {".git", "node_modules", ".next", "__pycache__", ".venv", "dist", "build"}

for item in os.listdir(cached_base_path):
    if item in _SKIP_DIRS:
        continue
    # Copy source files, configs, package.json, lockfiles...
```

This means `package.json` and lockfiles (e.g., `bun.lock`, `pnpm-lock.yaml`, `yarn.lock`, `package-lock.json`) are copied, but `node_modules` is not.

### 3. Container Startup (Dependency Install)

On container startup, the startup command checks for missing dependencies and installs them:

```bash
if [ -f "package.json" ] && [ ! -d "node_modules" ]; then
  echo "[TESSLATE] Installing dependencies..." &&
  if [ -f "bun.lock" ] || [ -f "bun.lockb" ]; then bun install;
  elif [ -f "pnpm-lock.yaml" ]; then pnpm install;
  elif [ -f "yarn.lock" ]; then yarn install;
  else npm install;
  fi;
fi
```

This runs **before** the dev server starts. It:
- Detects the correct package manager from the lockfile
- Only runs if `node_modules` doesn't exist (no-op on subsequent starts)
- Works identically on Docker and Kubernetes

### 4. Subsequent Starts

After the first boot installs dependencies, `node_modules` persists on the project's Docker volume. Future container restarts skip the install step entirely (the `[ ! -d "node_modules" ]` check passes immediately).

---

## Package Manager Detection

The startup script auto-detects the package manager from lockfiles:

| Lockfile | Package Manager | Install Command |
|----------|----------------|-----------------|
| `bun.lock` or `bun.lockb` | Bun | `bun install` |
| `pnpm-lock.yaml` | pnpm | `pnpm install` |
| `yarn.lock` | Yarn | `yarn install` |
| `package-lock.json` (default) | npm | `npm install` |

---

## Directories Excluded from Copy

These directories are never copied from base cache to project volume:

| Directory | Why Excluded |
|-----------|-------------|
| `node_modules` | Platform-specific, installed fresh in container |
| `.next` | Build output, regenerated on dev server start |
| `__pycache__` | Python bytecode, regenerated automatically |
| `.venv` | Python virtual env, platform-specific |
| `dist` | Build output |
| `build` | Build output |
| `.git` | Version control metadata |

---

## Cross-Platform Behavior

| Host OS | Docker Engine | Dependencies | Notes |
|---------|---------------|-------------|-------|
| Linux | Native | Installed in container | Works perfectly |
| macOS | Docker Desktop | Installed in container | Works perfectly |
| Windows | Docker Desktop | Installed in container | Works perfectly |
| Windows | WSL2 Backend | Installed in container | Works perfectly |

Because dependencies are always installed inside the Linux container, there are **no platform-specific issues**.

---

## Performance

| Scenario | Time |
|----------|------|
| First start (bun install) | 5-15 seconds |
| First start (npm install) | 15-60 seconds |
| Subsequent starts (node_modules exists) | ~0ms (instant check) |

The devserver Docker image pre-caches common packages, making first installs faster.

---

## Troubleshooting

### Dependencies Not Installing

1. **Check container logs** for `[TESSLATE] Installing dependencies...` message
2. **Verify lockfile exists**: The project must have a lockfile (`bun.lock`, `package-lock.json`, etc.)
3. **Check TESSLATE.md**: If the base has a custom start command, it must include the dep install prefix

### Wrong Package Manager

If the wrong package manager is used, ensure the correct lockfile is in the project root. The detection order is: bun → pnpm → yarn → npm (default).

### Manual Install

If you need to manually install dependencies inside a running container:

```bash
# Access the container
docker exec -it <container-name> sh

# Install with the appropriate package manager
bun install    # or npm install, yarn install, pnpm install
```

---

## Related Documentation

- [Docker Setup Guide](../../guides/docker-setup.md)
- [Base Config Parser](../../orchestrator/services/base-config-parser.md)
- [Dockerfiles](dockerfiles.md)
