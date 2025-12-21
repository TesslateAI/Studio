# Dependency Installation Architecture Options

## Current Architecture

```
User adds container → File-manager pod runs git clone + npm install → Container starts (deps ready)
```

**Problem:** npm install runs in file-manager pod, blocking the orchestrator task for 45+ seconds.

---

## Option A: File Init (Current)

**Where:** File-manager pod during `initialize_container_files()`
**When:** When container is added to the architecture graph
**How:** `kubectl exec` into file-manager pod, run git clone + npm install

```
┌─────────────────────────────────────────────────────────────┐
│  Orchestrator Task                                          │
│  └─> kubectl exec file-manager -- git clone + npm install   │
│      (blocks for 45+ seconds)                               │
└─────────────────────────────────────────────────────────────┘
```

### Pros
- ✅ Container starts instantly (deps already installed)
- ✅ Dev server is immediately usable
- ✅ Simple mental model: "add container" = "container is ready"
- ✅ No cold start surprise for users

### Cons
- ❌ **Blocks orchestrator task** for 45+ seconds
- ❌ Task manager holds state in memory during long operation
- ❌ Single point of failure (if file-manager pod dies during install)
- ❌ User sees "adding container" spinner for a long time
- ❌ Can't parallelize multiple container adds

---

## Option B: Container Startup (Init Container)

**Where:** Dev-server pod's init container
**When:** When container pod starts
**How:** K8s init container runs npm install before main container starts

```
┌─────────────────────────────────────────────────────────────┐
│  Pod Startup                                                │
│  ├─> Init Container: git clone + npm install                │
│  └─> Main Container: npm run dev (waits for init)           │
└─────────────────────────────────────────────────────────────┘
```

### Pros
- ✅ **Doesn't block orchestrator** - task completes immediately
- ✅ Naturally distributed - each pod handles its own deps
- ✅ Can parallelize multiple container starts
- ✅ Pod restart automatically re-installs deps if needed
- ✅ K8s handles failures/retries natively

### Cons
- ❌ Container URL shows 503 for 45+ seconds
- ❌ User doesn't know when container will be ready
- ❌ Every pod restart re-runs npm install (if node_modules lost)
- ❌ More complex pod spec (init containers)
- ❌ Logs are in pod, not in orchestrator task

---

## Option C: Container Startup (Main Container)

**Where:** Dev-server main container command
**When:** Container starts, before dev server
**How:** Deployment command includes npm install

```
┌─────────────────────────────────────────────────────────────┐
│  Main Container Command                                     │
│  └─> cd /app && npm install && npm run dev                  │
└─────────────────────────────────────────────────────────────┘
```

### Pros
- ✅ **Simplest implementation** - just change the command
- ✅ Doesn't block orchestrator
- ✅ No init container complexity
- ✅ Same container handles both install and serve

### Cons
- ❌ Container URL shows 503 for 45+ seconds
- ❌ If npm install fails, container crashes
- ❌ Hard to distinguish "installing" vs "crashed"
- ❌ Every container restart re-runs npm install
- ❌ Can't restart dev server without re-installing deps

---

## Option D: Background Job (Recommended)

**Where:** Separate K8s Job or background task
**When:** Immediately after container added, but async
**How:** Fire-and-forget job, poll for completion

```
┌─────────────────────────────────────────────────────────────┐
│  Add Container                                              │
│  ├─> Create K8s Job: git clone + npm install (async)        │
│  └─> Return immediately to user                             │
│                                                             │
│  (Later) Job completes → Container can be started           │
└─────────────────────────────────────────────────────────────┘
```

### Pros
- ✅ **Doesn't block orchestrator** at all
- ✅ User gets immediate feedback ("container added, installing deps...")
- ✅ Can show real progress via job logs
- ✅ K8s handles job failures/retries
- ✅ Can start multiple jobs in parallel
- ✅ Clear separation of concerns

### Cons
- ❌ More complex implementation (need job tracking)
- ❌ Need UI to show "installing" vs "ready" state
- ❌ Two-step process: add container, then start when ready
- ❌ Need to prevent starting container before job completes

---

## Option E: Pre-built Base Images

**Where:** Container registry (ECR/DockerHub)
**When:** When base is published to marketplace
**How:** Each base has a pre-built image with deps included

```
┌─────────────────────────────────────────────────────────────┐
│  Base Published                                             │
│  └─> Build image with node_modules baked in                 │
│                                                             │
│  User Adds Container                                        │
│  └─> Pull pre-built image (deps already there)              │
└─────────────────────────────────────────────────────────────┘
```

### Pros
- ✅ **Fastest startup** - no npm install at all
- ✅ Consistent across all users
- ✅ Can cache at registry level
- ✅ Network-bound (image pull) vs CPU-bound (npm install)

### Cons
- ❌ Need to rebuild image when base deps change
- ❌ Larger image sizes (node_modules is huge)
- ❌ Can't customize deps per user
- ❌ Complex CI/CD for base maintainers
- ❌ Image pull might still be slow for large images

---

## Option F: S3 Cached node_modules

**Where:** S3 bucket, downloaded during startup
**When:** Container init or startup
**How:** Store pre-built node_modules.tar.gz per base, download instead of npm install

```
┌─────────────────────────────────────────────────────────────┐
│  Base Published                                             │
│  └─> npm install → tar node_modules → upload to S3          │
│                                                             │
│  User Adds Container                                        │
│  └─> Download node_modules.tar.gz from S3 (fast)            │
│  └─> Extract (fast)                                         │
└─────────────────────────────────────────────────────────────┘
```

### Pros
- ✅ **Much faster than npm install** (~5-10s vs 45s)
- ✅ Network-bound, not CPU-bound
- ✅ Can share cache across all users of same base
- ✅ Doesn't require custom images
- ✅ Easy to invalidate cache when base updates

### Cons
- ❌ Need cache management infrastructure
- ❌ Storage costs for cached deps
- ❌ Cache invalidation complexity
- ❌ Platform-specific binaries (node-gyp) may fail
- ❌ Still need npm install for user-added deps

---

## Comparison Matrix

| Option | Blocks Orchestrator | Startup Time | Complexity | User Experience |
|--------|---------------------|--------------|------------|-----------------|
| A: File Init (Current) | ❌ Yes (45s) | ⚡ Instant | Low | 😐 Long "adding" phase |
| B: Init Container | ✅ No | 🐢 Slow (45s 503) | Medium | 😐 Long 503 phase |
| C: Main Container | ✅ No | 🐢 Slow (45s 503) | Low | 😐 Long 503 phase |
| D: Background Job | ✅ No | ⚡ Instant* | Medium | 😊 Clear status |
| E: Pre-built Images | ✅ No | ⚡ Fast | High | 😊 Fast startup |
| F: S3 Cache | ✅ No | ⚡ Fast (5-10s) | Medium | 😊 Fast startup |

*After job completes

---

## Recommendation

### Short-term: Option D (Background Job)

1. Change `initialize_container_files()` to spawn a K8s Job instead of blocking
2. Return task immediately with status "installing_dependencies"
3. Add endpoint to check job status
4. Prevent container start until job completes
5. Show real progress in UI

**Implementation:**
```python
# Instead of blocking kubectl exec:
job = create_dependency_install_job(namespace, container_directory, git_url, branch)
await k8s_client.create_job(job)
# Return immediately
return {"status": "installing", "job_name": job.metadata.name}
```

### Long-term: Option F (S3 Cache)

1. When base is added to marketplace, run npm install and cache node_modules to S3
2. When user adds container, download cached deps from S3
3. Fall back to npm install if cache miss
4. Keep Option D as fallback for user-added deps

**Expected improvement:**
- Current: 45s npm install
- With S3 cache: 5-10s download + extract
- **4-9x faster**

---

## Your Current Architecture vs Options

```
CURRENT (Option A):
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ Add Container│────▶│ npm install  │────▶│ Container    │
│   (async)    │     │ (45s block)  │     │   Ready      │
└──────────────┘     └──────────────┘     └──────────────┘
                     ▲
                     │ BOTTLENECK

RECOMMENDED (Option D):
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ Add Container│────▶│ K8s Job      │────▶│ Container    │
│   (instant)  │     │ (background) │     │   Ready      │
└──────────────┘     └──────────────┘     └──────────────┘
                     │
                     └─▶ User sees "Installing dependencies..."
```
