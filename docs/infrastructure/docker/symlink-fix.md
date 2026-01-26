# Node.js Symlink Fix for Docker on Windows

## Overview

This document explains how Tesslate Studio handles broken Node.js symlinks when running Docker containers on Windows hosts.

**Source File**: `orchestrator/app/services/base_config_parser.py` (see `_fix_node_modules_symlinks_command` method)

---

## The Problem

### Why Symlinks Break

When you run Docker on Windows with bind mounts or volume copies, Unix symbolic links in `node_modules/.bin/` get corrupted. Instead of being proper symlinks, they become regular file copies of the target.

**How it happens:**

1. A base template or project has `node_modules/` with properly installed dependencies
2. Files in `node_modules/.bin/` are Unix symlinks pointing to executables in package directories (e.g., `next` -> `../next/dist/bin/next`)
3. When these files are copied through Windows filesystem (Docker Desktop volumes, file copies, etc.), symlinks become regular files
4. The copied files contain code with relative imports like `require("../server/require-hook")` that expect to be in the original symlink location

### Symptoms

When symlinks are broken, you will see errors like:

```
Error: Cannot find module '../server/require-hook'
  at node_modules/.bin/next:4:12
```

Or more generally:
- `npm run dev` fails immediately
- Executables in `node_modules/.bin/` crash with module resolution errors
- `npx` commands fail to run properly

### Why This Specifically Affects Windows Docker

- **Linux Docker**: Symlinks are preserved natively
- **macOS Docker**: Symlinks are preserved via gRPC FUSE mounts
- **Windows Docker**: NTFS symlinks require special permissions and often get converted to file copies when crossing filesystem boundaries

---

## The Solution

Tesslate Studio automatically detects and fixes broken symlinks on container startup.

### Detection Logic

The fix script checks if `node_modules/.bin/` contains any regular files instead of symlinks:

```bash
for f in node_modules/.bin/*; do
    if [ -f "$f" ] && [ ! -L "$f" ]; then
        BROKEN=true; break;
    fi;
done;
```

**Logic:**
- `-f "$f"` = file exists and is a regular file
- `! -L "$f"` = file is NOT a symbolic link
- If any file in `.bin/` is a regular file (not a symlink), symlinks are considered broken

### Repair Strategy

When broken symlinks are detected, the fix runs automatically:

1. **Primary Fix - npm rebuild**
   ```bash
   npm rebuild
   ```
   This regenerates the `node_modules/.bin/` symlinks without reinstalling all packages.

2. **Fallback - Full Reinstall**
   If `npm rebuild` fails, the script removes `node_modules/` and runs a fresh install:
   ```bash
   rm -rf node_modules && npm install
   ```

### Complete Fix Script

```bash
if [ -d "node_modules" ] && [ -d "node_modules/.bin" ]; then
  BROKEN=false;
  for f in node_modules/.bin/*; do
    if [ -f "$f" ] && [ ! -L "$f" ]; then
      BROKEN=true; break;
    fi;
  done;
  if [ "$BROKEN" = "true" ]; then
    echo "[TESSLATE] Detected broken node_modules symlinks (copied from Windows), running npm rebuild..." &&
    npm rebuild 2>/dev/null || (
      echo "[TESSLATE] Rebuild failed, reinstalling dependencies..." &&
      rm -rf node_modules && npm install
    );
  fi;
fi
```

---

## When It Runs

### Automatic Execution

The symlink fix runs **automatically on every container startup** as part of the startup command chain. It is prepended to:

1. **Custom start commands** from `TESSLATE.md` files
2. **Generic fallback commands** when no configuration exists

This means every Node.js project gets the fix applied without any user intervention.

### No-Op Behavior

The fix is designed to be a no-op (do nothing) when:
- `node_modules/` directory does not exist
- `node_modules/.bin/` directory does not exist
- All files in `.bin/` are already proper symlinks
- The project is not a Node.js project

This ensures zero overhead for projects that don't need the fix.

---

## Manual Fix Commands

If you need to manually fix broken symlinks inside a running container:

### Option 1: npm rebuild (Recommended)

```bash
npm rebuild
```

This recreates symlinks in `node_modules/.bin/` without downloading packages again.

### Option 2: Full Reinstall

If rebuild fails or you want a clean slate:

```bash
rm -rf node_modules
npm install
```

### Option 3: Fix Specific Package

If only one package's symlinks are broken:

```bash
npm rebuild <package-name>
```

Example:
```bash
npm rebuild next
npm rebuild typescript
```

---

## Troubleshooting

### Fix Ran But Still Getting Errors

1. **Check if the fix actually ran:**
   Look for `[TESSLATE] Detected broken node_modules symlinks` in container logs.

2. **Verify symlinks are now correct:**
   ```bash
   ls -la node_modules/.bin/ | head -20
   ```
   You should see `lrwxrwxrwx` (symlink indicator) for each file, not `-rwxr-xr-x` (regular file).

3. **Manual rebuild:**
   ```bash
   npm rebuild
   ```

### npm rebuild Fails

Common causes:

1. **Missing native dependencies:**
   Some packages need compilation. Install build tools:
   ```bash
   apt-get update && apt-get install -y build-essential python3
   npm rebuild
   ```

2. **Permission issues:**
   ```bash
   chown -R $(whoami) node_modules
   npm rebuild
   ```

3. **Corrupted package-lock.json:**
   ```bash
   rm -rf node_modules package-lock.json
   npm install
   ```

### Symlinks Keep Breaking

If symlinks break repeatedly:

1. **Avoid bind mounts for node_modules:**
   Use a named volume for `node_modules/` instead of bind-mounting the entire project directory.

   Docker Compose example:
   ```yaml
   volumes:
     - ./:/app
     - node_modules:/app/node_modules  # Named volume
   ```

2. **Install dependencies inside container:**
   Don't copy `node_modules/` from the host. Instead, let the container run `npm install` on startup.

### Package Manager Compatibility

The fix works with all Node.js package managers:

| Package Manager | Rebuild Command |
|-----------------|-----------------|
| npm             | `npm rebuild`   |
| yarn            | `yarn rebuild`  |
| pnpm            | `pnpm rebuild`  |
| bun             | `bun install --force` |

The automatic fix uses `npm rebuild` by default, which works in most cases. For other package managers, use the manual commands above.

---

## Technical Details

### Why npm rebuild Works

`npm rebuild` runs the `postinstall` scripts and regenerates symlinks by:
1. Reading the dependency tree from `package-lock.json`
2. Recreating bin links in `node_modules/.bin/`
3. Running any native addon compilations

This is faster than a full `npm install` because it doesn't download packages.

### Performance Impact

| Scenario | Time Impact |
|----------|-------------|
| No fix needed (symlinks OK) | ~0ms (instant check) |
| npm rebuild | 5-30 seconds |
| Full reinstall | 30 seconds - 5 minutes |

The detection is nearly instant because it only checks the first file in `.bin/` that fails the symlink test.

### Cross-Platform Behavior

| Host OS | Docker Engine | Symlinks Preserved | Fix Needed |
|---------|---------------|-------------------|------------|
| Linux   | Native        | Yes               | No         |
| macOS   | Docker Desktop| Yes               | No         |
| Windows | Docker Desktop| No                | Yes        |
| Windows | WSL2 Backend  | Usually           | Sometimes  |

---

## Related Documentation

- [Docker Compose Orchestrator](../../orchestrator/services/docker-compose-orchestrator.md)
- [Base Config Parser](../../orchestrator/services/base-config-parser.md)
- [Container Startup Commands](../../orchestrator/services/container-startup.md)
