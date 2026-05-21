# Suite 14 - External Deployments

> See [README.md](README.md) for format, priorities, severity, environments, and accounts.

**Why this suite matters:** Building an app inside Tesslate Studio is only half the promise - customers eventually want their app **live on the internet** under a real URL. External deployment to Vercel, Netlify, or Cloudflare is the bridge from "it works in my preview" to "I shipped it." A customer judges this feature by one thing: did they get a working public URL with minimal fuss, and when a build failed, did the product tell them clearly why and let them try again. This suite tests that bridge end to end.

> **Note:** External deployments are **not available in desktop mode** - the customer runs builds and pushes from the cloud/Docker platform. Most cases below are `[Cloud/Docker only]`; one case verifies the desktop experience is an honest, clear "not here."

**Suite prerequisites:** Tester A logged in. A real API token for at least one provider (Vercel / Netlify / Cloudflare) in test/personal scope. At least one buildable project (a working frontend project from suites 2-5). For the failure case, a project you can deliberately break the build of.

---

### `DEPLOY-01` - Connect a deployment provider [Cloud/Docker only]
- **Customer value:** A customer links their hosting account once so they can ship projects to it without re-entering credentials each time.
- **Priority:** High
- **Pre:** Tester A logged in; a valid provider API token ready (Vercel / Netlify / Cloudflare).
- **Scenario:**
  1. Open the deployment / connections settings.
  2. Add a provider credential - pick the provider and paste the token.
  3. Save and return to the credential list.
- **What good looks like:**
  - The provider is clearly offered and the form explains what token it needs and where to get it.
  - On save, the credential is stored and appears in the list with the provider name - the raw token is **not** echoed back in plaintext.
  - It's clear whether this credential is a default (usable by any project) or can be scoped to a project.
- **Watch for:** the token shown back in full after saving; no confirmation the credential was stored; a confusing form with no hint about which token type is needed.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `DEPLOY-02` - Deploy a project and get a live URL that loads [Cloud/Docker only]
- **Customer value:** The core promise of this feature - a customer ships their project and gets a public URL that actually serves their app.
- **Priority:** Critical
- **Pre:** `DEPLOY-01` done; a buildable project open.
- **Scenario:**
  1. Trigger a deployment of the project to the connected provider.
  2. Watch the status as it progresses.
  3. When it finishes, open the returned deployment URL in a new browser tab.
  4. Click around the deployed app.
- **What good looks like:**
  - Status moves visibly through pending -> building -> success - the customer is never left guessing.
  - A real, public deployment URL is returned and is easy to find/copy.
  - Opening the URL loads the **actual app**, not a 404, a provider placeholder, or a blank page.
  - The deployed app behaves like the preview did - navigation and basic interactions work.
- **Watch for:** a "success" status with a URL that 404s or shows the wrong content; the build hanging at "building" forever with no timeout; the URL pointing at a stale or empty deployment; the deploy claiming success with nothing actually shipped.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `DEPLOY-03` - Follow deployment status and build logs [Cloud/Docker only]
- **Customer value:** A customer can watch their deployment build in real time and read the logs to understand what's happening.
- **Priority:** Medium
- **Pre:** A deployment in progress or recently finished.
- **Scenario:**
  1. Open the deployment's detail / logs view.
  2. Read through the build and deploy log output.
  3. Confirm the displayed status matches what actually happened.
- **What good looks like:**
  - Build/deploy logs are visible and readable - the customer can follow the build steps.
  - The status shown matches reality (a finished deploy reads success/failed, not stuck on building).
  - Logs are complete enough to diagnose a problem, not truncated into uselessness.
- **Watch for:** an empty or perpetually-loading log view; status that contradicts the logs; logs cut off right where the interesting part would be.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `DEPLOY-04` - A failed build is explained clearly and can be retried [Cloud/Docker only]
- **Customer value:** When a deployment fails, the customer understands why and can fix it and try again - instead of being stuck.
- **Priority:** High
- **Pre:** A project deliberately broken so its build will fail (e.g. a syntax error or a missing dependency).
- **Scenario:**
  1. Trigger a deployment of the broken project.
  2. Wait for it to fail.
  3. Read the failure reason and logs.
  4. Fix the project, then retry the deployment.
- **What good looks like:**
  - The deployment ends in a clear **failed** state - not an ambiguous limbo, not a false success.
  - The failure reason and build logs point at the actual problem (e.g. the build error), enough for the customer to act.
  - No misleading live URL is presented for a failed build.
  - A retry path is obvious; after fixing the project, a retry succeeds.
- **Watch for:** a failed build reported as success; a failure with no reason or logs; no way to retry without starting over from scratch; a dead URL handed to the customer anyway.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `DEPLOY-05` - Deploy a multi-container project [Cloud/Docker only]
- **Customer value:** A customer with a frontend + backend (or multi-service) project can deploy the whole thing in one action.
- **Priority:** Medium
- **Pre:** A multi-container project with provider credentials configured.
- **Scenario:**
  1. Use the deploy-all action for the multi-container project.
  2. Watch the per-container outcomes.
- **What good looks like:**
  - Each deployable container is deployed; the result reports a clear total / deployed / failed breakdown.
  - Per-container outcomes are visible - the customer can see which service succeeded and which didn't.
  - A partial success is allowed and honestly reported, not collapsed into a blanket "done" or a blanket "failed".
- **Watch for:** only one container deploying; per-container results hidden; a partial failure shown as full success; the whole operation aborting because one container failed.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `DEPLOY-06` - Project-scoped credential overrides the default [Cloud/Docker only]
- **Customer value:** A customer can keep a separate hosting account for one specific project without it affecting their other projects.
- **Priority:** Medium
- **Pre:** A default credential for a provider, **and** a project-specific credential for the same provider on one project.
- **Scenario:**
  1. Deploy the project that has its own project-scoped credential.
  2. Confirm the deployment used the project-scoped account, not the default.
- **What good looks like:**
  - The project-scoped credential takes precedence - the deploy lands in that project's specific hosting account.
  - It's clear in the UI which credential a given deployment used.
  - Other projects without an override still use the default credential.
- **Watch for:** the default credential being used despite a project-scoped one existing; no way to tell which account a deploy went to; the override leaking to unrelated projects.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `DEPLOY-07` - A bad credential fails cleanly with a reconnect path [Cloud/Docker only]
- **Customer value:** When a hosting token is wrong or has expired, the customer gets a clear authentication error and knows to reconnect - rather than a confusing build failure.
- **Priority:** Medium
- **Pre:** A stored provider credential with a deliberately wrong or expired token.
- **Scenario:**
  1. Attempt to deploy a project using that credential.
  2. Read the error.
  3. Remove or re-enter the credential and confirm the path to fix it.
- **What good looks like:**
  - The failure is clearly identified as an **authentication / credential** problem - not a generic build error.
  - No partial deployment happens with a dead token.
  - The customer is pointed toward reconnecting or updating the credential; after removing it, deploys that need it prompt to reconnect.
- **Watch for:** an auth failure masquerading as a build error; a raw provider error dump; the customer left guessing whether it was their code or their token.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `DEPLOY-08` - Cloud deploys are honestly unavailable in desktop mode [Desktop only]
- **Customer value:** A desktop customer isn't led down a dead-end path - the product tells them upfront that external cloud deploys aren't part of the desktop experience.
- **Priority:** Low
- **Pre:** The desktop app running.
- **Scenario:**
  1. Look for the external deployment feature in the desktop app.
  2. If a control is present, attempt an external provider deployment.
- **What good looks like:**
  - The deployment feature is either absent or clearly marked as not available in desktop mode.
  - Any attempt produces a clear, friendly "not available in desktop mode" message - not a crash, not a silent no-op, not a confusing error.
  - The customer understands this is by design, not a bug.
- **Watch for:** a deploy button that appears to work but does nothing; a raw error; no explanation of why the feature is missing.
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
**Overall deployment experience (1-5) & notes:** 
