# Suite 7 - Snapshots & timeline

> See [README.md](README.md) for format, priorities, severity, environments, and accounts.

**Why this suite matters:** When a customer builds with an AI agent, they take risks - they let the agent rewrite half the app, try a bold redesign, install a new dependency. They will only be brave if they know they can get back. Snapshots and the timeline are the product's safety net and its memory. The promise is simple: save a known-good point, see your history laid out, branch off to experiment, and restore without fear. The bar is high because the failure mode is the worst kind - lost work. A restore that warns clearly and reverts faithfully, a branch that truly diverges, a timeline that never loses a point: that's what makes a customer trust the agent enough to keep building.

**Suite prerequisites:** Tester A logged in. A project open in the builder with real content - files the agent has generated or you have edited (see suites 2-4). For branching and divergence cases you'll create multiple snapshots over the course of the suite.

---

### `SNAP-01` - Create a snapshot
- **Customer value:** A customer locks in a known-good version of their project before trying something risky.
- **Priority:** High
- **Pre:** A project with content open in the builder.
- **Scenario:**
  1. Open the Timeline / version history view.
  2. Create a snapshot and give it a meaningful label (e.g. "before redesign").
  3. Wait for it to finish.
- **What good looks like:**
  - Creating a snapshot is one obvious action; the label sticks.
  - It completes in a reasonable time with clear progress/confirmation - no indefinite spinner.
  - The new snapshot appears in the timeline with its label, author, and timestamp.
  - The customer can keep working immediately; the snapshot does not lock the project.
- **Watch for:** a snapshot that never finishes; the label being dropped; no confirmation so you can't tell if it worked; the editor freezing during the snapshot.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `SNAP-02` - Review the list of snapshots
- **Customer value:** A customer can see every version they've saved and tell them apart at a glance.
- **Priority:** Medium
- **Pre:** Several snapshots created (`SNAP-01` repeated a few times, ideally with different labels).
- **Scenario:**
  1. Open the timeline / snapshot list.
  2. Scan the snapshots.
- **What good looks like:**
  - All snapshots are listed, newest first, none missing.
  - Each row carries enough to identify it - label, author, and a readable timestamp ("2 hours ago" or a real date).
  - The list stays readable as it grows; it scrolls cleanly.
- **Watch for:** snapshots missing from the list; ambiguous "Snapshot" rows with no label; confusing or wrong timestamps; reverse order being wrong.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `SNAP-03` - Timeline graph view
- **Customer value:** A customer sees the shape of their project's history - a visual map, not just a flat list.
- **Priority:** Medium
- **Pre:** Multiple snapshots exist.
- **Scenario:**
  1. Open the timeline's graph view.
  2. Click a snapshot node; pan/zoom around the graph.
- **What good looks like:**
  - Snapshots render as connected nodes showing how versions follow one another.
  - Clicking a node clearly highlights it and surfaces its details.
  - The graph pans and zooms smoothly, like the architecture canvas.
  - The current/active point is visually obvious.
- **Watch for:** a tangled or unreadable graph; nodes not connected in the right order; clicking a node doing nothing; the graph disagreeing with the list view.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `SNAP-04` - Restore a snapshot, with a clear warning
- **Customer value:** A customer who took a wrong turn can roll the whole project back to a good version.
- **Priority:** Critical
- **Pre:** At least two snapshots; the current project state visibly differs from an earlier snapshot (e.g. files changed since).
- **Scenario:**
  1. Pick an earlier snapshot and choose Restore.
  2. Read the confirmation prompt.
  3. Confirm, then inspect the project's files and the preview.
- **What good looks like:**
  - Before anything is overwritten, a clear warning states that current unsaved changes will be lost - no silent restore.
  - After confirming, the project files genuinely revert to that snapshot's state - verify in the editor and the live preview.
  - The restore finishes in reasonable time with a clear "restored" confirmation.
  - The project is fully usable afterward - it starts, the preview renders.
- **Watch for:** no warning before destructive restore; a "restore" that doesn't actually change the files; a partial restore leaving a mixed/corrupted state; the project broken after restore.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `SNAP-05` - Create a branch from a snapshot
- **Customer value:** A customer experiments on a side branch without touching their main line of work.
- **Priority:** Medium
- **Pre:** A snapshot exists.
- **Scenario:**
  1. Select a snapshot and choose Create Branch.
  2. Give the branch a name.
- **What good looks like:**
  - A named branch is created starting from that exact snapshot.
  - The timeline / graph shows the branch as a distinct line off the chosen point.
  - It's clear which branch you are now working on.
- **Watch for:** the branch name being lost; the branch starting from the wrong point; no visible indication a branch was created or which one is active.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `SNAP-06` - Develop on a branch and see the divergence
- **Customer value:** A customer's experiment and their main line evolve independently and stay separable.
- **Priority:** Medium
- **Pre:** `SNAP-05` - a branch exists.
- **Scenario:**
  1. On the branch, make some changes (edit files or have the agent build something) and create a snapshot.
  2. Switch back to the main line.
  3. Look at the timeline graph.
- **What good looks like:**
  - The branch keeps its own history; its snapshot does not appear on the main line.
  - Switching back to the main line shows the main-line files, unaffected by the branch work.
  - The graph clearly shows the two lines diverging from the shared point.
- **Watch for:** branch changes bleeding into the main line; switching lines not actually changing the files; the graph showing one straight line when there should be two.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `SNAP-07` - Restore is non-destructive to history
- **Customer value:** A customer can restore an old version and still reach everything that came after it - restore moves you, it doesn't erase.
- **Priority:** Medium
- **Pre:** `SNAP-04` completed - you've restored to an earlier snapshot.
- **Scenario:**
  1. After the restore, make a change and create a new snapshot.
  2. Open the timeline and look for the snapshots that existed *before* the restore.
- **What good looks like:**
  - New snapshots layer on top of the restored point; you can keep building forward.
  - The snapshots that were taken after the point you restored to are still present and reachable in the timeline.
  - History is additive - restoring did not delete any past version.
- **Watch for:** post-restore snapshots silently deleted; the timeline truncated at the restore point; no way back to the version you restored *from*.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `SNAP-08` - Snapshotting a substantial project stays fast
- **Customer value:** A customer with a real, sizeable project can still snapshot quickly enough that it's a habit, not a chore.
- **Priority:** Low
- **Pre:** A project with substantial content (many files, dependencies installed).
- **Scenario:**
  1. Create a snapshot of the large project.
  2. Then restore it.
- **What good looks like:**
  - The snapshot completes without timing out and within a tolerable wait.
  - Progress feedback is shown for anything that takes more than a moment.
  - The resulting snapshot is fully usable - it lists and restores correctly.
- **Watch for:** the snapshot hanging or timing out on a big project; no progress feedback during a long operation; a snapshot that completes but is incomplete/corrupt.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `SNAP-09` - Empty-timeline state
- **Customer value:** A customer on a brand-new project sees an inviting, understandable timeline rather than an error.
- **Priority:** Low
- **Pre:** A freshly created project with no snapshots yet.
- **Scenario:**
  1. Open the Timeline view.
- **What good looks like:**
  - A clean empty state explains that no snapshots exist yet and how to create the first one.
  - No error, no broken graph, no blank screen.
  - The "create snapshot" action is easy to find from here.
- **Watch for:** an error or stack trace on an empty timeline; a confusing blank canvas; no guidance toward making the first snapshot.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

---

## Suite roll-up

| Result | Count |
|--------|-------|
| Pass | |
| Fail | |
| Blocked | |
| Not run | |

**Defects filed:** _list IDs_ - 
**Overall snapshots & timeline experience (1-5) & notes:** 
