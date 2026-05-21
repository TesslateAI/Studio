# Suite 13 - App Economy

> See [README.md](README.md) for format, priorities, severity, environments, and accounts.

**Why this suite matters:** Tesslate Apps are a two-sided economy. Installers spend real money running Apps; creators earn real money when their Apps get used; and admins are the safety valve that keeps bad versions out of circulation. If the wallets don't reconcile, if spend records lie, if a yanked App keeps charging people, or if the approval workbench lets junk through, customers lose trust and money - and that is unrecoverable. This suite tests the **money and lifecycle** side of Apps, not the build/install mechanics (suites 11 and 12). Judge it on whether the numbers are honest, the controls actually work, and the experience is something a creator or installer would feel safe putting a credit card behind.

**Suite prerequisites:** Tester A logged in, on a paid tier, with at least one Tesslate App already installed and used enough to incur spend (see suites 11-12). An **Admin** account for the `[Admin]` cases. For creator cases, an account with creator capability enabled. Stripe test mode available for the Stripe Connect case. For the two-admin yank case you need a **second** distinct admin account.

---

### `APP-ECON-01` - Installer wallet shows an honest balance
- **Customer value:** A customer running paid Apps can see, at a glance, how much money is behind their App usage and whether they can keep running things.
- **Priority:** High
- **Pre:** Tester A logged in; the App billing / wallet area open.
- **Scenario:**
  1. Open the App billing / wallet view.
  2. Note the displayed balance and wallet state.
  3. Cross-check the figure against what you'd expect from recent App usage.
- **What good looks like:**
  - The installer wallet shows a clear current balance and a state (active / suspended / etc.).
  - The number is plausible - it reflects real usage, not a placeholder zero or a stale figure.
  - The view explains what the wallet funds (App runtime spend) so a new customer isn't confused about how it differs from AI credits.
- **Watch for:** a wallet that always reads $0.00; balance that never changes after spend; no indication of what the wallet is for; a perpetual loading spinner.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-ECON-02` - Spend records and the wallet ledger reconcile
- **Customer value:** A customer can audit exactly what an App charged them for and trust that the wallet balance is the sum of real events.
- **Priority:** High
- **Pre:** An installed App that has been used enough to generate several spend records.
- **Scenario:**
  1. Open the spend records list and read a few entries.
  2. Open the wallet ledger (the append-only debit/credit history).
  3. Pick a recent spend record and find the matching ledger debit.
  4. Add up the ledger entries and compare to the displayed wallet balance.
- **What good looks like:**
  - Each spend record shows what was billed: dimension (AI compute, storage, MCP tool call, etc.), payer, amount, and whether it has settled.
  - Settled spend appears as a corresponding debit in the ledger; unsettled spend is clearly marked as pending.
  - The ledger entries sum to the current wallet balance - the books reconcile.
  - Timestamps and amounts are consistent between the two views.
- **Watch for:** spend records with no matching ledger entry (or vice versa); a balance that doesn't equal the ledger sum; "settled" records that never produced a debit; amounts that disagree between views; cryptic dimension labels a customer can't interpret.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-ECON-03` - Creator wallet shows earnings [Cloud only]
- **Customer value:** A creator who publishes Apps can see the money they've earned from other people installing and running them.
- **Priority:** Medium
- **Pre:** A creator account whose published App has been used by an installer enough to generate settled spend.
- **Scenario:**
  1. Log in as the creator and open the creator wallet / earnings view.
  2. Compare the earnings figure to the spend generated on the creator's App.
- **What good looks like:**
  - The creator wallet shows an earnings balance distinct from the installer wallet.
  - Earnings reflect the creator's share of settled App spend (the creator gets the larger split after the platform fee).
  - A non-creator account does not see a creator wallet, or sees a clear empty/null state - no confusing phantom balance.
- **Watch for:** creator earnings stuck at zero despite real usage; the creator share looking wrong (e.g. platform took most of it); installer and creator wallets being conflated.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-ECON-04` - Creator connects Stripe to get paid out [Cloud only]
- **Customer value:** A creator can connect a payout account so the money they earn can actually reach their bank.
- **Priority:** Medium
- **Pre:** A creator account; Stripe test mode; no payout account connected yet.
- **Scenario:**
  1. Open the creator payout / Stripe Connect setup.
  2. Start the connect flow and complete Stripe's test-mode onboarding.
  3. Return to Tesslate Studio.
- **What good looks like:**
  - The connect flow launches cleanly and hands off to Stripe with clear branding/context.
  - After completing Stripe onboarding you return to a state that clearly says payouts are connected/enabled.
  - Before connecting, the creator wallet view explains that a payout account is needed to withdraw - no silent dead end.
- **Watch for:** the Stripe handoff failing or looping; returning to an ambiguous state where it's unclear if Connect succeeded; no indication that earnings can't be withdrawn until Connect is done.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-ECON-05` - Request a yank on an App version
- **Customer value:** Anyone who finds a serious problem in a published App can flag it for recall so others aren't harmed.
- **Priority:** Medium
- **Pre:** A published App version (yours or another's, per environment policy).
- **Scenario:**
  1. Open the App version and find the yank-request action.
  2. Submit a yank request - choose a severity (low / medium / critical) and write a reason.
- **What good looks like:**
  - The form makes the severity choice meaningful - it's clear that critical means something stronger than low.
  - On submit, a yank request is created and confirmed; it's clear it has entered an admin review queue.
  - The reason text is captured and will be visible to reviewers.
- **Watch for:** the request vanishing with no confirmation; severity having no apparent effect; no feedback that a human will review it.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-ECON-06` - Admin approves a non-critical yank [Admin]
- **Customer value:** Admins can quickly pull a low/medium-risk App version out of circulation with a single decision.
- **Priority:** Medium
- **Pre:** A low- or medium-severity yank request waiting in the admin queue (from `APP-ECON-05`).
- **Scenario:**
  1. Log in as Admin and open the yank queue in the admin workbench.
  2. Open the pending yank request and review its severity and reason.
  3. Approve it.
- **What good looks like:**
  - The yank queue clearly lists pending requests with severity, target App version, and reason.
  - A single admin approval is enough for a low/medium-severity yank - no second approver demanded.
  - After approval the App version is visibly marked as yanked and the request leaves the pending queue.
- **Watch for:** a non-critical yank wrongly demanding a second admin; the version still showing as live after approval; the queue not updating.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-ECON-07` - Critical yank requires two distinct admins [Admin]
- **Customer value:** The most severe recalls - security holes, abuse - can't be triggered (or rubber-stamped) by a single admin acting alone.
- **Priority:** High
- **Pre:** A critical-severity yank request in the queue; **two** distinct admin accounts available.
- **Scenario:**
  1. As Admin 1, open the critical yank request and approve it.
  2. Observe the result, then as Admin 1 attempt to approve it a second time.
  3. As Admin 2 (a different admin) open the same request and approve it.
- **What good looks like:**
  - Admin 1's first approval does **not** complete the yank - the UI clearly says a second, different admin is still needed.
  - The same admin approving twice is rejected with a clear message - one person cannot satisfy both approvals.
  - Admin 2's approval completes the yank; the App version is then marked yanked.
  - Throughout, the request shows who has approved so far and what's still required.
- **Watch for:** a single admin completing a critical yank; the same admin's second click being accepted; an unclear state where it's impossible to tell what approval is outstanding.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-ECON-08` - A yanked App blocks new installs and new sessions
- **Customer value:** Once a dangerous App version is recalled, no new customer can install it or spin up a fresh session against it.
- **Priority:** High
- **Pre:** An App version that has been yanked (from `APP-ECON-06` or `APP-ECON-07`).
- **Scenario:**
  1. As Tester A, open the yanked App's marketplace page and attempt to install it.
  2. If you have an existing install of that version, attempt to start a new runtime session for it.
- **What good looks like:**
  - Installing the yanked version is blocked with a clear, honest message about why (it was recalled).
  - Minting a new runtime session for a yanked version is blocked the same way.
  - The block is informative, not a generic error - a customer understands the App was pulled, not that something broke.
- **Watch for:** a yanked App still installable; new sessions still spinning up against a yanked version; a raw error instead of an explanation; the customer being charged for a blocked attempt.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-ECON-09` - Creator files a yank appeal
- **Customer value:** A creator who believes their App was recalled unfairly has a real path to contest the decision.
- **Priority:** Low
- **Pre:** A yank affecting an App the creator account published.
- **Scenario:**
  1. Log in as the creator and open the yanked App / yank record.
  2. Find the appeal action and file an appeal with a written reason.
- **What good looks like:**
  - The creator can clearly see their App was yanked and why.
  - An appeal can be filed with a reason; it's confirmed and flagged for admin review.
  - The appeal is tied to the specific yank - there's no ambiguity about what is being contested.
- **Watch for:** no appeal path at all for the creator; the appeal submitting silently with no confirmation; being able to file multiple duplicate appeals on the same yank.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-ECON-10` - Fork a forkable App; a non-forkable one is blocked
- **Customer value:** A customer can take a forkable App as a starting point for their own version - and creators who lock their App stay protected.
- **Priority:** Medium
- **Pre:** One published App marked **forkable**; one published App marked **non-forkable**.
- **Scenario:**
  1. Open the forkable App's marketplace page and use the Fork action.
  2. Confirm a new draft App and an editable source project were created for you.
  3. Open the non-forkable App's page and look for / attempt the Fork action.
- **What good looks like:**
  - Forking the forkable App produces a new **draft** App owned by you, visibly linked back to the original it was forked from.
  - You also get an editable source project so you can immediately start changing the fork.
  - The non-forkable App offers no Fork action, or clearly explains the creator disabled forking - no broken-looking failure.
- **Watch for:** a fork that produces nothing usable; the new App not linked to its source; a non-forkable App being forkable anyway; the fork copying over the original's approval state instead of starting as a draft.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-ECON-11` - Create and install an App bundle
- **Customer value:** A customer can install a curated set of Apps in one action instead of hunting down and installing each one.
- **Priority:** Medium
- **Pre:** At least two approved App versions available to include.
- **Scenario:**
  1. Create a bundle and add two or more Apps to it (set order if offered).
  2. Publish / make the bundle available.
  3. As an installer, install the bundle in one action.
  4. Check My Apps for the bundle's members.
- **What good looks like:**
  - The bundle can be assembled and given a name; members are clearly listed.
  - Installing the bundle installs each member App; the result reports per-App success or failure, not just an opaque "done".
  - All successfully installed members show up in My Apps afterward.
- **Watch for:** installing the bundle only installing one App; a partial failure hidden behind a blanket success message; bundle members charged or consented to without the customer seeing what they agreed to.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-ECON-12` - Admin submission workbench: review, advance, decide [Admin]
- **Customer value:** Admins can confidently review what creators submit and either move it forward or reject it with a reason the creator can act on - keeping the marketplace trustworthy.
- **Priority:** High
- **Pre:** Admin account; at least one App submission in the review pipeline (a creator published an App - see suite 11).
- **Scenario:**
  1. Log in as Admin and open the submission workbench / review queue.
  2. Open a pending submission and review its manifest, automated check results, and metadata.
  3. Advance the submission to the next stage.
  4. On a separate submission, reject it (or approve the one that reaches the final stage) and enter a clear decision reason.
- **What good looks like:**
  - The workbench lists submissions with their current stage and surfaces the automated check results (manifest valid, features supported, billing disclosure present, etc.) so the admin isn't reviewing blind.
  - Advancing a submission moves it cleanly to the next stage and the queue reflects it.
  - A rejection requires/records a reason; an approval at the final stage makes the App installable in the marketplace.
  - The decision reason is something the creator will be able to see - it's actionable, not internal-only jargon.
- **Watch for:** check results missing or unreadable so the admin can't make an informed call; stage transitions that don't stick; rejections with no captured reason; an approved App not actually becoming installable; the queue not refreshing after a decision.
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
**Overall App economy experience (1-5) & notes:** 
