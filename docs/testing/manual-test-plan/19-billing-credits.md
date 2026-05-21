# Suite 19 - Billing & credits

> See [README.md](README.md) for format, priorities, severity, environments, and accounts.

**Why this suite matters:** Billing is where trust is won or lost. A customer who can't tell what tier they're on, gets charged unexpectedly, or hits a confusing wall when their credits run out will not come back - and may dispute the charge. This suite checks that paying Tesslate Studio feels honest and predictable: the billing page tells the truth, upgrading is smooth and immediately reflected, cancelling does what it says, credits are consumed in a fair order, and the **moment a customer runs out** is handled with a clear path forward rather than a dead end. Judge these on the *feeling* of the money flow, not just whether Stripe returned success.

**Suite prerequisites:** Tester A logged in. Stripe **test mode** is active in this environment - use card `4242 4242 4242 4242`, any future expiry, any CVC. Have a few accounts at different states ready if possible: one free, one paid, one near-zero credits. Tier prices and limits below are **guidance only** - pricing drifts; **confirm against the current pricing shown in the environment** before asserting exact numbers.

> Indicative tier model (confirm against current pricing): **Free** ~$0, ~3 projects, ~1,000 monthly credits, no BYOK - **Basic** ~$8/mo, ~5 projects - **Pro** ~$20/mo, ~10 projects, BYOK - **Ultra** ~$100/mo, unlimited projects, BYOK. Treat exact numbers as needing verification.

---

### `BILLING-01` - Billing page shows the correct tier and credits
- **Customer value:** A customer can open one page and immediately understand what they're paying for and how much they have left.
- **Priority:** High
- **Pre:** Tester A logged in.
- **Scenario:**
  1. Open Settings -> Billing.
  2. Read the current tier, plan limits (projects, deploys), billing period dates, and credit balances.
  3. Cross-check the tier against what the account actually is.
- **What good looks like:**
  - The current tier is named clearly and matches reality.
  - Plan limits and the billing period (start/renewal dates) are shown and plausible.
  - Credit balance is visible and broken out (bundled vs. purchased) with a reset date for bundled credits.
  - The page loads quickly and reads like a clear statement, not a wall of jargon.
- **Watch for:** the tier shown wrong; "undefined"/blank limits; credits shown as one opaque number with no reset date; the page taking a long time or erroring.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BILLING-02` - Upgrade a subscription via Stripe checkout
- **Customer value:** A customer who needs more spins up a higher tier and gets the benefits straight away.
- **Priority:** Critical
- **Pre:** Tester A on a free or low tier; Stripe test mode.
- **Scenario:**
  1. On the billing page, choose to upgrade and pick a higher tier.
  2. Complete the Stripe test checkout with card `4242 4242 4242 4242`.
  3. Return to the app and re-open the billing page.
- **What good looks like:**
  - The checkout opens promptly and looks like a legitimate, branded Stripe page.
  - After paying, you're returned to the app with a clear success indication.
  - The tier updates to the new plan; limits and monthly credits adjust to match the new tier.
  - The change is visible without needing a manual hard-refresh or re-login.
- **Watch for:** the tier not updating after a successful payment; credits not topped up; landing on a blank or error page after checkout; a long delay before the upgrade reflects.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BILLING-03` - Cancel a subscription (cancels at period end)
- **Customer value:** A customer scaling down wants to cancel without losing access they already paid for.
- **Priority:** High
- **Pre:** Tester A on a paid subscription (from `BILLING-02`).
- **Scenario:**
  1. On the billing page, cancel the subscription.
  2. Read the resulting state and period information.
- **What good looks like:**
  - Cancellation is confirmed and the UI clearly states the plan **cancels at period end** - not immediately.
  - The paid features remain usable until the period end date, which is shown.
  - There is no surprise about whether access stops now or later.
- **Watch for:** access cut off immediately despite "period end" wording; no end date shown; an ambiguous state where the customer can't tell if they're still subscribed.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BILLING-04` - Reactivate a cancelled subscription
- **Customer value:** A customer who changes their mind before the period ends can undo the cancellation without re-subscribing from scratch.
- **Priority:** Medium
- **Pre:** `BILLING-03` done; the period has not yet ended.
- **Scenario:**
  1. On the billing page, reactivate / resume the subscription.
  2. Re-read the billing state.
- **What good looks like:**
  - The cancellation is reversed; the plan reads as active again with a normal renewal date.
  - No second charge is incurred just to reactivate within the same period.
  - The state is unambiguous - clearly "active", not "cancels at period end".
- **Watch for:** reactivation forcing a fresh checkout; a duplicate charge; the UI still showing "cancels at period end" after reactivating.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BILLING-05` - Stripe customer portal
- **Customer value:** A customer wants to manage their payment method and download invoices like any normal subscription.
- **Priority:** Medium
- **Pre:** Tester A on a paid account.
- **Scenario:**
  1. From the billing page, open "Manage subscription" / the customer portal.
  2. Look at the payment method and invoice history; return to the app.
- **What good looks like:**
  - The Stripe customer portal opens cleanly, scoped to this customer.
  - The payment method on file and past invoices are visible and downloadable.
  - Returning to the app lands you back on the billing page in a sensible state.
- **Watch for:** the portal showing the wrong customer or no data; a broken return URL; the portal link failing to open.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BILLING-06` - Credit balance: bundled vs. purchased
- **Customer value:** A customer wants to understand their two kinds of credits - the monthly allowance vs. credits they bought - so they know what resets and what doesn't.
- **Priority:** High
- **Pre:** Tester A with both bundled (monthly) and ideally some purchased credits.
- **Scenario:**
  1. Open the credits section of the billing page.
  2. Read the bundled balance, purchased balance, total, and any reset date.
- **What good looks like:**
  - Bundled and purchased credits are shown separately, with a clear total.
  - The bundled credits show when they reset; purchased credits are clearly marked as non-expiring.
  - The distinction is explained well enough that a non-technical customer gets it.
- **Watch for:** a single opaque number; no reset date; the labels so unclear the customer can't tell which credits expire.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BILLING-07` - Buy a credit package
- **Customer value:** A customer who burns through their monthly allowance can top up immediately without changing plans.
- **Priority:** High
- **Pre:** Tester A logged in; Stripe test mode; note the current credit balance first.
- **Scenario:**
  1. Choose a credit package (e.g. a small or medium pack) and start checkout.
  2. Complete the Stripe test checkout.
  3. Return and re-check the credit balance.
- **What good looks like:**
  - The package and its credit amount are clearly stated before paying.
  - After checkout, the balance increases by exactly the package amount.
  - The bought credits land in the **purchased** bucket (not bundled) and do not carry a reset date.
- **Watch for:** balance not updating; the wrong amount added; bought credits landing in the bundled bucket so they'd wrongly expire; a long delay before they appear.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BILLING-08` - Credits consumed bundled-first
- **Customer value:** A customer expects their "use it or lose it" monthly credits to be spent before the credits they paid real money for.
- **Priority:** Medium
- **Pre:** Tester A with **both** bundled and purchased credits available.
- **Scenario:**
  1. Note both balances.
  2. Run one or more agent tasks that consume credits.
  3. Re-check both balances.
- **What good looks like:**
  - The bundled balance goes down first; the purchased balance is untouched until bundled is exhausted.
  - The deduction is reflected promptly and the math is correct.
- **Watch for:** purchased credits drained while bundled ones still sit unused; balances not updating; an inconsistent total.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BILLING-09` - Low-credit warning
- **Customer value:** A customer gets a heads-up *before* they're stranded mid-task, so they can top up in advance.
- **Priority:** Medium
- **Pre:** Tester A on an account with credits near the low threshold.
- **Scenario:**
  1. Use the app normally - open the dashboard, start an agent task.
  2. Watch for a low-credit warning.
- **What good looks like:**
  - A clear, non-blocking warning (banner or notice) appears while credits are low.
  - The warning offers an obvious next step (buy credits / upgrade).
  - It's noticeable but not so aggressive it blocks ordinary work.
- **Watch for:** no warning at all (customer blindsided later); a warning that blocks the UI; a warning with no actionable link.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BILLING-10` - The out-of-credits moment
- **Customer value:** When a customer hits zero, the experience should guide them out of it - not feel like the product broke.
- **Priority:** High
- **Pre:** Tester A on an account at (or driven to) zero credits.
- **Scenario:**
  1. Attempt a credit-consuming action - start an agent task.
  2. Observe exactly what happens.
- **What good looks like:**
  - The action is cleanly blocked with a clear "out of credits" message - no silent failure, no raw error.
  - A modal or panel guides the customer to upgrade or buy credits, with working buttons.
  - Once credits are added, the customer can immediately continue - no stuck state.
  - The whole moment feels like a gentle upsell, not a crash.
- **Watch for:** the agent run failing silently or with a stack trace; the modal having dead buttons; the app locking up; the customer unable to recover even after buying credits.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BILLING-11` - Transaction & usage history
- **Customer value:** A customer wants a clear record of what they were charged for and where their credits went.
- **Priority:** Medium
- **Pre:** Tester A with a mix of activity - a subscription, a credit purchase, and some AI usage.
- **Scenario:**
  1. Open the transaction history view; read the entries.
  2. Open the usage breakdown (by model / agent / date) if present.
- **What good looks like:**
  - Transactions list subscription charges, credit purchases, and marketplace spend with type, amount, and date.
  - Usage is broken down understandably so a customer can see what consumed their credits.
  - Entries reconcile with what the customer actually did - nothing missing or doubled.
- **Watch for:** missing transactions; amounts that don't add up; an unreadable raw dump; pagination that loses entries.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BILLING-12` - Team billing for an admin [Admin]
- **Customer value:** An admin running a paid team manages one shared plan and credit pool for everyone.
- **Priority:** Medium
- **Pre:** Tester A is admin of an org team (see suite 18).
- **Scenario:**
  1. Open the team's billing view.
  2. Read the team subscription, the shared credit pool, and team usage.
  3. If available, walk up to (but don't necessarily complete) a team upgrade or team credit purchase.
- **What good looks like:**
  - The team's plan, shared credit pool, and usage are shown clearly and distinctly from personal billing.
  - An admin can see how to upgrade the team or buy team credits.
  - It's obvious this is *team* money, not the admin's personal account.
- **Watch for:** team and personal billing bleeding together; the credit pool not reflecting team-wide usage; team billing controls missing or broken.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BILLING-13` - Abandoned checkout leaves no charge
- **Customer value:** A customer who starts checkout and backs out must not be charged or half-upgraded.
- **Priority:** Medium
- **Pre:** Tester A; Stripe test mode; note the current tier and credit balance.
- **Scenario:**
  1. Start a checkout (either a subscription upgrade or a credit purchase).
  2. On the Stripe page, cancel / close it without completing payment.
  3. Return to the app and re-check the tier and credit balance.
- **What good looks like:**
  - You're returned to the app cleanly with a sensible state.
  - The tier and credit balance are exactly as before - no charge, no partial upgrade.
  - No stray "pending" subscription or phantom credit entry is left behind.
- **Watch for:** the tier changing despite no payment; a charge appearing; a stuck "processing" state; a confusing landing page after cancelling.
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
**Overall billing experience (1-5) & notes:** 
