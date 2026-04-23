# Snapshots Router

**File**: `orchestrator/app/routers/snapshots.py`

**Base path**: `/api/projects/{project_id}/snapshots`

## Purpose

Project timeline / branching built on the CAS (content-addressable) snapshot system backed by btrfs + Volume Hub. Lets users create named branches, snapshot the current volume, view the timeline graph, and restore a prior snapshot.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/` | owner | List CAS snapshots for the project. |
| GET | `/graph` | owner | Timeline graph (nodes + edges) for rendering the branch tree. |
| POST | `/branches` | owner | Create a named branch at the current head (201). |
| POST | `/` | owner | Create a new snapshot of the current project volume (201). |
| POST | `/{snapshot_hash}/restore` | owner | Restore the project volume to a given snapshot. |

## Auth

All endpoints require `current_active_user` and project ownership/team access.

## Related

- Models: `ProjectSnapshot` in [models.py](../../../orchestrator/app/models.py).
- Service: [../../../orchestrator/app/services/snapshot_manager.py](../../../orchestrator/app/services/snapshot_manager.py).
- Volume Hub + btrfs: `services/btrfs-csi/`.
