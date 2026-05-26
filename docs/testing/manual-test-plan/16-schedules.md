# Suite 16 - Schedules & automations

> See [README.md](README.md) for format, priorities, severity, environments, and accounts.

**Why this suite matters:** Most agent runs are something a customer asks for and waits on. Schedules turn the agent into something that works *for* the customer while they're away - a recurring report every morning, a check every five minutes, a digest every Friday. The value is in the agent firing on its own, at the right time, doing the work, and delivering the result somewhere the customer will see it. That only lands if the whole loop is trustworthy: a schedule that's easy to express ("every 5 minutes" should just work), a next-run time the customer can believe, a run that actually happens on time, and a result that actually arrives. A schedule that drifts, silently skips, or runs but delivers nothing is worse than no automation - the customer was counting on it.

**Suite prerequisites:** Tester A logged in, on a tier with enough credits for several scheduled agent runs. A project the agent can run against (see suites 2-4). A delivery target available where you can confirm results land (e.g. a chat session, or a connected messaging channel from suite 15). To verify firing, you'll create at least one schedule with a short, frequent interval.

---

### `SCHED-01` - Create a schedule (natural language)
- **Customer value:** A customer sets up a recurring agent run by describing the cadence in plain English.
- **Priority:** High
- **Pre:** A project the customer can edit.
- **Scenario:**
  1. Open Schedules / Automations and start a new schedule.
  2. Enter the cadence in natural language - e.g. "every 5 minutes" or "every weekday at 9am".
  3. Give it a prompt for the agent, a timezone, and a delivery target; save.
- **What good looks like:**
  - The natural-language cadence is accepted and correctly understood - it normalizes to the right schedule.
  - A next-run time appears immediately and matches the cadence you described.
  - The schedule saves with its prompt, timezone, and delivery target intact.
  - The whole form is approachable - a non-technical customer could set this up.
- **Watch for:** "every 5 minutes" being misread as something else; no next-run time shown; the timezone or prompt silently dropped; a confusing error on a perfectly reasonable phrase.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `SCHED-02` - Create a schedule (cron expression)
- **Customer value:** A power user expresses an exact cadence with a standard cron expression.
- **Priority:** Medium
- **Pre:** Schedule form open.
- **Scenario:**
  1. Create a schedule using a raw 5-field cron expression (e.g. `0 9 * * *`).
  2. Set the timezone and check the computed next run.
- **What good looks like:**
  - The cron expression is accepted without complaint.
  - The next-run time is computed correctly *for the chosen timezone* - verify it against what `0 9 * * *` should mean.
  - The schedule behaves identically to a natural-language one from here on.
- **Watch for:** a valid cron expression rejected; next-run computed in the wrong timezone (e.g. server UTC instead of the customer's); next-run off by an hour or a day.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `SCHED-03` - Schedules list shows next run, last run, and status
- **Customer value:** A customer sees all their automations at a glance and trusts what each one will do next.
- **Priority:** Medium
- **Pre:** Two or more schedules created.
- **Scenario:**
  1. Open the schedules list.
  2. Scan each schedule's details.
- **What good looks like:**
  - Each schedule shows its next run, last run, status (active/paused), and a run count.
  - The next-run times are sensible and consistent with each schedule's cadence.
  - The list is clear enough that the customer knows what's going to happen and when, without opening each one.
  - Filtering by project (if offered) narrows the list correctly.
- **Watch for:** missing or wrong next-run times; last-run showing nothing even after a run happened; status not matching reality; the list confusing or cluttered.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `SCHED-04` - A schedule fires, runs the agent, and delivers the result
- **Customer value:** The core promise - the agent runs on its own at the scheduled time and the result reaches the customer.
- **Priority:** Critical
- **Pre:** A schedule set to a short, frequent cadence (e.g. every minute / every 5 minutes), with a prompt that produces a visible result and a delivery target you can watch.
- **Scenario:**
  1. Note the next-run time.
  2. Wait through the scheduled time.
  3. Check the delivery target, the schedule's run history, and the project's chat/activity.
- **What good looks like:**
  - The agent task actually runs at (or very close to) the scheduled time - not skipped, not late.
  - The agent does the work described in the prompt - a real run, not an empty one.
  - The result is delivered to the configured target where the customer expects it.
  - The schedule's last-run timestamp and run count update, and the next-run time advances to the following slot.
- **Watch for:** the schedule never firing; firing far from the scheduled time; the run happening but producing nothing; the result never delivered; last-run/next-run not updating; duplicate runs for one slot.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `SCHED-05` - Pause and resume a schedule
- **Customer value:** A customer can put an automation on hold without losing its setup, and bring it back later.
- **Priority:** Medium
- **Pre:** An active, frequently-firing schedule.
- **Scenario:**
  1. Pause the schedule.
  2. Wait past one or two of its scheduled times and confirm it does not run.
  3. Resume it and wait for the next slot.
- **What good looks like:**
  - Pausing is immediate and the status clearly changes to paused.
  - While paused, the schedule does **not** fire - no runs, no deliveries.
  - Resuming reactivates it and it fires again on the next slot, with all its settings intact.
- **Watch for:** a paused schedule still firing; resume not actually reactivating it; the prompt/target lost across pause/resume; the status display not matching real behavior.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `SCHED-06` - Edit a schedule
- **Customer value:** A customer adjusts an automation - change the cadence, the prompt, the timezone - without recreating it.
- **Priority:** Medium
- **Pre:** An existing schedule.
- **Scenario:**
  1. Open the schedule and change its cadence (and optionally its prompt or timezone).
  2. Save, then check the next-run time.
- **What good looks like:**
  - The edits save and persist.
  - The next-run time recomputes to reflect the new cadence - it doesn't keep showing the old one.
  - The next time it fires, it uses the updated prompt/cadence, not the old one.
- **Watch for:** next-run not recomputing after a cadence change; the schedule still running the old prompt; edits silently not saving.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `SCHED-07` - Repeat-count limit auto-deactivates the schedule
- **Customer value:** A customer can set up an automation that runs a fixed number of times and then stops itself - no manual cleanup.
- **Priority:** Low
- **Pre:** A schedule created with a repeat count (e.g. 3) and a short cadence.
- **Scenario:**
  1. Let the schedule run its full repeat count.
  2. Wait past the slot where a further run would have happened.
- **What good looks like:**
  - The schedule runs exactly the configured number of times - no more, no fewer.
  - After the final run it automatically deactivates and stops firing.
  - The list shows it as completed/inactive, with a run count matching the limit.
- **Watch for:** the schedule continuing to fire past its repeat count; it stopping early before reaching the count; the status still showing "active" after it's done.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `SCHED-08` - Delete a schedule
- **Customer value:** A customer removes an automation they no longer want and trusts that it's truly gone.
- **Priority:** Medium
- **Pre:** A disposable, active schedule.
- **Scenario:**
  1. Delete the schedule.
  2. Wait past its next would-be run time.
- **What good looks like:**
  - The schedule is removed from the list immediately.
  - It does not fire again after deletion - no orphaned run, no stray delivery.
  - It stays gone after a refresh.
- **Watch for:** a deleted schedule still firing once or twice afterward; the schedule reappearing on refresh; no confirmation before deleting an active automation.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `SCHED-09` - A scheduled run's failure is visible, not silent
- **Customer value:** When a scheduled run can't complete, the customer finds out - automation they can't see failing is automation they can't trust.
- **Priority:** Medium
- **Pre:** A schedule whose run will fail or be blocked (e.g. a prompt that can't succeed, or run the account low on credits).
- **Scenario:**
  1. Let the schedule fire.
  2. Check the schedule's run history / status and any notifications.
- **What good looks like:**
  - The failed run is recorded with a clear, human-readable reason - not silently dropped.
  - The schedule itself stays intact and continues on its cadence (a bad run doesn't kill the automation).
  - The customer has a way to notice the failure - a status, a flag, or a notification - rather than discovering it by the missing result.
- **Watch for:** a failed run leaving no trace; the whole schedule silently deactivating after one failure; a raw stack trace instead of a readable reason; no signal at all that something went wrong.
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
**Overall schedules & automations experience (1-5) & notes:** 
