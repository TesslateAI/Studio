# Suite 5 - Containers & live preview

> See [README.md](README.md) for format, priorities, severity, environments, and accounts.

**Why this suite matters:** Generating code is only half the promise - the customer needs to *see their app running*. Containers and the live preview are where "the AI built it" becomes "and here it is, working." This is the payoff moment of the whole product, so it has to feel reliable: starting the app should be one click and visibly progressing, the preview should render the real running app, and changes should show up without a fuss. Equally important is the unhappy path - when a container fails to start, the customer must *see* the failure, understand it, and have an obvious route to fix it (often "ask the agent"). A preview that hangs, a status dot that lies, or a failure with no logs erodes trust faster than almost anything else.

**Suite prerequisites:** Tester A logged in. A configured, startable project with at least one web container (a template or a project that completed setup in suite 2). For multi-container cases, a project with two or more containers (e.g. app + database). For failure cases, a project you can deliberately break (a bad startup command or missing dependency). Confirm your environment's deployment mode - preview URLs differ between Cloud, Docker, and Desktop.

---

### `RUN-01` - Start the project's containers
- **Customer value:** A customer can bring their app to life with one action and watch it come up.
- **Priority:** Critical
- **Pre:** A configured project with at least one container, currently stopped.
- **Scenario:**
  1. Click Start on the project.
  2. Watch the startup progress and status indicators.
- **What good looks like:**
  - Startup begins immediately with visible progress or logs - no silent dead air.
  - The container(s) reach a running/healthy state in a reasonable time.
  - Status indicators move clearly from stopped -> starting -> running (green).
  - When it's ready, it's obvious the app is up and the preview is available.
- **Watch for:** a long unexplained wait; status stuck on "starting"; a green status that doesn't actually mean running; no feedback at all until it's done.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `RUN-02` - Stop the project
- **Customer value:** A customer can shut their app down cleanly when they're done.
- **Priority:** Critical
- **Pre:** A project with containers running.
- **Scenario:**
  1. Click Stop.
  2. Watch the status indicators.
- **What good looks like:**
  - The containers shut down promptly and gracefully.
  - Status moves clearly to stopped/idle.
  - The action feels final and clean - no lingering "stopping..." limbo.
- **Watch for:** containers that won't stop; status stuck on "stopping"; the project still appearing to consume resources after stop; an error on stop.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `RUN-03` - Restart the project
- **Customer value:** A customer can restart their app to pick up changes or recover from a hiccup.
- **Priority:** High
- **Pre:** A project with containers running.
- **Scenario:**
  1. Click Restart.
  2. Watch it stop and come back up.
- **What good looks like:**
  - The restart cycle is one action - stop then start happens automatically.
  - The end state is running/healthy with green status.
  - The preview works again afterward.
  - The whole cycle completes in a reasonable time with visible progress.
- **Watch for:** the project getting stuck mid-cycle; ending in a stopped or failed state instead of running; the preview not recovering.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `RUN-04` - Live preview renders the running app
- **Customer value:** The payoff - the customer sees their actual working app rendered live inside Tesslate Studio.
- **Priority:** Critical
- **Pre:** A web container running.
- **Scenario:**
  1. Open the preview pane.
  2. Look at the rendered app.
  3. Click around inside the preview - navigate between pages, use interactive elements.
- **What good looks like:**
  - The preview shows the real running app, fully rendered - not a blank frame or a loading state that never ends.
  - Navigation and interactions inside the preview work just like the real app.
  - The preview loads quickly once the container is up.
  - It genuinely feels like "there's my app" - the satisfying payoff of the build.
- **Watch for:** a blank or perpetually loading preview; the app rendering broken/unstyled; interactions inside the preview not working; a mismatch between the preview and what the app should be.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `RUN-05` - Refresh the preview
- **Customer value:** A customer can reload the preview to see the current state of their app.
- **Priority:** Medium
- **Pre:** `RUN-04` - preview open and rendering.
- **Scenario:**
  1. Click the preview's refresh control.
- **What good looks like:**
  - The preview reloads and shows current content.
  - The refresh is quick and the preview doesn't break or go blank afterward.
- **Watch for:** refresh leaving a blank frame; the preview losing its URL/route; a slow or stuck reload.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `RUN-06` - Open the preview in a new tab
- **Customer value:** A customer can view their running app full-screen in its own browser tab.
- **Priority:** Low
- **Pre:** `RUN-04` - a web container running.
- **Scenario:**
  1. Use the "open in new tab" control on the preview.
- **What good looks like:**
  - The app opens at its full URL in a separate browser tab and renders correctly.
  - It behaves like the real app - navigation works.
- **Watch for:** the new tab erroring or showing a wrong/blank page; an access error opening the app's URL directly.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `RUN-07` - Hot reload on a code change
- **Customer value:** A customer changes code and sees the result in the preview almost immediately - the build-see-tweak loop feels live.
- **Priority:** High
- **Pre:** A dev-server container running; the preview open.
- **Scenario:**
  1. Make a visible change to a source file - edit it yourself or have the agent do it.
  2. Save and watch the preview.
- **What good looks like:**
  - The preview updates to reflect the change quickly - automatically, or after an obvious refresh.
  - The change shown matches the edit made.
  - The loop feels tight enough to iterate comfortably.
- **Watch for:** the preview not updating at all; needing a full project restart for a trivial change; a long lag before the change appears; the preview breaking after a reload.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `RUN-08` - Switch the preview between containers
- **Customer value:** In a multi-service project, a customer can preview each running service, not just one.
- **Priority:** Medium
- **Pre:** A project with two or more containers running (e.g. a frontend and a separate web service).
- **Scenario:**
  1. With the preview open, use the container/service selector.
  2. Switch to a different container's preview.
- **What good looks like:**
  - The selector clearly lists the available containers.
  - Switching shows the chosen container's app at its correct URL/port.
  - Each container's preview renders correctly.
- **Watch for:** the selector missing containers; switching showing the wrong app or a blank frame; the selector not reflecting which container is actually running.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `RUN-09` - Container status indicators tell the truth
- **Customer value:** A customer can trust the status dots - they actually reflect whether the app is up, starting, or broken.
- **Priority:** High
- **Pre:** A multi-container project.
- **Scenario:**
  1. Watch the status indicators through a full start cycle.
  2. Hover over them to read any tooltips/details.
  3. Stop the project and watch them again.
- **What good looks like:**
  - Indicators transition stopped -> starting -> running in step with what's actually happening.
  - Tooltips/details give meaningful state ("running since...", "starting...", an error reason).
  - A failed container is shown as failed, not green.
  - When stopped, everything reads stopped.
- **Watch for:** a status that lags reality or shows green for a dead container; vague or missing tooltips; indicators that don't update without a manual refresh.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `RUN-10` - View container logs
- **Customer value:** A customer can watch their app's logs to understand what it's doing and diagnose problems.
- **Priority:** High
- **Pre:** A container running.
- **Scenario:**
  1. Open the container's logs view.
  2. Watch logs stream as the app runs.
  3. Search the logs for a term; copy a section; download the logs.
- **What good looks like:**
  - Recent output is shown and new lines stream in live.
  - Auto-scroll keeps up; ANSI colors render rather than showing escape codes.
  - Search highlights matches; copy puts log text on the clipboard; download produces a usable text file.
  - The logs are readable - not a cramped or truncated mess.
- **Watch for:** logs not streaming; raw escape codes instead of color; search/copy/download missing or broken; the view lagging badly with a lot of output.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `RUN-11` - A failed startup is visible and debuggable
- **Customer value:** When the app fails to start, the customer sees the failure clearly and has an obvious path to fix it - not a silent hang.
- **Priority:** High
- **Pre:** A project deliberately broken so startup fails (e.g. a bad startup command or a missing dependency).
- **Scenario:**
  1. Start the project.
  2. Observe how the failure is reported.
  3. Look for the failure logs and any offered next step (e.g. "ask the agent to fix it").
- **What good looks like:**
  - The container clearly shows a failed/error state - it does not hang in "starting" forever.
  - The failure logs are right there and explain what went wrong.
  - There is an obvious path forward - a way to retry, or to hand the error to the agent.
  - The failure feels handled and recoverable, not like a dead end.
- **Watch for:** an indefinite "starting" with no failure ever reported; no logs to explain the failure; no route to fix it; the whole workspace becoming unusable after a failed start.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `RUN-12` - Fixing a broken startup brings the app back
- **Customer value:** After a startup failure, the customer can apply a fix and successfully get the app running.
- **Priority:** High
- **Pre:** `RUN-11` - a project in a failed-startup state.
- **Scenario:**
  1. Apply the fix - correct the bad command/dependency yourself, or ask the agent to fix it.
  2. Start the project again.
  3. Open the preview.
- **What good looks like:**
  - After the fix, starting succeeds and the container reaches a healthy state.
  - The error state clears - the status reflects the recovery.
  - The preview renders the working app.
  - The recovery loop (see failure -> fix -> restart -> working) feels smooth and complete.
- **Watch for:** a stale error state lingering after a successful restart; needing to recreate the project to recover; the preview not coming back; the fix not taking effect without extra manual steps.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `RUN-13` - Preview when the project is stopped
- **Customer value:** A customer who opens the preview while the app is stopped gets a clear explanation, not a broken screen.
- **Priority:** Medium
- **Pre:** A project with containers stopped.
- **Scenario:**
  1. With the project stopped, open the preview pane.
- **What good looks like:**
  - The preview shows a clear "not running / stopped" placeholder.
  - It's obvious how to start the project from there.
  - There is no broken or blank iframe pretending to be the app.
- **Watch for:** a blank/error frame instead of a friendly placeholder; a confusing message; no clear way to start the project.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `RUN-14` - Partial start failure stays usable
- **Customer value:** When one service in a multi-container project fails, the rest still start and the customer can see exactly what's wrong.
- **Priority:** Medium
- **Pre:** A multi-container project where one container is set up to fail (the others healthy).
- **Scenario:**
  1. Start the project.
  2. Observe the state of each container.
- **What good looks like:**
  - The healthy containers still start and are usable; their previews work.
  - The failed container is clearly flagged with its own error and logs.
  - The overall project status honestly reflects "partial" - not a blanket green or a total failure.
  - You can act on just the failed service without tearing everything down.
- **Watch for:** the whole project marked failed when only one service broke; the failed container hidden or shown as healthy; healthy services unusable because of the one failure; no per-container error detail.
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
**Overall containers & preview experience (1-5) & notes:** 
