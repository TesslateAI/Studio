#!/usr/bin/env python3
"""
Convert CAS manifests from old linear Layer format to new DAG Snapshot format.

Old format (develop):
  { "layers": [ {hash, parent, type, label?, ts} ] }

New format (unified-snapshots):
  { "head": "...", "branches": {}, "snapshots": { hash: {hash, parent, prev, role, label?, consolidation, ts} } }

Conversion rules:
  - "layers" array  → "snapshots" hash-indexed map
  - "type" field    → "role" field
  - type "snapshot" → role "checkpoint"
  - type "sync"     → role "sync"  (unchanged value)
  - HEAD            = last entry in layers array
  - prev            = previous entry's hash (chronological chain)
  - consolidation   = false for all entries initially
  - NeedsMigration: if all layers share the same parent, mark HEAD as consolidation=true

Observability:
  Each run writes to runs/<timestamp>/ with:
    - state.json    — authoritative per-volume status (resumable)
    - run.log       — human-readable progress log
    - summary.json  — final counts + error list

Usage:
  # List prior runs
  python3 convert_manifests.py --list-runs

  # Dry run (read-only, prints what would change)
  python3 convert_manifests.py --bucket BUCKET --dry-run

  # Convert a single manifest (for validation)
  python3 convert_manifests.py --bucket BUCKET --volume-id vol-abc123

  # Convert all manifests (new run)
  python3 convert_manifests.py --bucket BUCKET

  # Resume a run — re-process pending/failed only
  python3 convert_manifests.py --bucket BUCKET --run-id 2026-04-14T01-30-00Z

  # Retry only failed from a specific run
  python3 convert_manifests.py --bucket BUCKET --run-id 2026-04-14T01-30-00Z --retry-failed

  # Show status of a run
  python3 convert_manifests.py --status --run-id 2026-04-14T01-30-00Z

  # Resolve bucket from k8s secret
  python3 convert_manifests.py --from-k8s-secret --context tesslate-beta-eks --dry-run
"""

import argparse
import base64
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Status values stored in state.json per volume
STATUS_PENDING    = "pending"      # listed but not attempted
STATUS_IN_PROGRESS = "in_progress" # started, not yet finished (crash marker)
STATUS_SUCCEEDED  = "succeeded"    # converted and verified
STATUS_FAILED     = "failed"       # error during convert/upload/verify
STATUS_SKIPPED    = "skipped"      # already in new format or empty

SCRIPT_DIR = Path(__file__).resolve().parent
RUNS_DIR = SCRIPT_DIR / "runs"


def ts_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_id_new() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def resolve_bucket_from_k8s(context: str) -> str:
    try:
        result = subprocess.run(
            ["kubectl", f"--context={context}",
             "get", "secret", "tesslate-btrfs-csi-config",
             "-n", "kube-system",
             "-o", "jsonpath={.data.STORAGE_BUCKET}"],
            capture_output=True, text=True, check=True,
        )
        return base64.b64decode(result.stdout).decode()
    except subprocess.CalledProcessError as e:
        print(f"ERROR: failed to read k8s secret: {e.stderr}", file=sys.stderr)
        sys.exit(1)


def list_manifests(bucket: str, volume_id: str | None = None) -> list[str]:
    prefix = f"manifests/{volume_id}.json" if volume_id else "manifests/"
    try:
        result = subprocess.run(
            ["aws", "s3api", "list-objects-v2",
             "--bucket", bucket,
             "--prefix", prefix,
             "--query", "Contents[].Key",
             "--output", "json"],
            capture_output=True, text=True, check=True,
        )
        keys = json.loads(result.stdout or "null")
        if keys is None:
            return []
        return sorted(k for k in keys if k.endswith(".json"))
    except subprocess.CalledProcessError as e:
        print(f"ERROR: failed to list S3 objects: {e.stderr}", file=sys.stderr)
        sys.exit(1)


def download_manifest(bucket: str, key: str) -> tuple[dict, bytes]:
    r = subprocess.run(
        ["aws", "s3", "cp", f"s3://{bucket}/{key}", "-"],
        capture_output=True, check=True,
    )
    return json.loads(r.stdout), r.stdout


def upload_manifest(bucket: str, key: str, manifest: dict) -> bytes:
    data = json.dumps(manifest, indent=2).encode()
    subprocess.run(
        ["aws", "s3", "cp", "-", f"s3://{bucket}/{key}",
         "--content-type", "application/json"],
        input=data, capture_output=True, check=True,
    )
    return data


def sha256_short(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


# ────────────────────────────────────────────────────────────────────────────
# Conversion logic
# ────────────────────────────────────────────────────────────────────────────

def is_already_converted(manifest: dict) -> bool:
    snaps = manifest.get("snapshots")
    if isinstance(snaps, dict) and len(snaps) > 0:
        return True
    return "head" in manifest


def is_old_format(manifest: dict) -> bool:
    """Old format if the "layers" key exists at all, even as null or [].
    An empty-layers old manifest gets normalized to the canonical empty DAG."""
    return "layers" in manifest


def convert_manifest(manifest: dict) -> dict:
    layers = manifest.get("layers") or []
    volume_id = manifest.get("volume_id", "")
    base = manifest.get("base", "")
    template_name = manifest.get("template_name", "")

    snapshots = {}
    prev_hash = ""

    # Some legacy manifests contain duplicate layer hashes (same content synced
    # multiple times, e.g. empty-content retries). In a hash-indexed map these
    # collapse to one entry — keep the first occurrence (preserves earliest ts
    # and correct prev pointer) and skip subsequent duplicates without
    # updating prev_hash, so the next unique entry chains from the last
    # unique one.
    for layer in layers:
        hash_val = layer["hash"]
        if hash_val in snapshots:
            continue  # duplicate — keep first, don't advance chronological chain

        # Sanity: never emit a self-cycle (defense-in-depth for weird inputs)
        safe_prev = prev_hash if prev_hash != hash_val else ""

        parent = layer.get("parent", "")
        old_type = layer.get("type", "sync")
        label = layer.get("label", "")
        ts = layer.get("ts", "")

        if old_type == "snapshot":
            role = "checkpoint"
        elif not old_type:
            role = "sync"
        else:
            role = old_type

        snapshot = {
            "hash": hash_val,
            "parent": parent,
            "prev": safe_prev,
            "role": role,
            "consolidation": False,
            "ts": ts,
        }
        if label:
            snapshot["label"] = label

        snapshots[hash_val] = snapshot
        prev_hash = hash_val

    head = layers[-1]["hash"] if layers else ""

    if head and len(layers) > 0:
        parents = set()
        h = head
        while h and h != base:
            s = snapshots.get(h)
            if not s:
                break
            parents.add(s["parent"])
            h = s["parent"]
        has_consolidation = any(s.get("consolidation") for s in snapshots.values())
        if not has_consolidation and len(parents) == 1:
            snapshots[head]["consolidation"] = True

    converted = {
        "volume_id": volume_id,
        "base": base,
        "head": head,
        "branches": {},
        "snapshots": snapshots,
    }
    if template_name:
        converted["template_name"] = template_name
    return converted


def verify_converted(bucket: str, key: str, expected_bytes: bytes) -> None:
    """Re-download and compare to what we uploaded. Raises on mismatch."""
    _, actual = download_manifest(bucket, key)
    if hashlib.sha256(actual).hexdigest() != hashlib.sha256(expected_bytes).hexdigest():
        raise RuntimeError(f"post-upload verify mismatch for {key}")


# ────────────────────────────────────────────────────────────────────────────
# State / logging
# ────────────────────────────────────────────────────────────────────────────

class RunState:
    """Per-run observability: state.json + run.log + summary.json.

    Local-first, optionally mirrored to S3 under:
      s3://{bucket}/backups/feat-unified-snapshots/runs/{run_id}/
    """

    # How many state flushes before we push state.json to S3.
    # Tradeoff: smaller = more S3 PUTs, finer crash recovery window.
    S3_FLUSH_EVERY = 25

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.state_path = run_dir / "state.json"
        self.log_path = run_dir / "run.log"
        self.summary_path = run_dir / "summary.json"
        self.state = {
            "run_id": run_dir.name,
            "bucket": None,
            "mode": None,
            "started_at": ts_utc(),
            "completed_at": None,
            "volumes": {},
        }
        self._log_fh = None
        self._s3_enabled = False
        self._s3_prefix = None  # e.g., backups/feat-unified-snapshots/runs/{run_id}
        self._flush_counter = 0

    @classmethod
    def load(cls, run_dir: Path) -> "RunState":
        obj = cls(run_dir)
        if obj.state_path.exists():
            obj.state = json.loads(obj.state_path.read_text())
        return obj

    def open(self, bucket: str, mode: str, s3_logs: bool = True) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        if self.state.get("bucket") and self.state["bucket"] != bucket:
            raise RuntimeError(
                f"run bucket mismatch: state has {self.state['bucket']}, got {bucket}"
            )
        self.state["bucket"] = bucket
        self.state["mode"] = mode
        self._log_fh = open(self.log_path, "a", buffering=1)
        self._s3_enabled = s3_logs
        self._s3_prefix = f"backups/feat-unified-snapshots/runs/{self.state['run_id']}"
        self._flush_state()
        if self._s3_enabled:
            self._s3_upload(self.state_path)

    def close(self, summary: dict) -> None:
        self.state["completed_at"] = ts_utc()
        self._flush_state()
        self.summary_path.write_text(json.dumps(summary, indent=2))
        if self._log_fh:
            self._log_fh.close()
            self._log_fh = None
        # Final S3 push of all artifacts
        if self._s3_enabled:
            self._s3_upload(self.state_path)
            self._s3_upload(self.log_path)
            self._s3_upload(self.summary_path)
            print(f"\nLogs uploaded to s3://{self.state['bucket']}/{self._s3_prefix}/")

    def log(self, msg: str, *, echo: bool = True) -> None:
        line = f"[{ts_utc()}] {msg}"
        if echo:
            print(line)
        if self._log_fh:
            self._log_fh.write(line + "\n")

    def volumes(self) -> dict:
        return self.state.setdefault("volumes", {})

    def update(self, volume_id: str, **kwargs) -> None:
        v = self.volumes().setdefault(volume_id, {})
        v.update(kwargs)
        self._flush_state()

    def _flush_state(self) -> None:
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.state, indent=2))
        tmp.replace(self.state_path)
        self._flush_counter += 1
        # Periodic S3 mirror of state.json for crash visibility
        if self._s3_enabled and self._flush_counter % self.S3_FLUSH_EVERY == 0:
            self._s3_upload(self.state_path)

    def _s3_upload(self, path: Path) -> None:
        """Best-effort S3 upload. Never aborts the run on failure."""
        if not self._s3_enabled or not self._s3_prefix:
            return
        bucket = self.state.get("bucket")
        if not bucket:
            return
        key = f"{self._s3_prefix}/{path.name}"
        try:
            subprocess.run(
                ["aws", "s3", "cp", str(path), f"s3://{bucket}/{key}",
                 "--content-type", "application/json" if path.suffix == ".json" else "text/plain",
                 "--only-show-errors"],
                check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as e:
            # Log but don't fail — S3 log is best-effort
            msg = f"WARN: S3 log upload failed for {path.name}: {e.stderr.strip() if e.stderr else e}"
            if self._log_fh:
                self._log_fh.write(f"[{ts_utc()}] {msg}\n")
            print(msg, file=sys.stderr)


def ensure_run(run_id: str | None) -> Path:
    if run_id is None:
        run_id = run_id_new()
    run_dir = RUNS_DIR / run_id
    return run_dir


def list_runs() -> None:
    if not RUNS_DIR.exists():
        print("(no runs yet)")
        return
    runs = sorted([p for p in RUNS_DIR.iterdir() if p.is_dir()])
    if not runs:
        print("(no runs yet)")
        return
    print(f"{'RUN_ID':<24} {'MODE':<10} {'STATUS':<12} {'SUCC':>5} {'FAIL':>5} {'SKIP':>5}")
    print("-" * 70)
    for p in runs:
        state_path = p / "state.json"
        if not state_path.exists():
            print(f"{p.name:<24} (no state)")
            continue
        s = json.loads(state_path.read_text())
        vols = s.get("volumes", {})
        counts = {k: 0 for k in [STATUS_SUCCEEDED, STATUS_FAILED, STATUS_SKIPPED, STATUS_PENDING, STATUS_IN_PROGRESS]}
        for v in vols.values():
            counts[v.get("status", STATUS_PENDING)] += 1
        status = "complete" if s.get("completed_at") else "running/aborted"
        print(f"{p.name:<24} {s.get('mode',''):<10} {status:<12} "
              f"{counts[STATUS_SUCCEEDED]:>5} {counts[STATUS_FAILED]:>5} {counts[STATUS_SKIPPED]:>5}")


def pull_run_from_s3(bucket: str, run_id: str) -> None:
    """Download a run's artifacts from S3 into the local runs/ dir."""
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"s3://{bucket}/backups/feat-unified-snapshots/runs/{run_id}/"
    print(f"Pulling {prefix} → {run_dir}/")
    try:
        subprocess.run(
            ["aws", "s3", "cp", prefix, str(run_dir), "--recursive", "--only-show-errors"],
            check=True,
        )
        print(f"  Done. Inspect with: --status --run-id {run_id}")
    except subprocess.CalledProcessError as e:
        print(f"ERROR: pull failed: {e}", file=sys.stderr)
        sys.exit(1)


def show_status(run_id: str) -> None:
    run_dir = RUNS_DIR / run_id
    state_path = run_dir / "state.json"
    if not state_path.exists():
        print(f"ERROR: no run at {run_dir}")
        sys.exit(1)
    s = json.loads(state_path.read_text())
    vols = s.get("volumes", {})
    counts = {k: [] for k in [STATUS_SUCCEEDED, STATUS_FAILED, STATUS_SKIPPED, STATUS_PENDING, STATUS_IN_PROGRESS]}
    for vid, v in vols.items():
        counts.setdefault(v.get("status", STATUS_PENDING), []).append(vid)

    print(f"Run:        {s.get('run_id')}")
    print(f"Bucket:     {s.get('bucket')}")
    print(f"Mode:       {s.get('mode')}")
    print(f"Started:    {s.get('started_at')}")
    print(f"Completed:  {s.get('completed_at') or '(running/aborted)'}")
    print(f"Volumes:    {len(vols)}")
    for st in [STATUS_SUCCEEDED, STATUS_FAILED, STATUS_SKIPPED, STATUS_IN_PROGRESS, STATUS_PENDING]:
        print(f"  {st:<13}  {len(counts[st])}")

    if counts[STATUS_FAILED]:
        print("\nFailed volumes:")
        for vid in counts[STATUS_FAILED][:20]:
            err = vols[vid].get("error", "(no error recorded)")
            print(f"  {vid}: {err}")
        if len(counts[STATUS_FAILED]) > 20:
            print(f"  ... and {len(counts[STATUS_FAILED]) - 20} more")

    if counts[STATUS_IN_PROGRESS]:
        print(f"\nIn-progress (likely crashed): {counts[STATUS_IN_PROGRESS]}")


# ────────────────────────────────────────────────────────────────────────────
# Main conversion loop
# ────────────────────────────────────────────────────────────────────────────

def process_one(bucket: str, key: str, volume_id: str, dry_run: bool,
                state: RunState) -> str:
    """Process a single manifest. Returns final status."""
    start = time.monotonic()
    state.update(volume_id,
                 status=STATUS_IN_PROGRESS,
                 key=key,
                 started_at=ts_utc(),
                 error=None)

    try:
        orig, orig_bytes = download_manifest(bucket, key)
    except Exception as e:
        state.update(volume_id,
                     status=STATUS_FAILED,
                     error=f"download failed: {e}",
                     finished_at=ts_utc(),
                     duration_sec=round(time.monotonic() - start, 3))
        state.log(f"  {volume_id}: FAILED (download): {e}")
        return STATUS_FAILED

    pre_sha = sha256_short(orig_bytes)

    if is_already_converted(orig):
        state.update(volume_id,
                     status=STATUS_SKIPPED,
                     skip_reason="already in DAG format",
                     pre_sha256=pre_sha,
                     layers_count=0,
                     snapshots_count=len(orig.get("snapshots", {})),
                     finished_at=ts_utc(),
                     duration_sec=round(time.monotonic() - start, 3))
        state.log(f"  {volume_id}: SKIPPED (already converted, {len(orig.get('snapshots', {}))} snapshots)")
        return STATUS_SKIPPED

    if not is_old_format(orig):
        layers = orig.get("layers") or []
        reason = "empty manifest" if not layers else "unrecognized format"
        state.update(volume_id,
                     status=STATUS_SKIPPED,
                     skip_reason=reason,
                     pre_sha256=pre_sha,
                     layers_count=len(layers),
                     snapshots_count=0,
                     finished_at=ts_utc(),
                     duration_sec=round(time.monotonic() - start, 3))
        state.log(f"  {volume_id}: SKIPPED ({reason})")
        return STATUS_SKIPPED

    try:
        converted = convert_manifest(orig)
    except Exception as e:
        state.update(volume_id,
                     status=STATUS_FAILED,
                     error=f"convert failed: {e}",
                     pre_sha256=pre_sha,
                     finished_at=ts_utc(),
                     duration_sec=round(time.monotonic() - start, 3))
        state.log(f"  {volume_id}: FAILED (convert): {e}")
        return STATUS_FAILED

    layers_count = len(orig.get("layers") or [])
    snapshots_count = len(converted["snapshots"])
    consolidations = sum(1 for s in converted["snapshots"].values() if s.get("consolidation"))

    if dry_run:
        state.update(volume_id,
                     status=STATUS_PENDING,  # dry-run never finalizes as succeeded
                     dry_run_preview={
                         "layers_count": layers_count,
                         "snapshots_count": snapshots_count,
                         "consolidations": consolidations,
                         "head": converted["head"][:30],
                     },
                     pre_sha256=pre_sha,
                     finished_at=ts_utc(),
                     duration_sec=round(time.monotonic() - start, 3))
        state.log(f"  {volume_id}: WOULD CONVERT ({layers_count} layers → {snapshots_count} snapshots, {consolidations} consol)")
        return STATUS_PENDING

    try:
        uploaded_bytes = upload_manifest(bucket, key, converted)
    except Exception as e:
        state.update(volume_id,
                     status=STATUS_FAILED,
                     error=f"upload failed: {e}",
                     pre_sha256=pre_sha,
                     finished_at=ts_utc(),
                     duration_sec=round(time.monotonic() - start, 3))
        state.log(f"  {volume_id}: FAILED (upload): {e}")
        return STATUS_FAILED

    try:
        verify_converted(bucket, key, uploaded_bytes)
    except Exception as e:
        state.update(volume_id,
                     status=STATUS_FAILED,
                     error=f"verify failed: {e}",
                     pre_sha256=pre_sha,
                     post_sha256=sha256_short(uploaded_bytes),
                     finished_at=ts_utc(),
                     duration_sec=round(time.monotonic() - start, 3))
        state.log(f"  {volume_id}: FAILED (verify): {e}")
        return STATUS_FAILED

    state.update(volume_id,
                 status=STATUS_SUCCEEDED,
                 layers_count=layers_count,
                 snapshots_count=snapshots_count,
                 consolidations=consolidations,
                 head=converted["head"],
                 pre_sha256=pre_sha,
                 post_sha256=sha256_short(uploaded_bytes),
                 finished_at=ts_utc(),
                 duration_sec=round(time.monotonic() - start, 3))
    state.log(f"  {volume_id}: CONVERTED ({layers_count} layers → {snapshots_count} snapshots)")
    return STATUS_SUCCEEDED


def main():
    parser = argparse.ArgumentParser(
        description="Convert CAS manifests from linear layers to DAG snapshots format",
    )
    parser.add_argument("--bucket", help="S3 bucket name")
    parser.add_argument("--from-k8s-secret", action="store_true",
                        help="Resolve bucket name from k8s secret")
    parser.add_argument("--context", default="tesslate-beta-eks",
                        help="kubectl context (default: tesslate-beta-eks)")
    parser.add_argument("--volume-id", help="Convert a single volume (for validation)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Read-only — plan the run without modifying S3")
    parser.add_argument("--run-id",
                        help="Use an existing run directory (resume) or name a new one")
    parser.add_argument("--retry-failed", action="store_true",
                        help="In --run-id mode, only retry volumes with status=failed")
    parser.add_argument("--list-runs", action="store_true",
                        help="List prior runs and exit")
    parser.add_argument("--status", action="store_true",
                        help="Show status of --run-id and exit")
    parser.add_argument("--no-s3-log", action="store_true",
                        help="Disable uploading run logs to S3")
    parser.add_argument("--pull-from-s3", action="store_true",
                        help="Download a run's logs from S3 to local runs/ dir (requires --run-id and --bucket/--from-k8s-secret)")
    args = parser.parse_args()

    if args.list_runs:
        list_runs()
        return

    if args.status:
        if not args.run_id:
            parser.error("--status requires --run-id")
        show_status(args.run_id)
        return

    if args.from_k8s_secret:
        bucket = resolve_bucket_from_k8s(args.context)
    elif args.bucket:
        bucket = args.bucket
    else:
        parser.error("Either --bucket or --from-k8s-secret is required")

    if args.pull_from_s3:
        if not args.run_id:
            parser.error("--pull-from-s3 requires --run-id")
        pull_run_from_s3(bucket, args.run_id)
        return

    mode = "dry-run" if args.dry_run else "live"
    run_dir = ensure_run(args.run_id)
    resuming = run_dir.exists() and (run_dir / "state.json").exists()
    state = RunState.load(run_dir) if resuming else RunState(run_dir)
    state.open(bucket, mode, s3_logs=not args.no_s3_log)

    print(f"\n{'='*60}")
    print(f"Unified Snapshots Migration — Manifest Converter")
    print(f"Run ID:   {run_dir.name}  ({'resume' if resuming else 'new'})")
    print(f"Mode:     {mode.upper()}")
    print(f"Bucket:   {bucket}")
    print(f"Target:   {args.volume_id or 'ALL manifests'}")
    print(f"Run dir:  {run_dir}")
    print(f"{'='*60}\n")

    state.log(f"opened run (mode={mode}, bucket={bucket}, resuming={resuming})")

    # Determine the work list
    if args.retry_failed:
        if not resuming:
            print("ERROR: --retry-failed requires an existing --run-id")
            sys.exit(1)
        keys = [v["key"] for v in state.volumes().values()
                if v.get("status") == STATUS_FAILED and v.get("key")]
        print(f"Retrying {len(keys)} failed volume(s) from prior run.\n")
    else:
        keys = list_manifests(bucket, args.volume_id)
        if not keys and args.volume_id:
            print(f"ERROR: No manifest found for volume {args.volume_id}")
            sys.exit(1)
        if not keys:
            print("No manifests found.")
            state.close(summary={"total": 0})
            return

        # On resume, skip already-succeeded unless retry-failed
        if resuming:
            done = {vid for vid, v in state.volumes().items()
                    if v.get("status") == STATUS_SUCCEEDED}
            keys = [k for k in keys
                    if k.replace("manifests/", "").replace(".json", "") not in done]
            print(f"Resume: {len(done)} already succeeded, {len(keys)} to process.\n")

    # Pre-populate all volumes as pending so state reflects the plan
    for key in keys:
        vid = key.replace("manifests/", "").replace(".json", "")
        existing = state.volumes().get(vid, {})
        if existing.get("status") not in (STATUS_SUCCEEDED,):
            state.update(vid, status=existing.get("status", STATUS_PENDING), key=key)

    # Process
    total = len(keys)
    counts = {STATUS_SUCCEEDED: 0, STATUS_FAILED: 0, STATUS_SKIPPED: 0, STATUS_PENDING: 0}
    for i, key in enumerate(keys, 1):
        vid = key.replace("manifests/", "").replace(".json", "")
        if i % 25 == 1 or total <= 10:
            state.log(f"[{i}/{total}] {vid}")
        status = process_one(bucket, key, vid, args.dry_run, state)
        counts[status] = counts.get(status, 0) + 1

    summary = {
        "run_id": run_dir.name,
        "bucket": bucket,
        "mode": mode,
        "total": total,
        "succeeded": counts.get(STATUS_SUCCEEDED, 0),
        "failed": counts.get(STATUS_FAILED, 0),
        "skipped": counts.get(STATUS_SKIPPED, 0),
        "pending": counts.get(STATUS_PENDING, 0),
        "completed_at": ts_utc(),
    }
    state.close(summary)

    print(f"\n{'='*60}")
    print(f"Summary (run {run_dir.name}):")
    print(f"  Total processed:  {total}")
    print(f"  Succeeded:        {summary['succeeded']}")
    print(f"  Failed:           {summary['failed']}")
    print(f"  Skipped:          {summary['skipped']}")
    print(f"  Pending (dry):    {summary['pending']}")
    print(f"{'='*60}")
    print(f"\nInspect: python3 {sys.argv[0]} --status --run-id {run_dir.name}")
    if summary["failed"]:
        print(f"Retry:   python3 {sys.argv[0]} --run-id {run_dir.name} --retry-failed --bucket {bucket}")

    if summary["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
