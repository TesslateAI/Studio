# Suite 21 - Desktop app

> See [README.md](README.md) for format, priorities, severity, environments, and accounts.

**Why this suite matters:** The desktop app is Tesslate Studio for customers who want their code on their own machine - local files, local runtimes, no cloud dependency for the core loop. It is the same React UI and FastAPI backend as cloud, but wrapped in a Tauri shell that has to do hard, invisible work: spawn a backend sidecar, set up a local database, survive crashes, live in the system tray, run projects as local processes or Docker containers, adopt folders straight off disk, and sync with the cloud when the customer wants it to. A customer judges all of this in the first thirty seconds - if the app doesn't launch cleanly, nothing else matters. Every case here is **Desktop only**: run them on a real installed (or `cargo tauri dev`) build of the desktop app, not a browser.

**Suite prerequisites:** The OpenSail desktop app installed (or a dev build running). A Tesslate account to sign in / pair with. For Docker-runtime cases, Docker Desktop installed and running. For sync/pairing cases, a reachable cloud environment and the same account on both. For the import case, an existing code folder on disk. OS notification permission can be granted when prompted.

---

### `DESKTOP-01` - App launches and the backend connects [Desktop only]
- **Customer value:** A customer double-clicks the app icon and, moments later, has a working product - no terminal, no setup.
- **Priority:** Critical
- **Pre:** The desktop app installed; not currently running.
- **Scenario:**
  1. Launch the OpenSail desktop app.
  2. Watch from the splash/loading state through to the UI being usable.
- **What good looks like:**
  - The window opens promptly and shows a clear loading/starting state - not a frozen blank window.
  - The bundled backend sidecar starts and the UI connects to it within a reasonable time (a handful of seconds, not minutes).
  - You reach a usable dashboard; you can sign in and see your workspace.
  - No raw error text, port warnings, or developer console noise is shown to the customer.
- **Watch for:** a permanently white/blank window; a "cannot connect to backend" state with no recovery; an extremely long startup; the app appearing ready before the backend actually is.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `DESKTOP-02` - First-run local setup [Desktop only]
- **Customer value:** A brand-new customer's first launch quietly sets up their local data so they can start working immediately.
- **Priority:** Critical
- **Pre:** A fresh install - no prior OpenSail data on this machine (or the OpenSail home directory cleared).
- **Scenario:**
  1. Launch the app for the very first time.
  2. Let it complete first-run setup; then create a project and confirm it persists.
  3. Quit and relaunch the app.
- **What good looks like:**
  - First run sets up the local database and home directory without the customer doing anything manual.
  - The first launch may take slightly longer than later ones, but it's clearly progressing.
  - Data created on first run (a project, sign-in) is still there after a relaunch.
- **Watch for:** a first-run that errors and leaves a half-initialized state; the customer asked to configure paths or databases; data lost between the first and second launch.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `DESKTOP-03` - Sidecar crash recovery [Desktop only]
- **Customer value:** If the backend process dies, the app should heal itself rather than leave the customer with a dead window.
- **Priority:** High
- **Pre:** The desktop app running normally.
- **Scenario:**
  1. Using the OS task manager / activity monitor, find and kill the backend sidecar process (the orchestrator process the app spawned).
  2. Watch the app and keep using it.
- **What good looks like:**
  - The app notices the backend is gone and automatically restarts it.
  - The UI either reconnects on its own or clearly tells the customer it's recovering, then recovers.
  - Within a short window the app is fully usable again - no permanent broken state.
- **Watch for:** the app hanging forever after the sidecar dies; no restart attempt; the customer forced to manually quit and relaunch; corrupted state after recovery.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `DESKTOP-04` - System tray: minimize, tooltip, open, quit [Desktop only]
- **Customer value:** A customer keeps OpenSail running quietly in the background and pulls it up when they need it.
- **Priority:** High
- **Pre:** The desktop app running.
- **Scenario:**
  1. Minimize / close the window to the tray and confirm the app keeps running.
  2. Hover over the tray icon and read the tooltip.
  3. Use the tray menu to re-open the Studio window.
  4. Use the tray menu to Quit.
- **What good looks like:**
  - Minimizing to tray keeps the app and its backend alive in the background.
  - The tray tooltip shows something useful (e.g. running agents/projects counts) and stays reasonably current.
  - "Open Studio" brings the window back to the foreground reliably.
  - "Quit" fully exits - the window closes and the backend sidecar shuts down too, leaving no orphan process.
- **Watch for:** the app fully exiting when it should only minimize; a stale or empty tooltip; "Open" not restoring the window; "Quit" leaving the backend process running.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `DESKTOP-05` - Window controls [Desktop only]
- **Customer value:** The app behaves like a real native window - minimize, maximize, move, close all just work.
- **Priority:** Medium
- **Pre:** The desktop app running.
- **Scenario:**
  1. Minimize, maximize/restore, and drag the window around.
  2. Resize the window and observe the UI reflow.
  3. Close the window via the window control.
- **What good looks like:**
  - All window controls behave as the OS conventions expect.
  - The UI reflows cleanly at different window sizes - no clipped or overlapping content.
  - Dragging is smooth; the window stays where you put it.
- **Watch for:** controls that do nothing; a window that can't be resized below a huge minimum; layout breaking at small sizes; jerky dragging.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `DESKTOP-06` - Create and run a project on the local runtime [Desktop only]
- **Customer value:** A customer builds and runs an app entirely on their own machine, with no containers or cloud involved.
- **Priority:** Critical
- **Pre:** The desktop app running; signed in.
- **Scenario:**
  1. Create a new project and choose the **local** runtime.
  2. Let setup complete; start the project.
  3. Open the live preview and interact with the running app.
- **What good looks like:**
  - The project is created with the local runtime and its files live on the local disk.
  - Starting it runs the app as a local process; the preview renders the running app.
  - It feels as smooth as the cloud builder - no extra friction for being local.
- **Watch for:** the project failing to start with a port or process error; the preview never loading; the runtime silently falling back to something else.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `DESKTOP-07` - Create a project on the Docker runtime [Desktop only]
- **Customer value:** A customer who prefers containerized isolation runs their project under Docker straight from the desktop app.
- **Priority:** High
- **Pre:** Docker Desktop installed and running on the machine; the desktop app running.
- **Scenario:**
  1. Create a new project and choose the **docker** runtime.
  2. Start the project and open the preview.
  3. Separately, quit Docker Desktop and confirm the runtime picker reflects Docker being unavailable.
- **What good looks like:**
  - The Docker runtime option is offered (and selectable) when Docker is actually available.
  - The project builds and runs in containers; the preview works.
  - When Docker is not running, the picker clearly shows the Docker option as unavailable with a reason - it doesn't let the customer pick a broken runtime.
- **Watch for:** the Docker option offered even when Docker is down; a cryptic failure when starting a Docker project; the unavailability reason missing or unhelpful.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `DESKTOP-08` - Import a local folder as a project [Desktop only]
- **Customer value:** A customer points OpenSail at code they already have on disk and starts working on it in place - without copying or re-uploading.
- **Priority:** High
- **Pre:** An existing code folder on disk; the desktop app running.
- **Scenario:**
  1. Use the import / "open existing folder" flow and pick the folder.
  2. Give it a name and choose a runtime; confirm.
  3. Open the imported project and browse its file tree.
  4. Try importing the *same* folder again.
- **What good looks like:**
  - The folder is adopted as a project without copying files - it works against the original location.
  - The file tree shows the real contents of the folder.
  - Re-importing the same folder is handled gracefully (it recognizes the existing project rather than creating a confusing duplicate).
- **Watch for:** the import duplicating or moving the customer's files; a non-folder path accepted then failing; the same folder importable twice as two separate projects; the file tree empty or wrong.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `DESKTOP-09` - Cloud pairing via deep link [Desktop only]
- **Customer value:** A customer links their desktop app to their cloud account so local and cloud work can flow together.
- **Priority:** High
- **Pre:** The desktop app running; a Tesslate cloud account; the pairing flow available.
- **Scenario:**
  1. Start the cloud pairing flow from the desktop app.
  2. Complete authentication (this typically opens a browser and returns to the app via a `tesslate://` deep link).
  3. Back in the desktop app, confirm the paired state.
- **What good looks like:**
  - The pairing flow opens cleanly and the browser-to-app handoff works - the deep link returns you to the desktop app.
  - After pairing, the app clearly shows it's connected to the cloud account.
  - The paired state survives a relaunch - the customer doesn't have to re-pair every session.
- **Watch for:** the deep link not returning to the app; pairing appearing to succeed but the app still showing "not paired"; the pairing lost on relaunch.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `DESKTOP-10` - Push a local project to the cloud [Desktop only]
- **Customer value:** A customer who built locally wants their project safely in the cloud - backed up and reachable from elsewhere.
- **Priority:** High
- **Pre:** Desktop app paired with the cloud (`DESKTOP-09`); a local project with some content.
- **Scenario:**
  1. From the project, trigger a sync push to the cloud.
  2. Watch the progress and result.
  3. Check the sync status indicator afterward.
- **What good looks like:**
  - The push runs with visible progress and completes with a clear success result.
  - The sync status then reads "in sync" / up to date.
  - Build artifacts and junk (e.g. `node_modules`, `.git` internals) are not uploaded - only the real project files.
- **Watch for:** the push hanging with no feedback; a vague failure with no reason; the status not updating to "in sync"; huge unnecessary uploads of dependency folders.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `DESKTOP-11` - Pull cloud changes to the desktop [Desktop only]
- **Customer value:** A customer who changed a project elsewhere brings those updates down to their desktop copy.
- **Priority:** High
- **Pre:** A project that exists both locally and in the cloud, with newer changes in the cloud.
- **Scenario:**
  1. From the project, trigger a sync pull.
  2. Watch the result, then open the file tree / editor to confirm the cloud changes arrived.
- **What good looks like:**
  - The pull completes with a clear result and the cloud changes appear in the local project.
  - The update is applied cleanly - the project isn't left half-written or corrupted if something interrupts it.
  - The sync status reads "in sync" afterward.
- **Watch for:** the pull silently doing nothing; partial files; the local project corrupted by an interrupted pull; the status still showing out-of-date.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `DESKTOP-12` - Sync conflict is handled safely [Desktop only]
- **Customer value:** When the same project changed both locally and in the cloud, the customer must not silently lose work.
- **Priority:** High
- **Pre:** A project synced to the cloud; then change it **both** locally and in the cloud so the two diverge.
- **Scenario:**
  1. Make a distinct edit locally and a different distinct edit in the cloud copy.
  2. Attempt a sync push from the desktop.
  3. Read whatever the app tells you.
- **What good looks like:**
  - The app detects the conflict and clearly warns the customer instead of blindly overwriting.
  - The message explains that the cloud has newer changes and gives the customer a choice (e.g. pull first, or override) - not just a dead error.
  - No work is destroyed without the customer's explicit decision.
- **Watch for:** the push silently overwriting the cloud (or vice versa); a cryptic conflict error with no path forward; the customer unable to tell which version "won".
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `DESKTOP-13` - OS notifications when the window is hidden [Desktop only]
- **Customer value:** A customer with OpenSail minimized to the tray still gets pulled back when an agent finishes or needs them.
- **Priority:** Medium
- **Pre:** The desktop app running with OS notification permission granted.
- **Scenario:**
  1. Start an agent task on a project.
  2. Minimize the window to the tray so it's hidden.
  3. Wait for the task to complete (or, in ask-mode, hit an approval gate).
  4. Then bring the window back to the foreground and run another task.
- **What good looks like:**
  - While the window is hidden, an OS-level notification fires when the agent completes / needs approval, naming the project.
  - With the window visible and focused, the app uses in-app toasts instead - the customer doesn't get a redundant OS popup for the same event.
  - Clicking the notification (where supported) brings the app forward.
- **Watch for:** no notification while hidden; OS notifications firing even when the window is focused; duplicate notifications; notifications with no project context.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `DESKTOP-14` - Unified workspace: add and remove local directories [Desktop only]
- **Customer value:** A customer working across several folders on their machine manages them all in one place.
- **Priority:** Medium
- **Pre:** The desktop app running; a couple of code folders on disk.
- **Scenario:**
  1. Open the unified workspace / directories view.
  2. Add a local directory to the workspace.
  3. Add a second one; confirm both are listed.
  4. Try adding a directory that's already there.
  5. Remove one of the directories.
- **What good looks like:**
  - Added directories show up immediately with their path (and, where relevant, are grouped by git repo).
  - Adding the same directory again is handled gracefully - it doesn't create a confusing duplicate entry.
  - Removing a directory cleanly takes it off the list without touching the actual files on disk.
- **Watch for:** duplicate entries for the same folder; a removed directory still showing; the customer's files being moved or deleted on removal; the list not updating without a refresh.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `DESKTOP-15` - Auto-update check and install [Desktop only]
- **Customer value:** A customer stays on the latest version without hunting for downloads - the app updates itself.
- **Priority:** Medium
- **Pre:** A desktop build older than the latest available release, with the updater configured for this environment.
- **Scenario:**
  1. Launch the app and let the background update check run (or trigger a check if there's a manual control).
  2. When an update is offered, read the prompt.
  3. Choose to install (or "Later" first, then install).
- **What good looks like:**
  - An available update is detected and the customer gets a clear, native "Install / Later" prompt - not a silent forced restart.
  - Choosing "Later" lets the customer keep working; choosing "Install" downloads, installs, and restarts into the new version.
  - If no update is available, the check is quiet and doesn't bother the customer.
  - An update failure is non-fatal - the app keeps running on the current version.
- **Watch for:** the app force-restarting with no warning; the update failing and leaving a broken install; a noisy prompt when there's nothing to update; the restart not landing on the new version.
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
**Overall desktop experience (1-5) & notes:** 
