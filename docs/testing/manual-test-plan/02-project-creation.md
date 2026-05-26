# Suite 2 - Project creation & setup

> See [README.md](README.md) for format, priorities, severity, environments, and accounts.

**Why this suite matters:** Before a customer can build anything, they need a project - and every project starts here. This is the on-ramp to the whole product, so it has to be fast, forgiving, and clear. A customer might start from nothing, from a template, or by bringing in an existing Git repo, and in each case they expect to land in a working workspace within moments. Just as important is the **setup** step: Tesslate Studio analyzes a project, detects what stack it is, and proposes the containers and services needed to run it (the Librarian flow that produces `.tesslate/config.json`). When that analysis is accurate and the manual controls are honest, the customer trusts the platform with their app. When it guesses wrong or hides what it's doing, they lose confidence before they've built a thing.

**Suite prerequisites:** Tester A logged in, on a tier with project quota available. A public Git repo URL ready to import (a small real app, e.g. a Vite or Next.js starter). For the private-repo case, a connected GitHub/GitLab provider (see suite 20) and access to a private repo. For the quota case, an account already at or near its project limit.

---

### `CREATE-01` - Create a project
- **Customer value:** The core first step - a customer can spin up a fresh workspace to build in.
- **Priority:** Critical
- **Pre:** Logged in as Tester A, below the project quota.
- **Scenario:**
  1. Start a new project and choose the empty / from-scratch option.
  2. Give it a name and confirm.
  3. Wait for the project to be ready and observe where you land.
- **What good looks like:**
  - Creation is quick - the project is ready in seconds, not minutes, with visible progress if it takes any time.
  - You are taken straight into the project's workspace (or setup), not left guessing.
  - The new project appears on the dashboard with a sensible name and a unique slug.
  - The workspace opens with editor, chat, and preview areas reachable.
- **Watch for:** a long unexplained wait; the project stuck in an "initializing" or "failed" state; landing on a blank screen; the project missing from the dashboard afterward.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CREATE-02` - Create a project from a template
- **Customer value:** A customer can start from a ready-made base instead of an empty folder, saving setup time.
- **Priority:** High
- **Pre:** Logged in; at least one template/base available.
- **Scenario:**
  1. Start a new project and choose to create from a template/base.
  2. Browse the available templates, pick one, name the project, and create.
  3. Open the new project's workspace and look at the file tree.
- **What good looks like:**
  - Templates are presented clearly enough to choose between (name, description, maybe a preview).
  - The new project comes pre-populated with the template's files - it is genuinely a head start, not empty.
  - The project is ready quickly and opens into a usable workspace.
  - The template's app is coherent - files reference each other correctly, nothing obviously missing.
- **Watch for:** templates that fail to copy fully; a "template" project that opens empty; broken or placeholder files; the choice screen being confusing.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CREATE-03` - Import a project from a public Git repo
- **Customer value:** A customer can bring an existing codebase into Tesslate Studio and keep working on it here.
- **Priority:** High
- **Pre:** Logged in; a public Git repo URL for a real, small app.
- **Scenario:**
  1. Start a new project and choose import from Git.
  2. Paste the public repo URL, set the branch, and create.
  3. Wait for the clone, then open the workspace and inspect the files.
- **What good looks like:**
  - The import shows progress and completes in a reasonable time.
  - The repo's files appear in the workspace, intact and matching the source.
  - The branch you chose is the one imported.
  - You land in a usable workspace ready to set up and run.
- **Watch for:** a silent or stuck import; missing files or a truncated tree; the wrong branch; no feedback while it clones.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CREATE-04` - Import a private Git repo with a connected provider
- **Customer value:** A customer can import their own private code once they've connected their Git provider.
- **Priority:** Medium
- **Pre:** GitHub (or GitLab) connected in Settings -> Connections; access to a private repo on that account.
- **Scenario:**
  1. Start a new project and choose import from Git.
  2. Paste the private repo URL and create.
  3. Confirm the import succeeds and the files appear.
- **What good looks like:**
  - The import uses the connected provider's access automatically - no manual token paste.
  - The private repo clones successfully and its files appear intact.
  - The experience is the same smooth flow as a public import.
- **Watch for:** a permission failure despite a connected provider; being asked to paste a token anyway; a credential or token leaking into any error or log message.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CREATE-05` - Import error handling feels helpful
- **Customer value:** When an import can't work, the customer understands why and what to fix, instead of hitting a wall.
- **Priority:** Medium
- **Pre:** Logged in; the Git import flow.
- **Scenario:**
  1. Try to import an obviously invalid / unreachable repo URL.
  2. Try a valid repo URL but a branch name that does not exist.
  3. Try a private repo URL without any connected provider.
- **What good looks like:**
  - Each failure produces a clear, plain-language message naming the problem (bad URL, no such branch, no access).
  - The flow stays usable - you can correct the input and retry without starting over.
  - No raw stack traces, and no half-created broken project left behind.
- **Watch for:** a generic "something went wrong"; a project created in a broken state on failure; the flow locking up; technical error dumps.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CREATE-06` - Naming and slug feel sensible
- **Customer value:** A customer can name a project naturally and trust it to be identified cleanly across the product.
- **Priority:** Medium
- **Pre:** Logged in; the create-project flow.
- **Scenario:**
  1. Create a project with a normal name containing spaces and mixed case.
  2. Create another with a long name and some punctuation.
  3. Check how each appears on the dashboard and in its workspace URL.
- **What good looks like:**
  - The display name is preserved as typed; the generated slug is clean, readable, and unique.
  - Long names truncate gracefully in the UI rather than breaking the layout.
  - Two projects with the same name still get distinct slugs and are distinguishable.
- **Watch for:** an unreadable or collision-prone slug; the name being silently mangled; layout breaking on a long name.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CREATE-07` - Hitting the project quota
- **Customer value:** When a customer reaches their plan's project limit, they understand it and see a clear way forward - it should feel like a gentle nudge, not a brick wall.
- **Priority:** High
- **Pre:** An account already at its tier's project limit.
- **Scenario:**
  1. Try to create one more project.
  2. Read the message and whatever options are offered.
- **What good looks like:**
  - The limit is communicated clearly and kindly - it explains you've reached your plan's project count.
  - A genuine path forward is offered (upgrade, or delete an existing project).
  - The moment feels intentional, not like an error or a crash.
  - Existing projects remain fully usable.
- **Watch for:** a raw error or 403-style message; no explanation of why; no path to resolve it; the create UI breaking instead of explaining.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CREATE-08` - Open the new project's workspace
- **Customer value:** A customer can get into their project and start working with no friction.
- **Priority:** Critical
- **Pre:** A project exists (from any earlier case).
- **Scenario:**
  1. From the dashboard, open the project.
  2. Wait for the workspace to fully load.
  3. Glance over the editor, file tree, chat, and preview areas.
- **What good looks like:**
  - The workspace opens quickly and fully - no half-loaded panels.
  - The file tree, code editor, chat, and preview are all present and reachable.
  - The project's state (files, any prior config) is correctly loaded.
  - It feels like a real IDE-style environment, ready to use.
- **Watch for:** a slow or partial load; missing panels; an error on open; the workspace looking empty for a project that has files.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CREATE-09` - Project analysis detects the stack
- **Customer value:** The platform inspects an imported or new project and figures out what it is and how to run it - so the customer doesn't have to configure containers by hand.
- **Priority:** High
- **Pre:** A project with real code (an imported repo or template) open; the setup / analyze flow available.
- **Scenario:**
  1. Open the project's setup and run the analyze / agent analysis step.
  2. Watch the analysis work and read what it proposes.
- **What good looks like:**
  - The analysis shows progress - you can see it working, not a frozen wait.
  - It correctly identifies the stack (e.g. "Next.js frontend", "FastAPI backend") for the project you gave it.
  - It proposes sensible containers, ports, and startup commands that match the project.
  - The result is presented for review before anything is committed - it's a proposal, not a silent change.
- **Watch for:** a wrong stack guess (a Node app called a Python app, etc.); a missing service; the analysis hanging or failing with no message; proposals so generic they're useless.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CREATE-10` - Review and accept the proposed configuration
- **Customer value:** A customer can confirm the detected setup and have it become their project's real, runnable configuration.
- **Priority:** High
- **Pre:** `CREATE-09` completed - an analysis proposal is on screen.
- **Scenario:**
  1. Review the proposed containers and startup commands.
  2. Accept / save the configuration.
  3. Check that the containers now show up in the workspace / architecture view.
- **What good looks like:**
  - Accepting the proposal creates real container definitions tied to the project.
  - The saved config is reflected consistently in the setup screen and the architecture view.
  - The project is now in a startable state (suite 5 covers actually running it).
  - The `.tesslate/config.json` is genuinely written - re-opening setup shows the same config.
- **Watch for:** the accepted config not persisting; containers missing from the architecture view; setup and architecture views disagreeing; needing to re-run analysis to see your own saved config.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CREATE-11` - Configure a service by hand
- **Customer value:** A customer who knows their stack - or wants to override the analysis - can define a container themselves.
- **Priority:** High
- **Pre:** A project's setup page open, with a manual configuration option.
- **Scenario:**
  1. Switch to manual service configuration.
  2. Add a container - set its image, port, and startup command.
  3. Save and confirm it appears in the workspace / architecture view.
  4. Enter an obviously invalid value (e.g. a port out of range, two services on the same port) and try to save.
- **What good looks like:**
  - The manual form is clear about what each field expects.
  - A valid container saves and shows up correctly.
  - Invalid input is caught with a specific, actionable message - you cannot save a broken config.
  - In-progress input survives switching between the analyze and manual tabs.
- **Watch for:** a confusing or unlabelled form; an invalid config saving silently; vague "invalid" errors; losing your typed input when switching tabs.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CREATE-12` - Add an infrastructure service
- **Customer value:** A customer can add a database or cache (Postgres, Redis, etc.) to their project without sourcing and configuring an image themselves.
- **Priority:** Medium
- **Pre:** A project's setup page open.
- **Scenario:**
  1. From the infrastructure / service catalog, add a service such as Postgres or Redis.
  2. Save the configuration.
  3. Confirm the service is added and is startable alongside the app.
- **What good looks like:**
  - The catalog offers common infrastructure (Postgres, Redis, MySQL, Mongo, object storage) with no manual image hunting.
  - The added service appears in the project's container list and architecture view.
  - The service is configured with sane defaults and is ready to start.
  - It's clear how the app would connect to it (connection details / env var hints).
- **Watch for:** a service added but not actually startable; no defaults so the customer must configure everything; the new service missing from the architecture view.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CREATE-13` - Set environment variables
- **Customer value:** A customer can give their containers the configuration values (API keys, connection strings, flags) their app needs to run.
- **Priority:** Medium
- **Pre:** A project with at least one container; the container config open.
- **Scenario:**
  1. Add a couple of environment variables to a container and save.
  2. Reopen the config and confirm they persisted.
  3. Start the container and confirm the values are actually present inside it (e.g. the app reads them, or they show in the running container).
- **What good looks like:**
  - Env vars are easy to add, edit, and remove.
  - Saved values persist across reopening the config.
  - The values genuinely reach the running container - the app sees them.
  - Sensitive-looking values are handled sensibly (not echoed everywhere in plaintext logs).
- **Watch for:** env vars not persisting; values not reaching the container at runtime; the editor losing entries on save; secrets leaking into logs or the UI.
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
**Overall project-creation experience (1-5) & notes:** 
