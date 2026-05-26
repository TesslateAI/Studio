# Suite 10 - Creator Publishing

> See [README.md](README.md) for format, priorities, severity, environments, and accounts.

**Why this suite matters:** The marketplace only has things to install because creators publish them. This suite is the **other side of the counter** - a creator turning their own agent or skill into a listed marketplace item, watching it move through review, and seeing how it performs once it's live. If publishing is confusing, the review status is opaque, or earnings never show up, creators stop contributing and the marketplace dries up. Judge this on whether a creator feels **in control and informed** the whole way: clear publish form, honest review status, a trustworthy profile and dashboard.

**Suite prerequisites:** Tester A logged in on a creator-capable account (request creator access from the team if it is gated). A square icon image ready for upload. For the review-progression cases, coordination with an Admin account (suite 11/13 cover the admin side in depth).

---

### `CREATOR-01` - Open Creator Studio
- **Customer value:** A creator has one place to manage everything they publish.
- **Priority:** High
- **Pre:** Tester A on a creator-capable account.
- **Scenario:**
  1. Navigate to Creator Studio from the account menu or marketplace.
  2. Scan the landing view.
- **What good looks like:**
  - Creator Studio opens and clearly presents what a creator can do - publish, manage items, see stats.
  - If the creator has nothing published yet, a friendly empty state explains the first step.
  - Navigation to publish flows and to existing items is obvious.
- **Watch for:** a dead-end empty state; Creator Studio hidden so well a creator can't find it; broken links into publish flows.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CREATOR-02` - Publish a new agent
- **Customer value:** A creator lists an agent they built so other customers can install it.
- **Priority:** Critical
- **Pre:** Creator Studio open; an icon image ready.
- **Scenario:**
  1. Start the "publish an agent" flow.
  2. Fill in name, description, category, and upload an icon.
  3. Set pricing - try free first.
  4. Submit.
- **What good looks like:**
  - The form is clear about what each field is for and what is required.
  - The icon uploads with a visible preview.
  - On submit, the agent is created and shown with an **"under review"** (or equivalent) status.
  - The creator gets a confirmation that explains what happens next (review, then it goes live).
- **Watch for:** a vague submit with no confirmation; the icon failing to upload silently; the item created but with no status at all; required fields not flagged before submit.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CREATOR-03` - Publish a paid agent
- **Customer value:** A creator can charge for their work and trust the price they set is what buyers will pay.
- **Priority:** High
- **Pre:** `CREATOR-02` understood; publish flow open.
- **Scenario:**
  1. Publish another agent, this time setting a non-zero price.
  2. Submit, then open the item's detail/preview as it would appear to buyers.
- **What good looks like:**
  - Pricing input is clear (currency, amount) and validated against obvious mistakes.
  - The price the creator set is exactly what shows on the listing/preview.
  - The item enters review like the free one, with no extra friction for being paid.
- **Watch for:** the displayed price not matching what was entered; no payout/Stripe-Connect prompt when one is expected; a paid item that can't actually be checked out later.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CREATOR-04` - Publish a skill
- **Customer value:** A creator shares a reusable skill (a workflow/instruction set) for others to attach to their agents.
- **Priority:** High
- **Pre:** Creator Studio open.
- **Scenario:**
  1. Start the "publish a skill" flow.
  2. Provide the skill name, description, body/instructions, and category.
  3. Submit.
- **What good looks like:**
  - The skill-publish flow is clearly distinct from the agent flow and asks for skill-appropriate content.
  - The skill body is captured intact - long instruction text isn't truncated or mangled.
  - The skill is created and enters review with a visible status.
- **Watch for:** the skill body silently truncated; the skill flow being a confusing reuse of the agent form; no review status after submit.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CREATOR-05` - Under-review status is visible and honest
- **Customer value:** A creator knows exactly where their submission stands and isn't left guessing.
- **Priority:** High
- **Pre:** At least one item submitted from `CREATOR-02`/`CREATOR-04`.
- **Scenario:**
  1. Open Creator Studio and find the submitted item.
  2. Read its status and any reviewer notes.
  3. If an Admin moves or rejects it (coordinate, or revisit after suite 11/13), re-check the status.
- **What good looks like:**
  - The status clearly distinguishes "under review" from "live/approved" from "rejected".
  - A rejected item shows the **reason** in plain language the creator can act on.
  - The status updates without the creator needing to guess or contact support.
  - An item under review is **not** yet installable by customers.
- **Watch for:** a permanently-stuck "under review"; a rejection with no reason; an unreviewed item already appearing live in the marketplace.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CREATOR-06` - Creator dashboard shows item status, stats, and earnings
- **Customer value:** A creator can see how their published items are performing - installs, ratings, and money earned.
- **Priority:** Medium
- **Pre:** A creator account with at least one published or submitted item; ideally one with some install activity.
- **Scenario:**
  1. Open the creator dashboard in Creator Studio.
  2. Review each item's status and stats (installs, ratings).
  3. Check the earnings/payout area if the creator has paid items.
- **What good looks like:**
  - Every item is listed with an accurate status.
  - Stats are present and plausible for items that have activity.
  - Earnings, where applicable, are shown clearly with how/when payout happens.
  - A creator with no activity yet sees honest zeros, not a broken panel.
- **Watch for:** stale or obviously-wrong stats; earnings that don't reconcile with installs; an items list that's missing recently published items.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CREATOR-07` - Public creator/author profile page
- **Customer value:** A creator has a public page that builds their reputation and lets customers discover all their work.
- **Priority:** Medium
- **Pre:** A creator with at least one approved/live item.
- **Scenario:**
  1. Open the creator's public profile (from one of their marketplace items or a direct profile link).
  2. Review it, then open it again logged out.
- **What good looks like:**
  - The profile shows the creator's name/handle, their published items, and reputation (installs, ratings).
  - Only live/approved items appear publicly - items under review stay private.
  - The page loads for anonymous visitors and links back to each item.
- **Watch for:** under-review or rejected items leaking onto the public profile; the profile failing to load logged out; missing or broken links to the creator's items.
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
**Overall creator-publishing experience (1-5) & notes:** 
