# Suite 17 - External Agent API

> See [README.md](README.md) for format, priorities, severity, environments, and accounts.

**Why this suite matters:** The External Agent API is how a **developer-customer** brings Tesslate's agent into their own product - a script, a CI job, an internal tool, their own SaaS. For this customer the "experience" is not a UI; it's the API itself: how fast they get a working key, how clear the responses are, how useful the event stream is, and how good the docs are. A developer evaluating Tesslate decides in minutes whether the API is pleasant to integrate against. This suite walks that evaluation. Test it as a developer would - judge clarity, predictability, and whether the events stream is genuinely useful, not just whether a request returned data.

> Every case in this suite is `[API client]` - you drive it with Postman, Insomnia, or `curl`, not the browser UI. The browser is used only to create and manage keys.

**Suite prerequisites:** Tester A logged in, with access to the API Keys settings. An API client (Postman / Insomnia / `curl`) ready. At least one project the key will be able to invoke an agent against. The base URL of the QA environment and, ideally, the API documentation the team points developers to.

---

### `API-01` - Create an API key and see it exactly once [API client]
- **Customer value:** A developer can mint a credential to authenticate their integration, and the product handles the secret responsibly.
- **Priority:** High
- **Pre:** Tester A logged in; the API Keys settings open.
- **Scenario:**
  1. Create a new API key - give it a descriptive name; if offered, set scopes and a project restriction.
  2. Read what is shown on creation.
  3. Navigate away and return to the key list.
- **What good looks like:**
  - The full key value is shown **once**, clearly flagged as the only time it will be visible, with an easy copy action.
  - After leaving and returning, only a masked preview is shown - never the full secret again.
  - The creation step is quick and the resulting key is immediately usable.
- **Watch for:** the full key retrievable again later; no warning that it's shown once; an awkward copy experience that risks the developer losing the key; the key not working right after creation.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `API-02` - List and inspect API keys [API client]
- **Customer value:** A developer managing an integration can see which keys exist, what they can do, and when they were last used.
- **Priority:** Medium
- **Pre:** `API-01` done - at least one key exists.
- **Scenario:**
  1. Open the API key list.
  2. Review each key's metadata.
- **What good looks like:**
  - Each key shows a name, its scopes, creation date, and last-used date - enough for a developer to audit and rotate keys.
  - The full secret is never re-displayed, only a masked preview.
  - The list makes it easy to tell keys apart by their names/purpose.
- **Watch for:** keys with no identifying info; missing last-used data that would help spot stale keys; the secret leaking into the list.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `API-03` - Invoke an agent over the API and get a task handle [API client]
- **Customer value:** A developer can kick off an agent run from their own code with a single authenticated request and immediately get back a handle to track it.
- **Priority:** Critical
- **Pre:** A valid API key; the base URL; a project the key can access; the invoke endpoint and payload shape known (from the docs).
- **Scenario:**
  1. Send a POST to the external agent invoke endpoint with `Authorization: Bearer <key>` and a body containing the project and a message/prompt.
  2. Read the response.
- **What good looks like:**
  - The request returns **immediately** with a task id and an events URL - it does not block until the agent finishes.
  - The response is clean, well-structured JSON a developer can parse without guesswork.
  - The task id and events URL are obviously the keys to tracking progress (next two cases).
  - An invocation is recorded on the platform side (a chat with an "api" origin) so the developer can correlate it later.
- **Watch for:** the request blocking until the run completes; an ambiguous response with no clear task handle; the events URL missing or malformed; an opaque error if the payload is slightly off rather than a helpful one.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `API-04` - Poll task status to completion [API client]
- **Customer value:** A developer who prefers simple polling can check on a running agent task and know when it's done and what it produced.
- **Priority:** High
- **Pre:** `API-03` done - a task id from a recent invocation.
- **Scenario:**
  1. GET the task status endpoint for that task id.
  2. Poll it a few times as the run progresses.
  3. Poll once more after the run has finished.
- **What good looks like:**
  - The status response clearly reports the current state and transitions sensibly: running -> completed (or failed).
  - Accumulated messages / results are available so a poller doesn't need the SSE stream to get the outcome.
  - A terminal state is unambiguous - a developer can reliably detect "done" and stop polling.
  - The shape is consistent between polls - fields don't appear and disappear.
- **Watch for:** a status that never reaches a terminal state; "completed" with no result payload; inconsistent response shapes; needing the SSE stream just to learn the final outcome.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `API-05` - Subscribe to the SSE event stream and watch progress [API client]
- **Customer value:** A developer building a responsive integration can stream the agent's progress in real time instead of polling.
- **Priority:** High
- **Pre:** `API-03` done - a task id and its events URL.
- **Scenario:**
  1. Open the events SSE endpoint for the task with the API client (`curl -N` or Postman's SSE support).
  2. Watch the events arrive as the agent works.
  3. Confirm the stream ends with a clear terminal event.
- **What good looks like:**
  - Events stream in progressively as the agent works - the developer can build a live UI on top of them.
  - Events are well-formed and meaningful (agent messages, steps/progress), not opaque blobs.
  - The stream ends with an unambiguous terminal status event so the consumer knows to close the connection.
  - Starting the stream is straightforward given just the events URL from the invoke response.
- **Watch for:** the stream emitting nothing until the very end (no real-time value); events that can't be parsed or have no useful content; the stream never signalling completion so the consumer hangs; needing undocumented headers/params to even connect.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `API-06` - Revoke a key and confirm the integration is cut off [API client]
- **Customer value:** A developer can immediately kill a leaked or retired key and trust that it stops working.
- **Priority:** High
- **Pre:** `API-01` done - a key currently working in `API-03`.
- **Scenario:**
  1. Revoke the key from the API Keys settings.
  2. Immediately retry the agent invoke request from `API-03` with the same key.
- **What good looks like:**
  - Revocation is a clear, confirmed action in the UI.
  - The revoked key stops working right away - the next API call is cleanly rejected.
  - The rejection is an honest auth error a developer can recognize and handle, not a confusing 500.
  - Other, non-revoked keys keep working.
- **Watch for:** a revoked key still authenticating; a long delay before revocation takes effect; an ambiguous error that doesn't tell the developer the key is dead.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `API-07` - The API is discoverable and the docs are usable [API client]
- **Customer value:** A developer evaluating Tesslate can integrate from the documentation alone, without reverse-engineering or asking support.
- **Priority:** Medium
- **Pre:** Access to whatever documentation the team points external developers to (API reference, guide, or in-product docs).
- **Scenario:**
  1. Starting only from the docs, work out how to create a key, invoke an agent, poll status, and consume the event stream.
  2. Copy any provided example requests into the API client and run them.
- **What good looks like:**
  - The docs cover the full loop - auth, invoke, status, events - with the correct endpoints and payload shapes.
  - Example requests are copy-pasteable and actually work against the QA environment.
  - Error responses and the once-only key behavior are documented, so a developer isn't surprised in production.
  - A competent developer could integrate in well under an hour using the docs alone.
- **Watch for:** docs that drift from the real API (wrong endpoints/fields); examples that fail when run; no mention of the events stream; key behavior or error formats left undocumented.
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
**Overall External Agent API experience (1-5) & notes:** 
