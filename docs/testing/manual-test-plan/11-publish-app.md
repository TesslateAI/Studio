# Suite 11 - Publish a Project as an App

> See [README.md](README.md) for format, priorities, severity, environments, and accounts.

**Why this suite matters:** Tesslate Apps is where a customer's project stops being a private workspace and becomes a **product other people install**. The creator journey here is high-stakes: they've built something real, and publishing must feel safe, guided, and honest. A good publish flow tells the creator what's ready and what isn't *before* they submit, offers concrete fixes (add a database, add storage), produces an immutable version they can trust, and keeps them informed as it moves through review. A bad one ships a broken App or leaves the creator staring at an opaque "pending" forever. Judge this on whether a creator finishes feeling **confident their App is sound and they know where it stands**.

**Suite prerequisites:** Tester A logged in on a creator-capable account. A configured project Tester A owns that runs cleanly (suites 2 and 5) - this is the App source project. For the approval-progression cases, an Admin account or coordination with the team (the admin-side mechanics are detailed in suites 12/13).

---

### `APP-PUB-01` - Generate a publish draft
- **Customer value:** A creator gets a starting-point manifest and a readiness checklist so they aren't authoring an App spec from a blank page.
- **Priority:** High
- **Pre:** A configured, runnable project Tester A owns, open in the builder.
- **Scenario:**
  1. From the project, open "Publish as App".
  2. Generate a publish draft.
  3. Review the generated draft manifest and the readiness checklist.
  4. Generate the draft a second time.
- **What good looks like:**
  - A draft manifest is produced that genuinely reflects the project (containers, ports, surfaces).
  - A readiness checklist appears with pass / warn / fail items the creator can act on.
  - Each checklist item is specific enough to fix - not "something is wrong".
  - Re-generating is safe and idempotent - it doesn't create duplicates or corrupt the draft.
- **Watch for:** an empty or generic draft that ignores the real project; a checklist with no actionable detail; re-generating spawning duplicate drafts.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-PUB-02` - Pre-publish state & replica safety check
- **Customer value:** A creator is warned *before* publishing if their App would lose data or misbehave when run by many installers.
- **Priority:** High
- **Pre:** `APP-PUB-01` done; the publish "check" available.
- **Scenario:**
  1. Run the pre-publish state/replica check.
  2. Read what it reports about the project's state model and replica behavior.
- **What good looks like:**
  - The check detects how the App stores state (e.g. local files, in-container DB) and whether that is safe.
  - It clearly explains any risk - e.g. "state in the container will not survive restarts / won't be isolated per install".
  - The warnings are understandable to a creator who isn't an infrastructure expert.
- **Watch for:** the check passing an App that obviously stores state unsafely; jargon-heavy warnings a creator can't act on; the check not running at all.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-PUB-03` - Act on a state-upgrade offer (add Postgres / object storage / KV)
- **Customer value:** When the safety check flags a problem, the creator is offered a concrete one-click fix instead of being left stuck.
- **Priority:** Medium
- **Pre:** `APP-PUB-02` surfaced at least one state/replica concern.
- **Scenario:**
  1. From the safety-check results, accept an upgrade offer - e.g. add a Postgres database, add object storage, or add a KV store.
  2. Apply it, then re-run the pre-publish check.
- **What good looks like:**
  - The upgrade offers are relevant to the actual problem found (a stateful App is offered a real datastore).
  - Accepting an offer actually wires the new service into the project/manifest.
  - Re-running the check shows the previously-flagged concern is now resolved.
- **Watch for:** an upgrade offer that does nothing; the new service added but not connected to the App; the warning persisting after the fix is applied.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-PUB-04` - Review and complete the App manifest
- **Customer value:** A creator can review and finalize what they're about to publish - identity, pricing, surfaces, billing.
- **Priority:** Medium
- **Pre:** A publish draft generated; checklist showing no blocking failures.
- **Scenario:**
  1. Open the full manifest/publish form.
  2. Review the App's name, handle, category, description, pricing/billing, and surfaces.
  3. Adjust a field and confirm the change is reflected.
- **What good looks like:**
  - The manifest is presented in a reviewable, human-readable form - not raw JSON the creator must hand-edit.
  - Each section (identity, billing, surfaces) is clear about what it means for installers.
  - Edits are captured and reflected before submission.
- **Watch for:** the creator forced to edit raw JSON with no guidance; sections that are unexplained; edits lost on navigation.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-PUB-05` - Submit the App to publish
- **Customer value:** The creator's central goal - turn their project into a published, versioned App that's on the path to being installable.
- **Priority:** Critical
- **Pre:** `APP-PUB-04` done; the readiness checklist has no blocking failures.
- **Scenario:**
  1. Submit the manifest to publish.
  2. Observe the result and any link to the App's marketplace page.
  3. Separately, attempt to submit with an invalid manifest and with a duplicate version number.
- **What good looks like:**
  - Submission succeeds and creates an **App** plus an **immutable version**.
  - The creator gets a clear confirmation and can deep-link to the App's (not-yet-live) marketplace page.
  - An invalid manifest is rejected with **specific, actionable** validation errors.
  - A duplicate version number is rejected with a clear message.
- **Watch for:** a submit that "succeeds" but creates nothing; vague validation errors; a duplicate version silently overwriting the previous one.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-PUB-06` - App and immutable version exist after publish
- **Customer value:** A creator can trust that what they published is fixed in place and won't change under installers' feet.
- **Priority:** High
- **Pre:** `APP-PUB-05` completed.
- **Scenario:**
  1. Open the App's page / the creator's App management view.
  2. Confirm the App record and its version are present.
  3. Inspect the published version's contents.
- **What good looks like:**
  - The App exists with the identity the creator gave it (slug, handle, category).
  - The published version is listed with its semver and is marked immutable - its manifest and bundle are frozen.
  - The version's contents match what was submitted.
- **Watch for:** a version that appears editable after publish; the App existing but with no version; identity fields not matching what was submitted.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-PUB-07` - Submission enters the approval pipeline (stage 0 auto-checks)
- **Customer value:** A creator sees their submission immediately picked up for review and gets fast automatic feedback.
- **Priority:** High
- **Pre:** `APP-PUB-05` completed.
- **Scenario:**
  1. Open the submission's status / checks view.
  2. Review the stage-0 automatic check results.
- **What good looks like:**
  - The submission is shown in an early review stage with a clear status.
  - Automatic checks have run - manifest validity, feature support, billing disclosure present - each with a pass/warn/fail result.
  - A clean submission advances; a hard failure is clearly marked as rejected with the failing check named.
- **Watch for:** a submission stuck before stage 0 ever runs; checks that report no result; a failing check with no indication of which check or why.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-PUB-08` - Track approval progress through admin review stages
- **Customer value:** Through the multi-stage admin review, the creator always knows what stage their App is at and isn't left in the dark.
- **Priority:** Medium
- **Pre:** A submission past stage 0; an Admin progressing it (coordinate, or revisit after suites 12/13).
- **Scenario:**
  1. As the creator, open the submission status periodically as the Admin advances it through review stages.
  2. Note how each stage transition is communicated.
- **What good looks like:**
  - The creator-facing view names the current review stage in plain terms.
  - Each advance is reflected for the creator without contacting support.
  - The creator can tell the difference between "still in review" and "stalled".
- **Watch for:** the creator view never updating while the admin progresses it; stage names that mean nothing to a creator; no sense of expected timeline.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-PUB-09` - See a rejection reason and respond
- **Customer value:** If an App is rejected, the creator learns exactly why and can fix and resubmit instead of giving up.
- **Priority:** High
- **Pre:** A submission that an Admin rejects with a reason (coordinate with suite 12/13).
- **Scenario:**
  1. As the creator, open the rejected submission.
  2. Read the rejection reason / decision notes.
  3. Confirm what the creator can do next.
- **What good looks like:**
  - The rejection reason is shown to the creator in plain language.
  - It is specific enough to act on - the creator knows what to change.
  - The creator has a clear next step (fix and republish a new version).
- **Watch for:** a rejection with no reason; reasons full of internal jargon; a rejected App with no path forward; the rejected App still appearing installable.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-PUB-10` - Republish a new version
- **Customer value:** A creator improves their App and ships an update without disturbing what's already published.
- **Priority:** Medium
- **Pre:** An already-published App; a change made to the source project.
- **Scenario:**
  1. From the App source project, publish again with a higher version number.
  2. Confirm the App's version history.
- **What good looks like:**
  - The new version is appended to the **same** App.
  - Previous versions remain present and immutable - the update doesn't rewrite history.
  - The new version enters the approval pipeline on its own, like the first.
- **Watch for:** the new version replacing rather than appending; old versions becoming editable or disappearing; the App identity changing on republish.
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
**Overall publish-an-App experience (1-5) & notes:** 
