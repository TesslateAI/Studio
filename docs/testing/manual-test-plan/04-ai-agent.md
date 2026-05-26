# Suite 4 - AI Agent: Code Generation & Interaction

> See [README.md](README.md) for format, priorities, severity, environments, and accounts.

**Why this suite matters:** The AI agent **is** the product. A customer's whole reason for using Tesslate Studio is to describe software in plain language and get working code back. Everything else - the editor, preview, deployment - exists to support this loop. This is the deepest suite in the plan. Test it hard, and judge it on **outcomes** (did it build the thing, does the thing work) not just on whether the chat scrolled.

This suite has **two parts, tested separately**:

- **Part A - Interaction mechanics** (`AGENT-A##`): does the chat experience itself work - streaming, step visibility, edit modes, cancel/retry, attachments, error handling.
- **Part B - End-to-end build scenarios** (`AGENT-B##`): give the agent a real task and verify the **generated software actually runs and behaves correctly**.

**Suite prerequisites:** Tester A logged in, on a tier with enough credits for several agent runs. A project created and open in the builder (see suite 2). For Part B, the project should be startable so you can preview the agent's output (see suite 5).

---

## Part A - Interaction mechanics

### `AGENT-A1` - Send a prompt and watch the agent work
- **Customer value:** A customer types a request in plain English and sees the AI respond and act on it.
- **Priority:** Critical
- **Pre:** A project open in the builder; chat panel visible.
- **Scenario:**
  1. Type a simple request (e.g. "Add a footer with a copyright line to the home page") and send.
  2. Watch the response area from send to finish.
- **What good looks like:**
  - The response begins quickly (no long dead air before anything appears).
  - Text streams in progressively; you can read along as it works.
  - Execution steps / tool calls appear as the agent works, in order.
  - It ends with a clear summary of what was done.
- **Watch for:** long unexplained pauses; a frozen "thinking" state; the response appearing all-at-once after a long wait; no indication of progress.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-A2` - Inspect agent steps and tool calls
- **Customer value:** A customer can see *what* the agent did - which files it read, what commands it ran - and trust it.
- **Priority:** High
- **Pre:** A completed agent run from `AGENT-A1`.
- **Scenario:**
  1. Expand the step / tool-call cards in the finished response.
  2. Read the parameters and results of a few steps.
- **What good looks like:**
  - Each step shows a clear tool name, its inputs, and its result.
  - Successful vs. failed steps are visually distinct.
  - Durations are shown; long steps are explained, not mysterious.
  - Expanding/collapsing is smooth and the content is readable (not raw unformatted blobs).
- **Watch for:** cryptic tool names with no context; results truncated so badly they're useless; steps that look failed but aren't (or vice versa).
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-A3` - Ask mode: approve actions one at a time
- **Customer value:** A cautious customer wants to approve each change before the agent touches their code.
- **Priority:** High
- **Pre:** Chat edit-mode set to **ask**.
- **Scenario:**
  1. Send a request that requires writing files / running commands.
  2. When an approval prompt appears, read it, then choose "Allow once".
  3. On the next prompt, choose "Allow all".
- **What good looks like:**
  - An approval prompt appears *before* each risky action, clearly stating what will happen.
  - "Allow once" runs just that one action and pauses again at the next.
  - "Allow all" stops further prompts for the rest of the run.
  - The agent genuinely waits - it does not act before you approve.
- **Watch for:** the agent acting before approval; vague prompts that don't say what's about to happen; "Allow all" still prompting.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-A4` - Stop the agent mid-run
- **Customer value:** A customer realizes the agent is going the wrong way and wants to halt it immediately.
- **Priority:** High
- **Pre:** An agent run in progress (or an approval prompt showing).
- **Scenario:**
  1. While the agent is actively working, click Stop / Cancel.
- **What good looks like:**
  - The run halts within a few seconds.
  - Status clearly shows it was stopped by the user.
  - Work already done remains visible; the project is not left half-corrupted.
  - You can immediately send a new message.
- **Watch for:** the agent ignoring Stop and continuing; a long hang before it stops; the chat becoming unusable afterward.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-A5` - Allow mode: hands-off execution
- **Customer value:** A customer who trusts the agent wants it to just run without interruption.
- **Priority:** Medium
- **Pre:** Edit-mode set to **allow / auto**.
- **Scenario:**
  1. Send a multi-step build request.
- **What good looks like:**
  - The agent runs all tools without approval prompts.
  - Steps still display so the customer can follow along.
- **Watch for:** approval prompts still appearing in allow mode.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-A6` - Plan mode: get a plan, not changes
- **Customer value:** A customer wants the agent to think through an approach before any code is touched.
- **Priority:** Medium
- **Pre:** Edit-mode set to **plan**.
- **Scenario:**
  1. Send a substantial build request (e.g. "Add user profiles with avatars").
  2. Review the response, then check the file tree.
- **What good looks like:**
  - The agent returns a clear, structured plan.
  - **No** files were modified - the plan is proposal-only.
  - The plan is specific enough to be useful (not generic filler).
- **Watch for:** the agent executing changes in plan mode; a vague non-actionable plan.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-A7` - Multi-turn conversation keeps context
- **Customer value:** A customer iterates naturally - "now make the button blue", "actually, larger" - without re-explaining.
- **Priority:** Critical
- **Pre:** A completed first request in a chat.
- **Scenario:**
  1. Send a follow-up that refers to the previous result without restating it (e.g. "make that heading bigger").
  2. Send another follow-up referencing the new state.
- **What good looks like:**
  - The agent understands "that heading" from context and changes the right thing.
  - Each turn builds on the last; earlier work is not undone or forgotten.
- **Watch for:** the agent asking what you mean; it editing the wrong element; it rebuilding from scratch and losing prior changes.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-A8` - Undo the last exchange
- **Customer value:** A customer dislikes the last result and wants to roll the conversation back a step.
- **Priority:** Medium
- **Pre:** A chat with at least one completed exchange.
- **Scenario:**
  1. Use the undo control.
- **What good looks like:**
  - The last user+assistant pair is removed from the conversation.
  - The original prompt is offered back so it can be re-sent or edited.
- **Watch for:** undo removing too much/too little; the prompt being lost.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-A9` - Retry / regenerate a response
- **Customer value:** A customer wants a different attempt at the same request.
- **Priority:** Medium
- **Pre:** A completed agent response.
- **Scenario:**
  1. Click retry / regenerate on the last response.
- **What good looks like:**
  - The prior exchange is replaced by a fresh run of the same prompt.
  - The new result is a genuine re-attempt, not a copy.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-A10` - Attach a file or image to a prompt
- **Customer value:** A customer shares a screenshot or reference file so the agent can work from it.
- **Priority:** Medium
- **Pre:** Chat open; a sample image and a sample file ready.
- **Scenario:**
  1. Attach an image to a message (e.g. "build a page that looks like this") and send.
  2. Separately, attach a text/code file and reference it.
- **What good looks like:**
  - The attachment uploads with clear feedback.
  - The agent's response shows it genuinely used the attachment's content.
- **Watch for:** silent upload failures; the agent ignoring the attachment.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-A11` - Conversation history persists
- **Customer value:** A customer leaves and comes back, and their work-in-progress conversation is still there.
- **Priority:** High
- **Pre:** A chat with several exchanges including agent steps.
- **Scenario:**
  1. Refresh the page; then leave the project and return.
- **What good looks like:**
  - The full conversation, in order, including expandable steps, is restored.
- **Watch for:** lost messages; steps gone; ordering scrambled.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-A12` - Standalone chat sessions
- **Customer value:** A customer manages multiple separate conversations.
- **Priority:** Medium
- **Pre:** Logged in; the standalone Chat area.
- **Scenario:**
  1. Open Chat -> create a new session -> rename it -> search the session list -> delete a session.
- **What good looks like:**
  - Recent sessions are listed; create/rename/search/delete all work; deleted sessions disappear.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-A13` - Streaming survives a brief network blip
- **Customer value:** A customer on imperfect wifi doesn't lose an agent run to a momentary drop.
- **Priority:** Medium
- **Pre:** An agent task running.
- **Scenario:**
  1. Briefly toggle the network off and back on (DevTools offline toggle) mid-run.
- **What good looks like:**
  - The stream reconnects and resumes; no duplicated or lost steps.
  - If the run truly cannot recover, a clear message says so.
- **Watch for:** the run silently dying; the chat showing a permanent spinner.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-A14` - Agent error is explained, not hidden
- **Customer value:** When something goes wrong, the customer understands why and what to do.
- **Priority:** High
- **Pre:** Trigger a failure - e.g. ask for something impossible, or run while at zero credits.
- **Scenario:**
  1. Send a request that will fail.
- **What good looks like:**
  - A clear error state with a human-readable reason.
  - For out-of-credits: a clear path to upgrade / buy credits.
  - The app does not crash; you can keep chatting afterward.
- **Watch for:** raw stack traces; a silent failure with no result; the chat locking up.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-A15` - Switch agents / models
- **Customer value:** A customer picks a different agent or model for a task.
- **Priority:** Medium
- **Pre:** More than one agent/model available (install one from the marketplace if needed - suite 9).
- **Scenario:**
  1. Switch the active agent or model selector -> send a prompt.
- **What good looks like:**
  - The selection is honored; the run uses the chosen agent/model.
  - Switching is clearly reflected in the UI.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

---

## Part B - End-to-end build scenarios

> These judge the **product outcome**. After each, you must actually look at the result - open the preview, click around, verify behavior. A response that *claims* success but produces broken or missing code is a **Fail**.

### `AGENT-B1` - Build a working feature from one prompt
- **Customer value:** The core promise - describe a feature, get working software.
- **Priority:** Critical
- **Pre:** A running, previewable project.
- **Scenario:**
  1. Ask: "Add a contact page with name, email, and message fields and a Submit button."
  2. Let the agent finish; open the live preview; navigate to the new page.
- **What good looks like:**
  - The new page genuinely exists and renders in the preview.
  - All described fields and the submit button are present and interactive.
  - It is wired into the app (reachable via navigation/route), not an orphan file.
  - The agent's summary matches what was actually built.
- **Watch for:** the page missing; a broken/blank render; fields that don't work; the agent claiming success with no file change.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-B2` - Iteratively refine a feature
- **Customer value:** A customer shapes the result through conversation rather than one perfect prompt.
- **Priority:** Critical
- **Pre:** `AGENT-B1` completed.
- **Scenario:**
  1. "Make the submit button green and full-width."
  2. "Add a required-field check before submit."
  3. "Show a thank-you message after submitting."
  4. Preview after each turn.
- **What good looks like:**
  - Each change is applied correctly and visibly in the preview.
  - Earlier changes survive - nothing regresses between turns.
  - The end result is a coherent, working form.
- **Watch for:** later edits undoing earlier ones; the agent touching unrelated files; the preview not reflecting changes.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-B3` - Fix a bug the agent is told about
- **Customer value:** A customer reports a problem in plain language and the agent repairs it.
- **Priority:** Critical
- **Pre:** A project with a known/introduced bug (e.g. a button that does nothing, or a console error).
- **Scenario:**
  1. Describe the bug: "The Submit button doesn't do anything when clicked - fix it."
  2. Let the agent investigate and fix; re-test in the preview.
- **What good looks like:**
  - The agent inspects the relevant code (visible in its steps) before changing it.
  - The bug is actually gone when you retest.
  - The fix is targeted - it doesn't rewrite unrelated parts.
- **Watch for:** a "fix" that doesn't fix anything; the agent breaking something else; a fix with no investigation.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-B4` - Multi-file feature
- **Customer value:** Real features span several files; the agent must change them coherently.
- **Priority:** High
- **Pre:** A running project.
- **Scenario:**
  1. Ask for something that needs multiple files - e.g. "Add a reusable Card component and use it on the home page in a 3-column grid."
  2. Inspect the file tree and the preview.
- **What good looks like:**
  - Multiple files are created/edited consistently (the component file *and* its usage).
  - Imports/paths line up; the feature renders correctly.
- **Watch for:** a component created but never used; broken imports; only one of several files changed.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-B5` - Install a dependency and use it
- **Customer value:** A customer asks for functionality that needs a library, and the agent handles the whole thing.
- **Priority:** High
- **Pre:** A running project.
- **Scenario:**
  1. Ask for something requiring a package - e.g. "Add a date picker to the form using a popular library."
  2. Watch the agent install the dependency and wire it in; restart/preview as needed.
- **What good looks like:**
  - The agent installs the package (visible in its steps) and the app still builds.
  - The new functionality works in the preview.
- **Watch for:** install failures left unhandled; the app failing to start after the change; the feature half-wired.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-B6` - Build from a fresh/empty project
- **Customer value:** A customer starts from nothing and gets a real app.
- **Priority:** High
- **Pre:** A brand-new empty project.
- **Scenario:**
  1. Ask the agent to scaffold a small app - e.g. "Build a simple to-do list app where I can add, check off, and delete items."
  2. Let it set up the project; start it; use the app in the preview.
- **What good looks like:**
  - The agent scaffolds a sensible project structure.
  - The app starts and the described features all work end to end.
- **Watch for:** a project that won't start; features that look present but don't function; the agent stalling on setup.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-B7` - Agent uses an attached design reference
- **Customer value:** A customer hands the agent a screenshot/mockup and gets something resembling it.
- **Priority:** Medium
- **Pre:** A running project; an image of a simple UI.
- **Scenario:**
  1. Attach the image: "Build a landing page hero section like this."
  2. Compare the preview to the reference.
- **What good looks like:**
  - The result clearly reflects the reference (layout, structure, intent).
  - It renders correctly in the preview.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-B8` - Agent recovers from its own mistake
- **Customer value:** When the agent breaks the build, it should notice and self-correct.
- **Priority:** High
- **Pre:** A running project.
- **Scenario:**
  1. Give a moderately complex request likely to need a couple of attempts (e.g. "Add client-side routing with three pages and a nav bar").
  2. Observe whether the agent catches and fixes errors during the run.
- **What good looks like:**
  - If a step fails (build error, bad import), the agent detects it and corrects course.
  - The final state is a working app, not a broken one left for the customer.
- **Watch for:** the agent declaring success on a broken build; errors ignored; the customer left to fix it.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-B9` - Agent works with a skill or MCP connector
- **Customer value:** An agent extended with a skill/connector can do more for the customer.
- **Priority:** Medium
- **Pre:** An agent that has a skill assigned or an MCP connector configured (see suite 9).
- **Scenario:**
  1. Send a request that should trigger the skill / connector capability.
- **What good looks like:**
  - The agent uses the extended capability (visible in its steps).
  - The result reflects that capability working.
- **Watch for:** the skill/connector being silently ignored; connector errors with no explanation.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-B10` - Large / longer task stays coherent
- **Customer value:** Bigger asks shouldn't make the agent lose the plot.
- **Priority:** Medium
- **Pre:** A running project.
- **Scenario:**
  1. Give a larger task - e.g. "Add a dashboard page with three stat cards, a chart, and a recent-activity list."
  2. Let it run to completion; review the result thoroughly.
- **What good looks like:**
  - All requested pieces are delivered, not just the first few.
  - The result is coherent and the app still works.
  - Progress feedback is steady throughout a long run.
- **Watch for:** the agent stopping partway; only part of the request delivered; the run timing out with no recovery.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `AGENT-B11` - Generated code quality spot-check
- **Customer value:** The customer may read or maintain the code; it should be reasonable.
- **Priority:** Medium
- **Pre:** Output from any earlier Part-B case.
- **Scenario:**
  1. Open a few of the agent-generated/edited files in the editor and read them.
- **What good looks like:**
  - Code is readable, consistent with the rest of the project, and free of obvious dead code or leftover debug junk.
  - No secrets or placeholder garbage left in.
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
**Overall agent experience (1-5) & notes:** 
