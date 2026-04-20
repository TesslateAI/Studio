# Unified Snapshots Migration — Full Procedure Guide

> **Purpose:** Migrate an environment (beta, then production) from the `develop`
> branch btrfs CSI system to the `feat/unified-snapshots-system` branch.
>
> **Audience:** Future Claude sessions (and humans) running this migration.
>
> **Scope:** This document captures the complete beta migration as executed
> on **2026-04-13 to 2026-04-14**, including every gotcha hit and how to
> avoid it. Each step has the exact command that was run.

---

## 0. TL;DR — What actually changes

### On S3 (the data)

Only `manifests/*.json` gets rewritten. Everything else is format-identical.

| Prefix | Format change | Migration action |
|--------|---------------|------------------|
| `blobs/sha256:*.zst` | none (content-addressed, same scheme) | leave alone |
| `index/templates.json` | none | leave alone |
| `tombstones/*` | none | leave alone |
| `manifests/{vol}.json` | `layers` array + `type` field → `snapshots` map + `role`/`prev`/`consolidation`/`head`/`branches` | **convert** |

### On the code (binaries)

The feature branch changes:

1. Manifest schema in Go (`pkg/cas/manifest.go`) — loads both formats but writes only new.
2. Sync daemon — per-volume actor model, consolidation tracking, parent-chain restore.
3. **UUID rewriting at receive time** (`pkg/btrfs/rewrite.go`) — rewrites parent UUIDs in
   btrfs send streams to match the local parent's native UUID before piping to `btrfs receive`.
   This is what makes old-format blobs restorable by the new daemon even though their stored
   parent UUIDs don't match the freshly-received local template's UUID.
4. Native minio-go S3 client (replaces rclone subprocesses) — faster restore, but new config requirements (see `docs/guides/unified-snapshots-deploy.md` or section 2 below).

### On the cluster state

- **Local btrfs pools on each node must be wiped.** They contain per-volume synthetic
  templates (`templates/_vol_*`) and layer subvolumes created by the old daemon. The new
  daemon will re-create everything from S3 on demand.
- **Volume Hub registry rebuilds automatically from CSI node discovery + S3 manifests**
  on startup. Nothing to migrate there.
- **No database migrations** between `develop` and `feat/unified-snapshots-system`.

---

## 1. Prerequisites

Before you start, verify:

- [ ] Feature branch already contains the three AWS-deploy fixes. Confirm with:
  ```
  git log --oneline feat/unified-snapshots-system -- \
    services/btrfs-csi/pkg/objstore/s3.go \
    k8s/base/volume-hub/deployment.yaml \
    k8s/terraform/aws/kubernetes.tf
  ```
  Expect to see commit `fix: AWS EKS deployment of btrfs CSI — IRSA creds, explicit S3 endpoint, Hub pull policy` (hash `9152f6e9` on beta). If absent, the migration will fail with the exact symptoms described in §5 "Gotchas we hit". Fix them **before** proceeding or re-deploy will be broken.

- [ ] `aws` CLI configured with credentials that can read/write the btrfs-snapshots bucket.
- [ ] `kubectl` with access to the target cluster (`tesslate-beta-eks` or `tesslate-production-eks`).
- [ ] `tesslate-btrfs-csi:<env>` image built and pushed to ECR **from the feature branch**.
  Build is user-driven (per CLAUDE.md memory): `./scripts/aws-deploy.sh build <env> btrfs-csi --cached`.
- [ ] Downtime window announced. Beta took ~1 hour end-to-end (20 min downtime, 40 min
  investigation + fixes on first run). Production should be ~30 min pure execution
  if all fixes are already in the image.

### Environment-specific values

Resolve these up-front. In this guide they're referred to as `$CTX`, `$BUCKET`, `$NS`.

```bash
CTX=tesslate-beta-eks                             # or tesslate-production-eks
NS=tesslate
BUCKET=$(kubectl --context=$CTX get secret tesslate-btrfs-csi-config \
  -n kube-system -o jsonpath='{.data.STORAGE_BUCKET}' | base64 -d)
echo "Bucket: $BUCKET"                            # e.g. tesslate-btrfs-snapshots-beta-352faddd
```

---

## 2. Apply the terraform changes FIRST

The feature branch adds `RCLONE_S3_ENDPOINT` to the `btrfs-csi-config` secret
(`k8s/terraform/aws/kubernetes.tf`). Without it, CSI startup fails with
`S3 endpoint not configured`. Apply terraform before cluster shutdown so the secret is ready when pods come back up.

```bash
cd k8s/terraform/aws
terraform plan   # expect: update on kubernetes_secret.btrfs_csi_config
terraform apply
```

Verify:
```bash
kubectl --context=$CTX get secret tesslate-btrfs-csi-config -n kube-system \
  -o jsonpath='{.data.RCLONE_S3_ENDPOINT}' | base64 -d
# expect: https://s3.us-east-1.amazonaws.com (or your region)
```

---

## 3. Full cluster shutdown

**Critical:** everything that can touch S3 manifests must be stopped. The sync daemon
has a 15s–5m interval — if left running during conversion it will overwrite the
converted format with the old format. This is one of the top gotchas.

Components to stop:
1. App namespace (`tesslate`) deployments
2. App namespace CronJobs (suspend)
3. Project namespaces (`proj-*`)
4. Volume Hub (`kube-system`)
5. btrfs CSI DaemonSet (`kube-system`) — DaemonSets can't scale to 0, patch `nodeSelector` instead

Use `run_migration.sh --phase stop` — it does all five. Inspect it first to ensure you
agree with its actions, then:

```bash
./scripts/migration/unified-snapshots/run_migration.sh --phase stop --context $CTX --dry-run
./scripts/migration/unified-snapshots/run_migration.sh --phase stop --context $CTX
```

Verify full shutdown:
```bash
kubectl --context=$CTX -n $NS get pods --field-selector=status.phase!=Succeeded
# expect: No resources found (Completed CronJob records are harmless)

kubectl --context=$CTX -n kube-system get pods -l app=tesslate-volume-hub
# expect: No resources

kubectl --context=$CTX -n kube-system get pods -l app=tesslate-btrfs-csi-node
# expect: No resources

kubectl --context=$CTX get ns -l tesslate.io/project
# expect: No resources
```

---

## 4. Full S3 backup (non-destructive)

Copy the entire bucket (blobs + index + manifests + tombstones) to
`backups/feat-unified-snapshots/`. Originals stay in place — this is copy-only.

```bash
./scripts/migration/unified-snapshots/backup_s3.sh --bucket $BUCKET --dry-run
./scripts/migration/unified-snapshots/backup_s3.sh --bucket $BUCKET
```

The script does: `aws s3 cp --recursive --exclude backups/*`, then an `aws s3 sync` to
catch any mid-copy changes, then a per-prefix count verification, then drops a
`BACKUP_INFO.json` marker.

For beta: **246.9 GiB / 5,640 objects** copied in ~30 minutes with
`aws configure set default.s3.max_concurrent_requests 20`. Server-side copy never
leaves AWS, no egress cost.

Verify:
```bash
for p in blobs index manifests tombstones; do
  src=$(aws s3api list-objects-v2 --bucket $BUCKET --prefix "$p/" --query "length(Contents[])" --output text)
  bak=$(aws s3api list-objects-v2 --bucket $BUCKET --prefix "backups/feat-unified-snapshots/$p/" --query "length(Contents[])" --output text)
  echo "$p/: src=$src bak=$bak"
done
# Counts per prefix must match.
```

---

## 5. Convert manifests to new DAG format

The converter reads each manifest in `manifests/`, detects old format, rewrites to
new format, uploads back. Resumable, crash-safe, observable.

Pre-flight: always validate a single manifest first.

```bash
# Pick one with many layers for a thorough test. Example beta had vol-5babb7cf9cbb (423 layers).
python3 scripts/migration/unified-snapshots/convert_manifests.py \
  --bucket $BUCKET --volume-id <pick-one-vol-id> --dry-run

python3 scripts/migration/unified-snapshots/convert_manifests.py \
  --bucket $BUCKET --volume-id <pick-one-vol-id>
```

Then run on everything:

```bash
python3 scripts/migration/unified-snapshots/convert_manifests.py --bucket $BUCKET
```

For beta: **429 manifests in ~18 minutes** (390 old-format converted + 39 empty ghosts
normalized + 0 failures). State and logs land at `runs/<timestamp>/` locally and
`s3://$BUCKET/backups/feat-unified-snapshots/runs/<timestamp>/`.

### Known edge cases the converter handles

1. **`"layers": null` ghost manifests** — volumes registered but never synced. The
   converter normalizes them to canonical empty DAG (`{"head":"","branches":{},"snapshots":{}}`).
   Beta had 38 of these (including `vol-001385846cdd`).

2. **Duplicate layer hashes** — the old sync daemon occasionally logged multiple "syncs"
   with the same content hash (typically all-same-empty-content from a broken sync loop).
   Converter dedupes, keeping the first occurrence's prev pointer, and never emits
   `prev == self`. Beta had 3 of these (`vol-d8bf8b305ef1` 80→1, `vol-a882be1176f4` 34→1,
   `vol-f24b5fd9f4f9` 50→16).

3. **`NeedsMigration` case** — old algorithm diffed every layer from the template, not
   from the previous layer. So all parents match. Converter marks HEAD as
   `consolidation: true` in this case; Go `BuildRestoreChain(HEAD)` then returns
   `[HEAD]` — efficient single-blob restore.

### Resume / retry

If the run gets interrupted:
```bash
python3 scripts/migration/unified-snapshots/convert_manifests.py --list-runs
python3 scripts/migration/unified-snapshots/convert_manifests.py --status --run-id <run-id>
python3 scripts/migration/unified-snapshots/convert_manifests.py --bucket $BUCKET --run-id <run-id>          # resume
python3 scripts/migration/unified-snapshots/convert_manifests.py --bucket $BUCKET --run-id <run-id> --retry-failed   # only failed
```

### Validate the conversion

After the run, check zero old format remains:

```bash
python3 - <<'EOF'
import json, subprocess
from concurrent.futures import ThreadPoolExecutor
BUCKET="$BUCKET"  # substitute
keys = json.loads(subprocess.run(["aws","s3api","list-objects-v2",
    "--bucket",BUCKET,"--prefix","manifests/",
    "--query","Contents[].Key","--output","json"],
    capture_output=True,text=True,check=True).stdout)
def check(k):
    m = json.loads(subprocess.run(["aws","s3","cp",f"s3://{BUCKET}/{k}","-"],
        capture_output=True,check=True).stdout)
    return "OLD" if "layers" in m else "NEW"
with ThreadPoolExecutor(max_workers=20) as ex:
    res = list(ex.map(check, keys))
print(f"{res.count('NEW')}/{len(res)} new, {res.count('OLD')} old")
EOF
```

Beta final: **429/429 new, 0 old**.

---

## 6. Wipe local btrfs pool on every node

**Critical and easy to skip.** The on-disk btrfs pool contains per-volume synthetic
templates (`templates/_vol_*`) and layer subvolumes created by the old daemon. The new
daemon uses shared templates (`templates/nextjs-16`, etc.) and different naming —
leaving the old state creates confusing split-brain behavior and can cause restore
failures or phantom volumes.

This was step one of the user's final fix on beta — without it projects wouldn't
restore correctly even after the manifest conversion.

Do it with CSI pods still running (they're the only thing that has the `btrfs` binary
and hostPath access on the nodes). The CSI sync daemon will do nothing harmful because
Volume Hub is down (no orchestration work to pick up).

```bash
WIPE='set -e
POOL=/mnt/tesslate-pool
echo "== Before =="; df -h $POOL | tail -1
# Deepest subvolumes first (btrfs refuses to delete non-leaf subvolumes).
btrfs subvolume list $POOL | awk "{print \$NF}" | awk "{print length, \$0}" | sort -rn | awk "{print \$2}" | while read path; do
  btrfs subvolume delete "$POOL/$path" 2>&1 | tail -1 || true
done
rm -rf $POOL/volumes $POOL/snapshots $POOL/templates $POOL/layers $POOL/uppers $POOL/work
mkdir -p $POOL/volumes $POOL/snapshots $POOL/templates $POOL/layers $POOL/uppers $POOL/work
echo "== After =="; df -h $POOL | tail -1; ls -la $POOL
'
for POD in $(kubectl --context=$CTX -n kube-system get pods -l app=tesslate-btrfs-csi-node -o jsonpath='{.items[*].metadata.name}'); do
  echo "=== wiping on $POD ==="
  kubectl --context=$CTX -n kube-system exec "$POD" -c tesslate-btrfs-csi -- sh -c "$WIPE"
done
```

**Note:** `btrfs subvolume delete` is async — reported space won't fully reclaim until
btrfs-cleaner runs. Don't panic if `df` still shows 400+ MiB "used" on a freshly wiped
pool. The subvolume list should be empty.

---

## 7. Deploy new images + restart storage plane

Build and push images **from `feat/unified-snapshots-system`**:

```bash
./scripts/aws-deploy.sh build <env> btrfs-csi --cached
./scripts/aws-deploy.sh build <env> backend    --cached
./scripts/aws-deploy.sh build <env> frontend   --cached
# (devserver only if you changed it)
```

Apply the compute overlay so the terraform + volume-hub changes land:

```bash
kubectl --context=$CTX apply -k k8s/overlays/aws-<env>/compute/
# expect: deployment.apps/tesslate-volume-hub configured (or unchanged if terraform already applied)
```

Re-enable CSI DaemonSet and start everything back up via the run-migration script's
`start` phase. This un-patches the `nodeSelector` disable, scales Hub and app pods
back to 1, and un-suspends CronJobs in the correct order (storage plane first, app
plane second).

```bash
./scripts/migration/unified-snapshots/run_migration.sh --phase start --context $CTX
```

Verify **image digests are identical** across Hub and CSI pods — this is the
imagePullPolicy gotcha (§8 item 3):

```bash
kubectl --context=$CTX -n kube-system get pods -l app=tesslate-volume-hub \
  -o jsonpath='{.items[*].status.containerStatuses[?(@.name=="hub")].imageID}'
echo
kubectl --context=$CTX -n kube-system get pods -l app=tesslate-btrfs-csi-node \
  -o jsonpath='{.items[*].status.containerStatuses[?(@.name=="tesslate-btrfs-csi")].imageID}'
# Both must resolve to the SAME sha256:... digest.
```

If the digests differ, force-delete the stale pod:
```bash
kubectl --context=$CTX -n kube-system delete pod -l app=tesslate-volume-hub
```

---

## 8. Gotchas we hit on beta (and how they're now prevented)

These are the four things that broke the first beta deploy. All four are now
fixed in the feature branch, so a production deploy shouldn't hit them —
but verify each before assuming.

### 1. `CAS sync not configured` — missing `RCLONE_S3_ENDPOINT`

**Symptom:** CSI returns gRPC FailedPrecondition on every restore:
```
rpc error: code = FailedPrecondition desc = CAS sync not configured
```

**Cause:** The native minio-go client (introduced in commit `8362446c`) requires
`RCLONE_S3_ENDPOINT` explicitly. The old rclone code auto-resolved from region.

**Fix:** Present in `k8s/terraform/aws/kubernetes.tf` — the secret has
`RCLONE_S3_ENDPOINT = "https://s3.${var.aws_region}.amazonaws.com"`.

**Verify:** `§2` command above. If you see this error, terraform wasn't applied.

### 2. `Access Denied` on every S3 read from Hub/CSI — missing IRSA support

**Symptom:** Hub warns `failed to create object storage: ...`, every CSI restore
returns `Access Denied` even though the IAM policy is correct and a debug pod
using the same service account can read the bucket.

**Cause:** `pkg/objstore/s3.go` called `credentials.NewStaticV4(cfg.AccessKeyID,
cfg.SecretAccessKey, "")`. On EKS with IRSA, both are empty strings — the client
signed every request with no credentials.

**Fix:** Present in `pkg/objstore/s3.go` — `buildS3Credentials()` detects
`AWS_WEB_IDENTITY_TOKEN_FILE` + `AWS_ROLE_ARN` and uses `NewSTSWebIdentity`.

**Verify:** Check CSI startup log says `Sync daemon started (CAS mode)` **without**
a preceding `failed to create object storage` warning, and that restores actually
download blobs. If you see Access Denied, the old image is still running — check
digests per §7.

### 3. Volume Hub running stale image after `rollout restart`

**Symptom:** Hub digest differs from CSI digest after a new image build and
`kubectl rollout restart`. Hub still behaves like the previous build.

**Cause:** `k8s/base/volume-hub/deployment.yaml` did not set `imagePullPolicy`.
Base image is `:latest` (would default to `Always`), but overlays rewrite the tag
to `:beta`/`:prod`. Kubernetes evaluates default pull policy against the *resolved*
tag — non-`:latest` defaults to `IfNotPresent` → stale cached digest persists
across rollouts. CSI DaemonSet sets `Always` explicitly so it's not affected.

**Fix:** Present in `k8s/base/volume-hub/deployment.yaml` — `imagePullPolicy:
Always` is now explicit on the hub container.

**Verify:**
```bash
kubectl --context=$CTX -n kube-system get deploy tesslate-volume-hub \
  -o jsonpath='{.spec.template.spec.containers[?(@.name=="hub")].imagePullPolicy}'
# expect: Always
```

If you ever see a digest mismatch, `kubectl delete pod` forces a fresh pull
immediately — this was the escape hatch on beta.

### 4. CSI DaemonSet disable-patch never removed on start

**Symptom:** After `start` phase, CSI pods have `DESIRED=0 READY=0`, Hub logs
`RebuildRegistry: no live nodes`. Backend gets stuck retrying restore.

**Cause:** `run_migration.sh --phase stop` patches the DaemonSet with
`nodeSelector: tesslate.io/migration-disabled: true` to drain it. The `start`
phase must remove this patch. If you only run `stop` and never `start` (or
partial starts), the DaemonSet stays drained indefinitely.

**Fix:** `run_migration.sh --phase start` removes the nodeSelector as its first
step. Be sure to run it.

**Verify:**
```bash
kubectl --context=$CTX -n kube-system get ds tesslate-btrfs-csi-node \
  -o jsonpath='{.spec.template.spec.nodeSelector}'
# expect: {} or similar (no tesslate.io/migration-disabled key)
```

Manual un-patch if the start phase didn't do it:
```bash
kubectl --context=$CTX -n kube-system patch daemonset tesslate-btrfs-csi-node \
  --type=json --patch='[{"op":"remove","path":"/spec/template/spec/nodeSelector/tesslate.io~1migration-disabled"}]'
```

---

## 9. First-project-load expectations

When a user opens a hibernated project for the first time after migration:

1. Backend calls Hub `EnsureCached(vol-X)`.
2. Hub picks a node, sends `RestoreVolume` to that CSI.
3. CSI reads `manifests/vol-X.json` from S3 (uses IRSA).
4. CSI downloads the template blob (`base` field), `btrfs receive` — creates
   `templates/_vol_vol-X`. Small (~200 bytes) — sub-second.
5. CSI calls `BuildRestoreChain(HEAD)`. For migrated manifests, HEAD has
   `consolidation: true`, so chain = `[HEAD]`.
6. CSI downloads the HEAD blob. **This is the slow step** — typical HEAD is
   100–300 MB compressed, 400 MB–1.5 GB decompressed. 1.5–3 minutes is normal.
7. CSI pipes the blob through the UUID rewriter and `btrfs receive` — creates
   `layers/vol-X@<short-hash>`.
8. CSI snapshots the layer subvolume into `volumes/vol-X`.
9. Hub marks volume cached, backend returns 200.
10. Compute pod scheduled — `pnpm install --frozen-lockfile` (~30–60s on a
    restored volume), then dev server starts and hits readiness.

Total: **~3–5 minutes from click to preview-ready** on first load. Subsequent
loads are fast (volume stays cached on the node).

### Common "it's stuck" UX moments and what they mean

- **`state=restoring` for 2–3 min with growing pool usage on the target node** —
  normal, HEAD blob is being downloaded/decompressed/received. Confirm progress
  via `df -h /mnt/tesslate-pool` and `du -sh /mnt/tesslate-pool/layers/*@pending/`
  on the owning node.

- **`Readiness probe failed: context deadline exceeded` on the dev pod** —
  normal during the `pnpm install` window. Pod goes Ready once Next.js boots
  (`✓ Ready in 1886ms` in logs).

- **`Deadline Exceeded` in the backend log** — the gRPC timeout on
  `backend → Hub → CSI RestoreVolume` is shorter than a real restore. CSI keeps
  working in the background; the backend polls `ResolveVolume` state and
  eventually gets `state=cached`.

---

## 10. Rollback

If the migration goes wrong and you need to revert:

```bash
./scripts/migration/unified-snapshots/rollback.sh --bucket $BUCKET --dry-run
./scripts/migration/unified-snapshots/rollback.sh --bucket $BUCKET
```

This restores `blobs/ index/ manifests/ tombstones/` from `backups/feat-unified-snapshots/`.
After restore, redeploy the previous (`develop`) images, re-enable CSI DaemonSet,
scale Hub + app back up.

Backups are retained indefinitely (they're in the same bucket with lifecycle rules
only on the `_deleted/` prefix, not `backups/`). For production, after a month of
stable migration, delete `backups/feat-unified-snapshots/` manually to free space.

---

## 11. Post-migration verification checklist

- [ ] `kubectl get pods -A` — all `tesslate` ns pods Running, both CSI nodes Running, Hub Running.
- [ ] `kubectl --context=$CTX -n kube-system logs deploy/tesslate-volume-hub -c hub | head` — **no** `failed to create object storage` warning.
- [ ] `kubectl --context=$CTX -n kube-system logs -l app=tesslate-btrfs-csi-node -c tesslate-btrfs-csi` — shows `Sync daemon started (CAS mode)`.
- [ ] Image digests match between Hub and CSI (§7 verify command).
- [ ] At least one hibernated project loads successfully in the browser end-to-end (files + preview).
- [ ] CronJobs (`namespace-reaper`, `snapshot-cleanup`) are `SUSPEND=false`.
- [ ] Migration state uploaded to S3: `aws s3 ls s3://$BUCKET/backups/feat-unified-snapshots/runs/`.

---

## 12. Reference: beta timeline (for pacing production)

| Time | Event | Notes |
|------|-------|-------|
| 0:00 | Preflight: terraform apply, cluster inspection | New `RCLONE_S3_ENDPOINT` landed |
| 0:05 | `run_migration.sh --phase stop` | 7 deployments to 0, Hub to 0, CSI disabled, 2 cronjobs suspended |
| 0:08 | `backup_s3.sh` | 246.9 GiB / 5,640 objects, server-side copy |
| 0:38 | `convert_manifests.py` | 429 manifests processed in 18 min |
| 0:56 | Validate all 429 in new format | 429/429 OK |
| 0:58 | Wipe btrfs pools on both nodes | Deletes old `_vol_*` synthetic templates |
| 1:00 | Restart CSI + Hub, scale app back | `--phase start` plus manual fixes |
| 1:10 | First project tested | `project-iy9rpx` restore: ~2 min once fixes were in |
| 1:15 | End-to-end working | Files + preview confirmed |

Production should be **faster** since all code bugs are now fixed in the branch —
expect ~30 min of pure execution time.

---

## 13. Useful related files / memories

- `scripts/migration/unified-snapshots/README.md` — script-level reference (flags, observability).
- `services/btrfs-csi/cmd/migrate/main.go` — the Go version of the manifest-only migrator,
  also does on-disk synthetic-template cleanup. Our Python script duplicates most of its
  logic but adds run observability (state.json, S3 log mirror, resume/retry).
- Memory: `feedback_rclone_endpoint_required.md`
- Memory: `feedback_rollout_restart_cached_image.md`
- Memory: `feedback_full_cluster_shutdown.md`
- Commits on feature branch:
  - `9152f6e9` fix: AWS EKS deployment of btrfs CSI
  - `eb9895f5` feat: unified-snapshots S3 manifest migration toolkit
