# Suite 12 - Install & Run Apps

> See [README.md](README.md) for format, priorities, severity, environments, and accounts.

**Why this suite matters:** This is the consumer end of the Tesslate App economy - a customer discovers an App someone else built, installs it, and **actually uses it** to get something done. It has to feel as trustworthy as installing an app on a phone: the customer sees what it will cost and what it can access, agrees on purpose, and ends up with a working tool. The install is the moment of consent; the running App is the moment of value. Judge this on whether the customer reaches a **genuinely working App** with no nasty surprises about billing, permissions, or a broken runtime - and can cleanly walk away by uninstalling.

**Suite prerequisites:** Tester A logged in, with an installer wallet / credits available for App spend (suite 13 covers the wallet in depth). At least one **approved** Tesslate App in the marketplace - coordinate with suite 11 or use a seeded App. For the install-time-credentials case, an App whose manifest declares required credentials and a valid value for that credential.

---

### `APP-USE-01` - Discover approved Apps in the Apps marketplace
- **Customer value:** A customer can find ready-to-install Apps and judge them before installing.
- **Priority:** High
- **Pre:** Tester A logged in; at least one approved public App exists.
- **Scenario:**
  1. Open the Apps section of the marketplace.
  2. Browse the listed Apps; open one App's detail page.
  3. Read its description, what it does, creator, and reputation.
- **What good looks like:**
  - Approved public Apps are listed with name, creator handle, and reputation (installs/stars).
  - The detail page explains what the App does and what installing it will involve.
  - Only approved Apps are installable - drafts/under-review Apps are not offered to customers.
  - Pricing/billing expectations are visible before the customer commits.
- **Watch for:** unapproved Apps appearing as installable; thin detail pages; no creator attribution; reputation numbers that look fake or broken.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-USE-02` - Install an approved Tesslate App
- **Customer value:** The core promise of the App economy - a customer installs someone else's App and gets their own working copy.
- **Priority:** Critical
- **Pre:** An approved App; Tester A logged in.
- **Scenario:**
  1. From the App's detail page, click Install.
  2. Review the consent step - wallet/billing consent, any MCP/connector consents, and the update-policy choice.
  3. Pick an update policy (e.g. manual vs auto) and confirm.
  4. Wait for the install to complete; then open "My Apps".
  5. Separately, try to install the same App a second time, and try to install an unapproved App.
- **What good looks like:**
  - The install flow clearly shows **what it will cost** (wallet/billing consent) and **what it can access** (MCP consents) before the customer agrees.
  - The update-policy choice is explained so the customer knows what they're picking.
  - Install completes and the App's containers/services come up healthy.
  - The install appears in "My Apps" as a usable install.
  - Installing the same App twice is blocked with a clear message; an unapproved App can't be installed.
- **Watch for:** an install that bills the customer with no consent shown; consents that are vague about scope; an install that "succeeds" but the App never starts; a duplicate install creating a broken second copy.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-USE-03` - Install an App that needs install-time credentials
- **Customer value:** A customer can install an App that integrates a third-party service by supplying their own key during install.
- **Priority:** Medium
- **Pre:** An approved App whose manifest declares required credentials; a valid credential value.
- **Scenario:**
  1. Start installing the App.
  2. Observe the credential input fields the install asks for.
  3. Try to proceed with a required field empty, then fill it and continue.
  4. After install, open and use the App to confirm the credential took effect.
- **What good looks like:**
  - The install asks for exactly the credentials the App declared, with clear labels.
  - The install button is gated until required credential fields are filled.
  - The credential value is treated as a secret - entered as a password field, never echoed back.
  - The running App actually uses the credential - the integration works.
- **Watch for:** install proceeding with required credentials missing; the credential shown in plaintext anywhere; the App running but the integration failing because the credential didn't reach it.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-USE-04` - Review the consent terms before agreeing
- **Customer value:** A customer can make an informed decision - they see precisely what spending and access they're authorizing.
- **Priority:** High
- **Pre:** An approved App with billing and at least one connector/MCP requirement.
- **Scenario:**
  1. Begin installing the App and stop at the consent step.
  2. Read the wallet/billing consent - who pays for what (compute, AI, storage).
  3. Read the MCP/connector consents - what external access is granted.
  4. Cancel the install at the consent step.
- **What good looks like:**
  - Billing consent spells out the spend dimensions and who the payer is in terms a customer understands.
  - Connector consents name the specific access being granted, not a blanket "allow everything".
  - Cancelling at consent installs nothing and charges nothing.
- **Watch for:** consent text that's blank or boilerplate; billing that doesn't say who pays; cancelling still leaving a partial install or a charge.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-USE-05` - The "My Apps" list
- **Customer value:** A customer has one place to see every App they've installed and its current state.
- **Priority:** Medium
- **Pre:** At least one App installed (`APP-USE-02`).
- **Scenario:**
  1. Open "My Apps".
  2. Review each install's summary.
- **What good looks like:**
  - Every installed App is listed with its name, version, state (installed/running/error), and update policy.
  - States are accurate - a running App reads as running, a failed one reads as failed.
  - The list updates as installs change state without a manual reload.
- **Watch for:** an installed App missing from the list; a stale state (shows "installing" forever); the list and reality disagreeing.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-USE-06` - An install's detail view
- **Customer value:** A customer can drill into one installed App to see how it's set up and what it's doing.
- **Priority:** Medium
- **Pre:** `APP-USE-05`.
- **Scenario:**
  1. From "My Apps", open an install's detail view.
  2. Review its containers/services, connections, update policy, and any schedules.
- **What good looks like:**
  - The detail view shows the App's running pieces with their status.
  - Connections, schedules, and the update policy are all visible and accurate.
  - There's a clear way from here to open/use the App and to manage it.
- **Watch for:** a detail view that doesn't match the App's real state; missing sections; no path to actually launch the App.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-USE-07` - Open a running App
- **Customer value:** A customer launches the App they installed and reaches its actual interface.
- **Priority:** Critical
- **Pre:** An installed App with a usable surface (`APP-USE-02`).
- **Scenario:**
  1. From "My Apps" or the install detail, open the App.
  2. Wait for it to load.
- **What good looks like:**
  - The App opens to its real interface (its surface/view), not a blank frame or error.
  - It loads in a reasonable time with clear progress while it starts.
  - The App looks like a finished product, not a debug screen.
- **Watch for:** a blank or broken iframe; the App hanging on "starting"; an error page; the App opening but obviously unconfigured.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-USE-08` - Use the App's actions and views
- **Customer value:** The whole point - the customer does real work with the App and it produces real results.
- **Priority:** Critical
- **Pre:** `APP-USE-07` - the App is open and loaded.
- **Scenario:**
  1. Use the App as intended - trigger its primary actions, navigate its views/surfaces.
  2. Enter data or run whatever the App's core workflow is.
  3. Confirm the App produces a genuine, correct result.
- **What good looks like:**
  - The App's actions respond and do what they claim.
  - Views/surfaces render real data and update as the customer interacts.
  - The App delivers the value its marketplace listing promised - end to end, not just the first screen.
- **Watch for:** actions that spin and never finish; views that show no data or stale data; the App working only superficially; errors with no explanation.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-USE-09` - App spend is metered and visible
- **Customer value:** A customer who used a billable App can see what it cost them - no mystery charges.
- **Priority:** Medium
- **Pre:** A billable App that has been used enough to incur spend (`APP-USE-08`).
- **Scenario:**
  1. After using the App, open the App billing / wallet / spend view.
  2. Review the spend recorded for this App.
- **What good looks like:**
  - Spend from using the App shows up with its dimension (compute, AI, etc.), the payer, and the amount.
  - The amounts are plausible for what the customer actually did.
  - The customer can reconcile the spend against their wallet balance.
- **Watch for:** usage that incurs no recorded spend (or vice versa); spend attributed to the wrong App or payer; amounts that look arbitrary.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-USE-10` - A yanked App stops new use
- **Customer value:** A customer is protected - if an App is recalled for a serious problem, they can't unknowingly install or start a new session of it.
- **Priority:** High
- **Pre:** An App version that has been yanked (coordinate with suite 13), or ask the team for one.
- **Scenario:**
  1. Try to install the yanked App version.
  2. If you already have it installed, try to start a fresh runtime session.
- **What good looks like:**
  - Installing a yanked App is blocked with a clear, non-alarming explanation.
  - Starting a new session of a yanked App is blocked the same way.
  - The customer understands it's the App that was withdrawn - not their account at fault.
- **Watch for:** a yanked App still installable; a raw error instead of a clear message; no explanation of why it's unavailable.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `APP-USE-11` - Uninstall an App
- **Customer value:** A customer can cleanly remove an App they no longer want, with nothing left running or billing in the background.
- **Priority:** High
- **Pre:** An installed App (`APP-USE-02`).
- **Scenario:**
  1. From the install's detail or "My Apps", choose Uninstall.
  2. Confirm.
  3. Re-check "My Apps" and the App's billing view.
- **What good looks like:**
  - Uninstall confirms the action and explains what will be removed.
  - The App's containers/services are torn down - nothing keeps running.
  - The install leaves the active "My Apps" list.
  - No further spend accrues after uninstall.
- **Watch for:** containers left running after uninstall; the App still in "My Apps"; spend continuing to accumulate; uninstall with no confirmation deleting work unexpectedly.
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
**Overall install-and-run-Apps experience (1-5) & notes:** 
