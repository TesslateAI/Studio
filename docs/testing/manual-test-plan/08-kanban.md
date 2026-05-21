# Suite 8 - Kanban

> See [README.md](README.md) for format, priorities, severity, environments, and accounts.

**Why this suite matters:** Building software is not just typing prompts - it's deciding what to build next. The Kanban board is where a customer plans their project, tracks what's done, and stays organized across many agent sessions. Its real differentiator is that the AI agent is a board citizen too: the agent can read the board, pick up tasks, move them as it works, and reference them by number (TSK-0001). That turns the board from a static to-do list into a shared workspace between the human and the agent. The board only works if it's frictionless - instant drag, tasks that don't get lost, reference numbers that stay stable - and if the agent's updates show up faithfully alongside the customer's.

**Suite prerequisites:** Tester A logged in. A project open in the builder (see suite 2). For the agent case (`KANBAN-10`), the project's agent must have the Kanban capability available and enough credits for a run.

---

### `KANBAN-01` - Board auto-creates with default columns
- **Customer value:** A customer gets a ready-to-use planning board the first time they open it - no setup ceremony.
- **Priority:** High
- **Pre:** A project that has never had its Kanban view opened.
- **Scenario:**
  1. Open the project's Kanban / board view for the first time.
- **What good looks like:**
  - A board appears immediately, already populated with sensible default columns (e.g. Backlog, To Do, In Progress, Review, Done).
  - The columns are in a logical left-to-right workflow order.
  - The board is empty of tasks but clearly ready to accept them - there's an obvious way to add the first task.
  - No error, no "create a board" wizard to slog through.
- **Watch for:** a blank screen or error on first open; columns in a nonsensical order; the customer forced through a setup step before they can use the board.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `KANBAN-02` - Create a task with an auto reference number
- **Customer value:** A customer captures a piece of work and gets a stable handle for it.
- **Priority:** High
- **Pre:** `KANBAN-01`.
- **Scenario:**
  1. Add a task to a column - give it a title and a description.
  2. Note the reference number assigned.
  3. Create two more tasks.
- **What good looks like:**
  - The task is created and lands in the column you added it to.
  - It is assigned a readable, auto-incrementing reference number (e.g. TSK-0001, then TSK-0002, TSK-0003).
  - Reference numbers are unique and don't reuse old numbers.
  - The card shows the title and the reference clearly.
- **Watch for:** no reference number assigned; duplicate or skipped numbers; the task landing in the wrong column; the title/description not saving.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `KANBAN-03` - Edit a task's fields
- **Customer value:** A customer fleshes out a task with the detail they need to track it properly.
- **Priority:** Medium
- **Pre:** A task exists (`KANBAN-02`).
- **Scenario:**
  1. Open a task's detail view.
  2. Set or change its priority, assignee, estimate, tags, and due date.
  3. Save, close, and reopen the task.
- **What good looks like:**
  - Every field is editable and the controls are clear (priority picker, assignee selector, date picker, tag input).
  - All changes persist - reopening the task shows the saved values, and they survive a page refresh.
  - The card on the board reflects the key fields (e.g. priority colour, assignee avatar, due date) without opening it.
- **Watch for:** a field that silently doesn't save; the assignee list missing real project members; the due date shifting by a day (timezone bug); card not reflecting edits.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `KANBAN-04` - Move a task between columns by drag
- **Customer value:** A customer advances work by dragging a card across the board, the way a Kanban board is meant to work.
- **Priority:** High
- **Pre:** A task exists.
- **Scenario:**
  1. Drag a task card from one column to another (e.g. To Do -> In Progress).
  2. Refresh the page.
- **What good looks like:**
  - The drag feels responsive - the card follows the cursor and the drop target is clearly indicated.
  - The card lands in the new column and stays there.
  - The move persists after a refresh - the board is not just a local illusion.
- **Watch for:** laggy or stuttering drag; the card snapping back to the original column; the move lost on refresh; the card duplicated.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `KANBAN-05` - Reorder tasks within a column
- **Customer value:** A customer prioritizes within a column by ordering cards top to bottom.
- **Priority:** Medium
- **Pre:** A column with several tasks.
- **Scenario:**
  1. Drag tasks up and down within one column to a deliberate order.
  2. Refresh the page.
- **What good looks like:**
  - Cards reorder smoothly; the insertion point is clear while dragging.
  - The new order persists after a refresh.
  - Other columns are unaffected.
- **Watch for:** order not sticking; cards jumping to unexpected positions; a reorder accidentally moving a card to another column.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `KANBAN-06` - Create a custom column
- **Customer value:** A customer shapes the board to their own workflow, not just the defaults.
- **Priority:** Medium
- **Pre:** `KANBAN-01`.
- **Scenario:**
  1. Add a new column - give it a name, and a colour/icon if offered.
  2. Add a task to the new column, then drag an existing task into it.
- **What good looks like:**
  - The new column appears on the board where expected.
  - It fully behaves like a built-in column - accepts new tasks and dropped tasks.
  - The name and styling are applied and persist.
- **Watch for:** the column appearing but not accepting tasks; styling/name not saving; the column added in a confusing position with no way to move it.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `KANBAN-07` - Reorder columns
- **Customer value:** A customer arranges the workflow stages in the order that matches how they actually work.
- **Priority:** Low
- **Pre:** Several columns exist, including a custom one.
- **Scenario:**
  1. Drag columns to a new left-to-right order.
  2. Refresh the page.
- **What good looks like:**
  - Columns drag and drop into a new order smoothly.
  - The new order persists after a refresh.
  - Tasks stay with their columns through the reorder.
- **Watch for:** columns not draggable; order lost on refresh; tasks getting detached from their column during the move.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `KANBAN-08` - Delete a column
- **Customer value:** A customer removes a stage they no longer need, with a clear understanding of what happens to its tasks.
- **Priority:** Medium
- **Pre:** A disposable custom column that contains a task or two.
- **Scenario:**
  1. Delete the column.
- **What good looks like:**
  - A confirmation makes clear what will happen to the tasks in that column (removed, or moved elsewhere).
  - After confirming, the column is removed cleanly.
  - The outcome for the tasks matches what the confirmation said - no surprise data loss.
- **Watch for:** no confirmation before deleting a column full of tasks; tasks silently vanishing with no warning; the column reappearing on refresh.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `KANBAN-09` - Task comments
- **Customer value:** A customer keeps a running discussion or notes on a task in one place.
- **Priority:** Medium
- **Pre:** A task exists.
- **Scenario:**
  1. Open a task and add a comment.
  2. Add a second comment.
  3. Close and reopen the task.
- **What good looks like:**
  - Comments are saved and shown in order, each with an author and a timestamp.
  - They persist after closing/reopening the task and after a refresh.
  - The comment thread is readable and clearly separated from the task description.
- **Watch for:** comments lost on reopen; missing author/timestamp; comments appearing out of order; no way to tell a comment from the description.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `KANBAN-10` - WIP / task limit on a column
- **Customer value:** A customer who wants to avoid overload sets a limit and gets a visible signal when a column is too full.
- **Priority:** Low
- **Pre:** A column with a WIP / task limit configured (e.g. limit 3).
- **Scenario:**
  1. Add or move tasks into that column until you reach and then exceed the limit.
- **What good looks like:**
  - As the column fills, the count toward the limit is visible.
  - At/over the limit the board signals it clearly - a warning state or a block, consistent with how it's designed.
  - The signal is honest: it doesn't warn early or stay silent past the limit.
- **Watch for:** the limit having no visible effect; the column blocking when it should only warn (or vice versa); a confusing/unexplained block.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `KANBAN-11` - The agent updates the board
- **Customer value:** The AI agent works the same board the customer does - picking up, creating, and advancing tasks as it builds.
- **Priority:** Medium
- **Pre:** A project with a Kanban board and a task or two; the project's agent has the Kanban capability and enough credits.
- **Scenario:**
  1. Ask the agent, in chat, to create a new task on the board (e.g. "add a task to the board for adding dark mode").
  2. Then ask it to move an existing task by its reference number (e.g. "move TSK-0002 to In Progress").
  3. Open the board after each.
- **What good looks like:**
  - The agent creates the task and it appears on the board with its own reference number, indistinguishable from a human-made task.
  - The agent correctly resolves the TSK reference and moves the right task to the right column.
  - The board reflects the agent's changes without needing a manual refresh dance, and the agent's chat summary matches what actually happened on the board.
  - Human-created and agent-created tasks coexist cleanly.
- **Watch for:** the agent claiming a board change that didn't happen; the wrong task moved; the agent misreading the TSK reference; board changes only visible after a hard reload; the agent corrupting existing tasks.
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
**Overall Kanban experience (1-5) & notes:** 
