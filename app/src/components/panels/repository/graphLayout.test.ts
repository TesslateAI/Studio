import { describe, expect, it } from 'vitest';
import { layoutCommitGraph, type GraphCommitInput } from './graphLayout';

/**
 * Helpful visualization for the tests below — commits are passed in
 * newest-first, matching what GitHub's `list commits` API returns.
 */

describe('layoutCommitGraph', () => {
  it('puts a simple linear history on a single lane', () => {
    const commits: GraphCommitInput[] = [
      { sha: 'c3', parents: ['c2'] },
      { sha: 'c2', parents: ['c1'] },
      { sha: 'c1', parents: [] },
    ];
    const layout = layoutCommitGraph(commits);

    expect(layout.nodes.map((n) => n.lane)).toEqual([0, 0, 0]);
    expect(layout.laneCount).toBe(1);
    // Two edges — c3 → c2 and c2 → c1. c1 has no parents.
    expect(layout.edges).toHaveLength(2);
    expect(layout.edges.every((e) => e.fromLane === 0 && e.toLane === 0)).toBe(true);
  });

  it('tracks merge commits on their own lane and produces an isMergeIn edge', () => {
    // Shape:
    //   c5 (merge of c4 + b1)
    //   c4
    //   b1
    //   c3
    //   c1
    const commits: GraphCommitInput[] = [
      { sha: 'c5', parents: ['c4', 'b1'] },
      { sha: 'c4', parents: ['c3'] },
      { sha: 'b1', parents: ['c3'] },
      { sha: 'c3', parents: ['c1'] },
      { sha: 'c1', parents: [] },
    ];
    const layout = layoutCommitGraph(commits);

    // The merge commit should sit at lane 0.
    const c5 = layout.nodes.find((n) => n.sha === 'c5')!;
    expect(c5.lane).toBe(0);
    expect(c5.isMergeCommit).toBe(true);

    // b1 should land on a side lane (>= 1).
    const b1 = layout.nodes.find((n) => n.sha === 'b1')!;
    expect(b1.lane).toBeGreaterThanOrEqual(1);

    // There should be a merge-in edge from c5 → b1.
    const mergeEdge = layout.edges.find(
      (e) => layout.nodes[e.fromIndex].sha === 'c5' && e.isMergeIn === true
    );
    expect(mergeEdge).toBeDefined();
    expect(mergeEdge!.toLane).toBe(b1.lane);

    // laneCount must be >= 2 because the merge branched out.
    expect(layout.laneCount).toBeGreaterThanOrEqual(2);
  });

  it('emits one edge per parent reference', () => {
    const commits: GraphCommitInput[] = [
      { sha: 'm', parents: ['a', 'b', 'c'] },
      { sha: 'a', parents: [] },
      { sha: 'b', parents: [] },
      { sha: 'c', parents: [] },
    ];
    const layout = layoutCommitGraph(commits);

    // Three edges out of the octopus merge.
    const mEdges = layout.edges.filter((e) => layout.nodes[e.fromIndex].sha === 'm');
    expect(mEdges).toHaveLength(3);
    // First parent is not a merge-in; the rest are.
    expect(mEdges[0].isMergeIn).toBe(false);
    expect(mEdges[1].isMergeIn).toBe(true);
    expect(mEdges[2].isMergeIn).toBe(true);
  });

  it('handles parents that fall outside the slice (long history, short page)', () => {
    const commits: GraphCommitInput[] = [{ sha: 'top', parents: ['gone'] }];
    const layout = layoutCommitGraph(commits);

    expect(layout.nodes[0].lane).toBe(0);
    expect(layout.edges).toHaveLength(1);
    expect(layout.edges[0].toIndex).toBeNull();
    expect(layout.edges[0].toLane).toBe(0);
  });

  it('reuses a lane when a branch terminates instead of fanning out forever', () => {
    // Sequence: top merge consumes a branch that died immediately.
    // We should not end up with more than 2 lanes.
    const commits: GraphCommitInput[] = [
      { sha: 'm', parents: ['a', 'b'] },
      { sha: 'b', parents: ['a'] },
      { sha: 'a', parents: [] },
    ];
    const layout = layoutCommitGraph(commits);
    expect(layout.laneCount).toBeLessThanOrEqual(2);
  });

  it('is deterministic — same input, same output', () => {
    const commits: GraphCommitInput[] = [
      { sha: 'c4', parents: ['c3', 'side'] },
      { sha: 'c3', parents: ['c2'] },
      { sha: 'side', parents: ['c2'] },
      { sha: 'c2', parents: ['c1'] },
      { sha: 'c1', parents: [] },
    ];
    const a = layoutCommitGraph(commits);
    const b = layoutCommitGraph(commits);
    expect(a).toEqual(b);
  });
});
