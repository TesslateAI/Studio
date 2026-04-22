/**
 * Commit-graph lane assignment.
 *
 * GitHub returns a flat list of commits ordered newest-first. To draw a
 * GitKraken-style timeline we need two things per commit:
 *
 *   1. A **lane index** — which vertical column the dot sits in.
 *   2. The set of **parent edges** — lines connecting this commit to each
 *      of its parents further down the timeline.
 *
 * This file implements a small, deterministic lane-allocation heuristic
 * that works well enough for 100-ish commits without pulling in a real DAG
 * layout library. It's not a perfect `git log --graph` — it's a readable
 * approximation that makes merges and branches visible.
 *
 * Algorithm:
 *   - Walk commits in the given order (newest → oldest).
 *   - Maintain a mutable `activeLanes` array. Each slot is either `null`
 *     (free) or an SHA the lane is "reserved for" (i.e. the next commit
 *     that should land in that lane).
 *   - When we visit a commit, first try to claim the lane that was reserved
 *     for its SHA; otherwise take the lowest-numbered free lane (or append
 *     a new one).
 *   - The commit's FIRST parent inherits the same lane.
 *   - Additional parents (merge commits) spawn new lanes. We prefer any
 *     lane that's already reserved for that parent, otherwise take the
 *     leftmost free slot.
 *   - When a lane's reserved SHA falls off the end (e.g. we ran out of
 *     commits), it stays "active" until the parent is reached or forever.
 *
 * Outputs are pure data — the React layer turns them into SVG.
 */

export interface GraphCommitInput {
  sha: string;
  parents: string[];
}

export interface GraphEdge {
  /** Index of the source commit in the laid-out list. */
  fromIndex: number;
  /** Index of the target commit, or `null` if the parent is not in the slice. */
  toIndex: number | null;
  /** Lane the source commit sits in. */
  fromLane: number;
  /** Lane the target commit sits in (or the parent's reserved lane if off-slice). */
  toLane: number;
  /**
   * `true` for the merge-in edge of a merge commit (the non-first parent).
   * UI layer can render these with a curved/diagonal stroke instead of a
   * straight vertical line.
   */
  isMergeIn: boolean;
}

export interface GraphNode {
  sha: string;
  lane: number;
  parents: string[];
  isMergeCommit: boolean;
}

export interface GraphLayout {
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** Max lane index used + 1 — the canvas should reserve this many columns. */
  laneCount: number;
}

export function layoutCommitGraph(commits: readonly GraphCommitInput[]): GraphLayout {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];

  /**
   * `activeLanes[i]` holds:
   *   - `null` if the lane is currently free,
   *   - otherwise the SHA of the commit expected to land there next.
   */
  const activeLanes: (string | null)[] = [];
  const indexBySha = new Map<string, number>();

  const claimLane = (preferredSha: string): number => {
    // Try: a lane already reserved for this SHA.
    for (let i = 0; i < activeLanes.length; i++) {
      if (activeLanes[i] === preferredSha) {
        return i;
      }
    }
    // Else: leftmost empty lane.
    for (let i = 0; i < activeLanes.length; i++) {
      if (activeLanes[i] === null) {
        return i;
      }
    }
    // Else: append.
    activeLanes.push(null);
    return activeLanes.length - 1;
  };

  let maxLane = 0;

  for (let i = 0; i < commits.length; i++) {
    const commit = commits[i];
    const lane = claimLane(commit.sha);
    if (lane > maxLane) maxLane = lane;

    // Free all OTHER lanes that were reserved for this SHA — happens when
    // multiple merges reference the same parent and we only consume it once.
    for (let j = 0; j < activeLanes.length; j++) {
      if (j !== lane && activeLanes[j] === commit.sha) {
        activeLanes[j] = null;
      }
    }

    // This lane is no longer "waiting for this SHA" — it has arrived.
    activeLanes[lane] = null;

    indexBySha.set(commit.sha, i);
    const isMergeCommit = commit.parents.length > 1;
    nodes.push({ sha: commit.sha, lane, parents: [...commit.parents], isMergeCommit });

    // First parent inherits this lane.
    if (commit.parents.length > 0) {
      activeLanes[lane] = commit.parents[0];
    }

    // Remaining parents spawn side lanes.
    for (let p = 1; p < commit.parents.length; p++) {
      const parent = commit.parents[p];
      // Prefer a lane already reserved for this parent so we don't fan out
      // unnecessarily on octopus merges.
      let sideLane = -1;
      for (let j = 0; j < activeLanes.length; j++) {
        if (activeLanes[j] === parent) {
          sideLane = j;
          break;
        }
      }
      if (sideLane === -1) {
        // Take leftmost free lane, else append.
        for (let j = 0; j < activeLanes.length; j++) {
          if (activeLanes[j] === null) {
            sideLane = j;
            break;
          }
        }
        if (sideLane === -1) {
          activeLanes.push(parent);
          sideLane = activeLanes.length - 1;
        } else {
          activeLanes[sideLane] = parent;
        }
      }
      if (sideLane > maxLane) maxLane = sideLane;
    }
  }

  // Second pass — emit edges now that every node has a lane.
  for (let i = 0; i < commits.length; i++) {
    const commit = commits[i];
    const node = nodes[i];
    commit.parents.forEach((parentSha, parentIdx) => {
      const childIdx = indexBySha.get(parentSha);
      let toLane: number;
      if (childIdx != null) {
        toLane = nodes[childIdx].lane;
      } else {
        // Parent lies outside the slice; route the edge to whichever lane is
        // currently reserved for that parent (or default to the source lane
        // so the line trails straight down off-canvas).
        let reservedLane = -1;
        for (let j = 0; j < activeLanes.length; j++) {
          if (activeLanes[j] === parentSha) {
            reservedLane = j;
            break;
          }
        }
        toLane = reservedLane !== -1 ? reservedLane : node.lane;
      }

      edges.push({
        fromIndex: i,
        toIndex: childIdx ?? null,
        fromLane: node.lane,
        toLane,
        isMergeIn: parentIdx > 0,
      });
    });
  }

  return {
    nodes,
    edges,
    laneCount: maxLane + 1,
  };
}

/** Stable color for a given lane index — cycles through a 6-color palette. */
const LANE_COLORS = [
  '#3b82f6', // blue
  '#22c55e', // green
  '#f97316', // orange
  '#a855f7', // purple
  '#14b8a6', // teal
  '#ec4899', // pink
];

export function laneColor(lane: number): string {
  return LANE_COLORS[lane % LANE_COLORS.length];
}
