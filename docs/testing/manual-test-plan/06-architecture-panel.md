# Suite 6 - Architecture panel

> See [README.md](README.md) for format, priorities, severity, environments, and accounts.

**Why this suite matters:** Most customers describe their app in chat and never think about the plumbing - but the moment a project grows past a single container, they need to *see* it. The architecture panel is where a customer understands their app as a system: a web frontend, an API, a database, how they talk to each other, and where it deploys. It only earns its place if it is genuinely clarifying - accurate to the real running project, easy to navigate, and able to make real changes (wire a database in, inject the right env var) without dropping to a terminal. A pretty diagram that lies about the project, or one that's read-only when the customer expects to edit, is worse than no panel at all.

**Suite prerequisites:** Tester A logged in. A project open in the builder with at least one container configured (see suites 2 and 8). For the connection and multi-container cases, a project with at least two containers - ideally a web/API container plus a database (Postgres/Redis). Have the project startable so the browser-preview node can show a live app.

---

### `ARCH-01` - Architecture canvas loads and mirrors the real project
- **Customer value:** A customer opens one screen and instantly sees what their app is actually made of.
- **Priority:** High
- **Pre:** A project with one or more configured containers.
- **Scenario:**
  1. Open the project and switch to the Architecture / Graph view.
  2. Compare what's drawn to what the project actually contains.
- **What good looks like:**
  - Every container in the project appears as its own node - none missing, none invented.
  - Each node shows the essentials at a glance: name, image, current status, and port.
  - Status on each node matches reality (a running container shows running; a stopped one shows stopped).
  - The canvas finishes drawing quickly and is ready to interact with.
- **Watch for:** nodes that don't match the real container list; stale status; a long blank canvas before anything renders; an error instead of a graph.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ARCH-02` - Pan, zoom, and fit-to-screen
- **Customer value:** A customer can move around a larger architecture comfortably and re-center when lost.
- **Priority:** Medium
- **Pre:** `ARCH-01`; ideally a project with several nodes.
- **Scenario:**
  1. Scroll/pinch to zoom in and out.
  2. Drag empty canvas space to pan around.
  3. Click "fit to screen" / "fit view".
- **What good looks like:**
  - Zoom and pan feel smooth - no jitter, no lag, no fighting the scroll.
  - Fit-to-screen reframes so every node is visible and reasonably sized.
  - You can always recover a sensible view; you never get stranded zoomed into empty space.
- **Watch for:** janky or inverted zoom; panning that snaps back; fit that cuts nodes off or zooms uselessly far out.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ARCH-03` - Inspect and edit a container node's properties
- **Customer value:** A customer adjusts a container's settings - a port, an env var - right from the diagram.
- **Priority:** High
- **Pre:** `ARCH-01`.
- **Scenario:**
  1. Click a container node to open its properties / details panel.
  2. Read its current settings (image, port, env vars, startup command).
  3. Change a field - e.g. add an environment variable or change the port - and save.
  4. Reopen the node, and cross-check against the project's setup/config view.
- **What good looks like:**
  - The properties panel opens promptly and shows the node's real, current configuration.
  - Editing is obvious; the save action gives clear confirmation.
  - The change persists - it survives reopening the panel and shows up in the setup/config view too.
  - Settings are presented readably, not as a raw JSON blob.
- **Watch for:** edits that silently don't save; the panel showing different values than the setup page; no feedback on save; the panel showing fields that don't apply.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ARCH-04` - Drag nodes and auto-layout
- **Customer value:** A customer arranges the diagram to match how they think, or lets the panel tidy it for them.
- **Priority:** Low
- **Pre:** `ARCH-01` with at least two nodes.
- **Scenario:**
  1. Drag a node to a new position.
  2. Drag a couple more to deliberately mess up the layout.
  3. Click auto-layout / arrange.
- **What good looks like:**
  - Nodes drag freely and follow the cursor; connections re-route with them.
  - Auto-layout produces a clean, readable arrangement with nodes spaced out and edges uncrossed where possible.
  - Manual positions are remembered (or it's clear they reset on auto-layout - either way, no surprise).
- **Watch for:** nodes that snap back or lag the cursor; edges that detach during a drag; auto-layout piling nodes on top of each other.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ARCH-05` - Browser-preview node shows the live app
- **Customer value:** A customer sees their actual running app embedded right in the architecture, alongside its services.
- **Priority:** Medium
- **Pre:** A project with a web container; the project started so the web app is reachable (see suite 5).
- **Scenario:**
  1. Locate or add the browser-preview node on the canvas.
  2. Look at what it renders while the web container is running.
- **What good looks like:**
  - The preview node embeds the live app - the same thing you'd see in the full preview pane.
  - It updates to reflect the running container, not a static placeholder.
  - When the container is stopped, the node shows a clear "not running" state rather than a broken frame.
- **Watch for:** a permanently blank or broken-iframe preview; the preview pointing at the wrong container; the node showing stale content after a restart.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ARCH-06` - Wire two containers together with a connection
- **Customer value:** A customer connects their API to a database visually, and the wiring just works - no hand-edited env files.
- **Priority:** High
- **Pre:** A project with at least two containers (e.g. an API container and a Postgres/Redis container).
- **Scenario:**
  1. Draw an edge from one node to another (e.g. API -> database).
  2. Choose the connection type when prompted - HTTP, database, or cache.
  3. Inspect the target container's environment variables.
  4. Start (or restart) the project and confirm the dependent container can actually reach the other.
- **What good looks like:**
  - Drawing the edge is intuitive; the connection appears with styling/labelling that conveys its type.
  - The right environment variable is injected automatically into the consuming container - e.g. a `DATABASE_URL` for a database connection, a service URL for HTTP.
  - The injected value points at the correct service and is usable as-is; the customer doesn't have to compose a connection string by hand.
  - At runtime the connection genuinely works - the app can talk to the connected service.
- **Watch for:** an edge that draws but injects nothing; a wrong or malformed connection string; the env var injected into the wrong container; the connection looking set up but failing at runtime.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ARCH-07` - Remove a connection cleanly
- **Customer value:** A customer changes their mind about how services connect and can undo the wiring without leftovers.
- **Priority:** Medium
- **Pre:** `ARCH-06` - a connection exists between two containers.
- **Scenario:**
  1. Select the connection edge on the canvas.
  2. Delete it.
  3. Re-inspect the previously-consuming container's environment variables.
- **What good looks like:**
  - The edge is removed from the canvas immediately.
  - The environment variable that the connection injected is also removed - no orphaned, now-meaningless config left behind.
  - Nothing unrelated changes; other connections and env vars are untouched.
- **Watch for:** the edge vanishing but the injected env var staying; deleting one connection wiping others; needing a manual save that isn't obvious.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ARCH-08` - Add a deployment-target node
- **Customer value:** A customer sees where their app ships as part of its architecture, and can start a deployment from the diagram.
- **Priority:** Medium
- **Pre:** `ARCH-01`.
- **Scenario:**
  1. Add a deployment-target node (e.g. Vercel / Netlify / Cloudflare) onto the canvas.
  2. Observe what it asks for and how it connects to the app.
- **What good looks like:**
  - A deployment node appears on the canvas and is visually distinct from a container node.
  - If no provider credentials are configured, it clearly prompts to connect one rather than silently doing nothing.
  - It reads as part of the app's story - the customer can see "this frontend deploys here".
- **Watch for:** a node that does nothing when clicked; no credential prompt and no deployment path; the node added but not associable with any container.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ARCH-09` - The architecture stays accurate after the app changes
- **Customer value:** A customer trusts the diagram because it keeps up with the real project as they build.
- **Priority:** Medium
- **Pre:** An architecture canvas open; a project the agent or setup flow can modify.
- **Scenario:**
  1. With the architecture view as a reference, have the agent (or the setup flow) add a new container or service to the project.
  2. Return to the architecture view (refresh if needed).
- **What good looks like:**
  - The new container shows up as a node, with correct name, image, and status.
  - Existing nodes, positions, and connections are not lost or scrambled by the update.
  - The diagram continues to be a truthful map of the project - not a snapshot frozen at first load.
- **Watch for:** new containers never appearing; the canvas needing a hard reload to be correct; existing layout/connections wiped on update; the panel erroring after a project change.
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
**Overall architecture-panel experience (1-5) & notes:** 
