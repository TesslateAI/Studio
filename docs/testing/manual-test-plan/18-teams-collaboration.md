# Suite 18 - Teams & collaboration

> See [README.md](README.md) for format, priorities, severity, environments, and accounts.

**Why this suite matters:** Most real customers don't build alone. A small team, an agency, or a couple of founders want to share a workspace, hand projects back and forth, and see what each other did. Teams are how Tesslate Studio stops being a single-player IDE and becomes something an organization adopts. This suite is **not** about permission enforcement (a viewer getting a 403 is covered by automated tests) - it's about whether collaboration actually *works* and *feels coherent*: does an invite land, does the project list follow you when you switch teams, can two people genuinely co-build on the same project without stepping on each other, and can an admin trust what they see in the activity log.

**Suite prerequisites:** Tester A and Tester B, each with a separate real email inbox. Tester A on a paid tier if possible (higher project/member limits). Both should be able to create a project and run the agent (see suites 2 and 4). Some cases need both testers acting at roughly the same time - coordinate so one can drive while the other observes.

---

### `TEAM-01` - Create an organization team
- **Customer value:** A customer moving past solo use spins up a shared workspace for their company or side project.
- **Priority:** Critical
- **Pre:** Tester A logged in; currently on the personal team.
- **Scenario:**
  1. Open the team switcher and choose to create a new team.
  2. Enter a team name (e.g. "Acme QA"); accept or adjust the suggested slug; submit.
  3. After creation, look at the team switcher and the dashboard.
- **What good looks like:**
  - The team is created without a long wait and you land in it as its admin.
  - The new team appears in the switcher alongside the personal team.
  - The dashboard now shows the new team's (empty) project space, with a sensible empty state - not an error or a stale list.
- **Watch for:** the team created but not selected; the personal team's projects still showing; a confusing slug error with no guidance on what's allowed.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `TEAM-02` - Personalize the team (name & avatar)
- **Customer value:** A team should feel like *theirs* - recognizable in the switcher and to teammates.
- **Priority:** Medium
- **Pre:** Tester A is admin of the org team from `TEAM-01`.
- **Scenario:**
  1. Open team settings; change the team name.
  2. Upload a team avatar image.
  3. Save, then look at the team switcher, dashboard header, and member list.
- **What good looks like:**
  - The new name and avatar appear consistently everywhere the team is shown.
  - The avatar is cropped/rendered cleanly, not stretched or pixelated.
  - The change is immediate - no need to hard-refresh to see it.
- **Watch for:** the avatar showing in one place but not another; an oversized image rejected with no clear size guidance; the old name lingering in the switcher.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `TEAM-03` - Invite a teammate by email
- **Customer value:** A customer brings a specific person onto the team by sending them an invite.
- **Priority:** Critical
- **Pre:** Tester A is admin of the org team; Tester B's email address ready.
- **Scenario:**
  1. Open the team's Members area and start an invitation.
  2. Enter Tester B's email, choose the **editor** role, and send.
  3. Check the pending-invites list; then check Tester B's inbox.
- **What good looks like:**
  - The invitation shows up immediately as "pending" with the email and role.
  - Tester B receives an invite email within a minute or two, with the team name and a clear, working link.
  - The email reads like a real product invitation - not a raw token or a broken-looking template.
- **Watch for:** no email arriving; the email going to spam with a suspicious sender; the invite link pointing to the wrong place; the pending list not updating.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `TEAM-04` - Accept the invitation and join
- **Customer value:** The invited person clicks through and lands inside the team, ready to work.
- **Priority:** Critical
- **Pre:** `TEAM-03` done; Tester B has the invite email.
- **Scenario:**
  1. As Tester B, open the invite link.
  2. If a preview page shows the team name and role, review it; then log in or register as Tester B.
  3. Accept the invitation.
  4. Open the team switcher and the dashboard as Tester B.
- **What good looks like:**
  - The invite preview clearly states which team and role Tester B is joining.
  - After accepting, the team appears in Tester B's switcher and they can open it.
  - Tester B sees the team's shared projects (per the editor role) without extra steps.
  - On Tester A's side, the member now shows as active rather than pending.
- **Watch for:** the link failing for an already-logged-in user; Tester B joining but seeing no projects; the invite still showing "pending" on Tester A's side after acceptance.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `TEAM-05` - Share a reusable invite link
- **Customer value:** An admin onboarding several people wants one link to drop in Slack rather than typing each email.
- **Priority:** High
- **Pre:** Tester A is admin of the org team.
- **Scenario:**
  1. In Members, create a shareable invite **link** - set a role and an expiry; optionally a max-uses limit.
  2. Copy the link.
  3. Open it in a fresh session (or as a different test identity) and accept.
  4. Return to the admin view and check the link's use count.
- **What good looks like:**
  - Copying the link is one click with clear "copied" feedback.
  - Opening the link shows the same clear team/role preview as an email invite.
  - The joiner lands in the team; the link's use-count increments.
  - The link is reusable up to its limit and clearly shows its expiry/usage state.
- **Watch for:** the link silently doing nothing; use-count not updating; an expired/exhausted link giving a cryptic error instead of a friendly "this link is no longer valid".
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `TEAM-06` - Switch teams and the workspace follows
- **Customer value:** A customer in multiple teams (their personal one plus a company one) expects switching to instantly re-scope everything.
- **Priority:** High
- **Pre:** Tester A is a member of at least two teams, each with at least one distinct project.
- **Scenario:**
  1. From the dashboard, switch the active team in the switcher.
  2. Observe the project list, recent activity, and any team-scoped settings.
  3. Refresh the page; switch again; navigate into a project and back.
- **What good looks like:**
  - The project list, dashboard, and team-scoped views all swap to the selected team within a moment.
  - There is never a flash of the *other* team's projects.
  - The selected team persists across a refresh - you stay where you were.
- **Watch for:** stale projects from the previous team lingering; the switch needing a manual refresh; the selection resetting to the personal team on reload.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `TEAM-07` - Review the team member list
- **Customer value:** An admin wants an at-a-glance picture of who is on the team and in what capacity.
- **Priority:** Medium
- **Pre:** A team with Tester A and Tester B as members.
- **Scenario:**
  1. Open the team's Members view.
  2. Read each member's name, email, role, and join date.
- **What good looks like:**
  - Every active member is listed with accurate name, email, role, and join date.
  - Pending invites are visually distinct from joined members.
  - Removed members do not appear.
  - The list is readable and sorted sensibly (e.g. admins first or by join date).
- **Watch for:** a member missing or duplicated; roles shown wrong; pending and active states looking identical.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `TEAM-08` - Two people co-build on one shared project
- **Customer value:** The real test of teamwork - Tester A and Tester B both working inside the same project and the result staying coherent.
- **Priority:** Critical
- **Pre:** A shared (team-visible) project both testers can open as editors; the project is startable.
- **Scenario:**
  1. Tester A opens the project and asks the agent to build a feature (e.g. a contact page).
  2. While that runs (or right after), Tester B opens the *same* project from their account.
  3. Tester B opens the file tree and the editor - do they see Tester A's new files?
  4. Tester B then asks the agent for a different change (e.g. a footer); Tester A refreshes and checks.
  5. Both testers open the chat session list for the project.
- **What good looks like:**
  - Tester B sees Tester A's generated files (after a refresh at most) - the project is genuinely shared, not a private copy.
  - The agent does not let both runs corrupt the project - a second run is queued or clearly blocked while one is active, not run destructively in parallel.
  - Both testers can see the project's chat history / sessions, so they understand what the other asked for.
  - The end state is one coherent project containing both contributions.
- **Watch for:** each tester seeing a different file tree; one tester's changes silently overwriting the other's; concurrent agent runs colliding and leaving broken files; chat sessions invisible to the other person.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `TEAM-09` - Project visibility within the team
- **Customer value:** A customer wants some projects shared with the whole team and others kept private to themselves.
- **Priority:** High
- **Pre:** A team with Tester A (admin) and Tester B (editor); a project owned by Tester A.
- **Scenario:**
  1. As Tester A, set the project's visibility to **team** and confirm Tester B can see and open it.
  2. As Tester A, set it to **private** and have Tester B refresh their dashboard.
  3. Set it back to **team**.
- **What good looks like:**
  - With team visibility, Tester B sees the project in the shared list and can open it.
  - With private visibility, the project disappears from Tester B's dashboard without breaking anything for them.
  - Toggling back restores access cleanly; the change is obvious to Tester A (clear current state shown).
- **Watch for:** the visibility change not taking effect until a re-login; Tester B keeping a stale link that still works after the project went private; an unclear or missing indicator of the current visibility.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `TEAM-10` - Activity / audit visibility for an admin
- **Customer value:** An admin running a team wants to see what happened - who invited whom, who changed what - so the team stays accountable.
- **Priority:** High
- **Pre:** A team where several actions have occurred (invites sent, a member joined, visibility changed, projects created).
- **Scenario:**
  1. As Tester A (admin), open the team's Audit Log / activity view.
  2. Read the recent entries; find the invite and the join from earlier cases.
  3. If filters exist, narrow by actor or action type, then clear them.
- **What good looks like:**
  - Recent activity is listed newest-first with a clear actor, action, affected resource, and timestamp.
  - The entries actually match what was done in earlier cases - it's a trustworthy record, not a vague feed.
  - Filtering (if present) narrows results correctly and clearing restores the full list.
- **Watch for:** missing events; entries with no actor or no timestamp; cryptic action codes a non-engineer can't read; the log so noisy it's useless.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `TEAM-11` - Remove a member from the team
- **Customer value:** When someone leaves a project or company, an admin needs to cleanly cut their access.
- **Priority:** High
- **Pre:** A team with Tester B as a member.
- **Scenario:**
  1. As Tester A (admin), remove Tester B from the team and confirm.
  2. As Tester B, refresh the team switcher and try to open a team project.
- **What good looks like:**
  - Removal is confirmed clearly and Tester B disappears from the member list.
  - Tester B no longer sees the team in their switcher and can no longer open its projects.
  - The removal shows up in the activity log.
- **Watch for:** Tester B keeping access via a cached page or stale link; the team still appearing in their switcher; no confirmation step before a destructive removal.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `TEAM-12` - Leave a team voluntarily
- **Customer value:** A member who no longer needs a team should be able to step away on their own.
- **Priority:** Medium
- **Pre:** Tester B re-added to the team (via `TEAM-05` link or a fresh invite) and is **not** the sole admin.
- **Scenario:**
  1. As Tester B, open team settings and choose Leave team; confirm.
  2. Check Tester B's switcher and dashboard.
- **What good looks like:**
  - Tester B leaves cleanly; the team drops out of their switcher and dashboard.
  - Tester A still sees the team intact, just without Tester B.
  - Attempting to leave a personal team, or leave as the sole admin, is gently prevented with a clear explanation rather than a hard error.
- **Watch for:** the team lingering in the leaver's switcher; a sole-admin being allowed to orphan the team; a confusing or missing confirmation.
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
**Overall collaboration experience (1-5) & notes:** 
