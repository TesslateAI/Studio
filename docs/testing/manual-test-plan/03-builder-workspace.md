# Suite 3 - Builder workspace

> See [README.md](README.md) for format, priorities, severity, environments, and accounts.

**Why this suite matters:** The builder workspace is where a customer spends most of their time - it is the IDE inside Tesslate Studio. Even though the AI agent writes most of the code, the customer still needs to read it, tweak it, organize files, and watch what the agent changes. A workspace that loads slowly, mangles a file on save, scrambles tabs, or hides the agent's edits makes the whole product feel untrustworthy. This suite judges the workspace on **craft**: does the editor feel solid and fast, do file operations behave predictably, can the customer move confidently between the code, architecture, preview, and design views, and does the editor stay honest when the agent is changing things underneath it.

**Suite prerequisites:** Tester A logged in. A project open in the builder with a real file tree (a template or imported repo - not an empty project). For the agent-edit case, the project should be able to run an agent task (suite 4). Keep DevTools open and note any errors during file operations.

---

### `BUILD-01` - File tree loads and navigates
- **Customer value:** A customer can see and move around their whole project's file structure at a glance.
- **Priority:** Critical
- **Pre:** A project with a real folder/file structure open in the builder.
- **Scenario:**
  1. Open the workspace and look at the file tree.
  2. Expand and collapse a few folders; scroll through the tree.
  3. Click into nested files.
- **What good looks like:**
  - The full hierarchy of folders and files renders quickly and completely.
  - Expand/collapse is instant and smooth; folder icons make structure clear.
  - The tree matches the project's actual files - nothing missing or phantom.
  - Navigating deep folders is comfortable, with no lag or jumpiness.
- **Watch for:** a slow or partial tree; missing files; folders that won't expand; the tree resetting its scroll/expansion state unexpectedly.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BUILD-02` - Open a file in the editor
- **Customer value:** A customer can open any file and read it comfortably with proper code formatting.
- **Priority:** Critical
- **Pre:** `BUILD-01`; a project with files of a few languages (e.g. JS/TS, CSS, JSON, Markdown).
- **Scenario:**
  1. Click a code file in the tree.
  2. Open files of different types in turn.
- **What good looks like:**
  - Files open quickly in the Monaco editor.
  - Syntax highlighting is correct for each language; line numbers are visible.
  - The content matches the file exactly - no truncation or encoding garbage.
  - The editor feels responsive - scrolling and cursor movement are smooth.
- **Watch for:** wrong or missing syntax highlighting; slow opens; garbled characters; the editor freezing on a particular file type.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BUILD-03` - Edit and save a file
- **Customer value:** A customer can make a change by hand and trust it is saved correctly.
- **Priority:** Critical
- **Pre:** A file open in the editor.
- **Scenario:**
  1. Type some changes into the file.
  2. Save (Ctrl/Cmd+S).
  3. Close and reopen the file; refresh the page and open it again.
- **What good looks like:**
  - There is a clear unsaved-changes indicator that clears on save.
  - Saving gives obvious confirmation and is fast.
  - Reopening the file - and reopening after a refresh - shows exactly the saved content.
  - No edits are silently lost or partially written.
- **Watch for:** changes not persisting; the unsaved indicator never clearing; a save that appears to work but reverts on refresh; corruption of the file.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BUILD-04` - Create, rename, and delete files and folders
- **Customer value:** A customer can organize their project - add new files, restructure folders, remove what they don't need.
- **Priority:** High
- **Pre:** A project workspace open.
- **Scenario:**
  1. Create a new file in a folder and a new folder.
  2. Add a file inside the new folder.
  3. Rename a file and rename a folder that contains files.
  4. Delete a disposable file, then a disposable folder.
- **What good looks like:**
  - New files/folders appear immediately in the tree in the right place; a new file opens ready to edit.
  - Renaming updates the tree and any open tabs; renaming a folder carries its contents along.
  - Deletion asks for confirmation and removes the item (and a folder's contents) cleanly.
  - Invalid or duplicate names are handled with a clear message, not a silent failure.
- **Watch for:** items appearing in the wrong place; a folder rename losing or orphaning its files; open tabs pointing at stale paths after a rename; deletion with no confirmation.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BUILD-05` - Work with multiple file tabs
- **Customer value:** A customer can have several files open at once and move between them naturally, the way they would in any code editor.
- **Priority:** Medium
- **Pre:** A project with several files.
- **Scenario:**
  1. Open three or more files so each gets a tab.
  2. Switch between tabs; scroll and move the cursor in each.
  3. Make an unsaved edit in one tab, then try to close it.
  4. Close other tabs.
- **What good looks like:**
  - Each file opens in its own clearly labelled tab.
  - Switching tabs preserves each file's scroll position and cursor.
  - Closing a tab with unsaved changes warns before discarding.
  - Tabs feel stable - no flicker, no reordering on their own.
- **Watch for:** tabs scrambling order; losing scroll/cursor state on switch; closing an unsaved tab with no warning; the wrong file showing under a tab.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BUILD-06` - Find and replace within a file
- **Customer value:** A customer can quickly locate and bulk-change text in a file without hunting line by line.
- **Priority:** Medium
- **Pre:** A file with repeated text open.
- **Scenario:**
  1. Open find (Ctrl/Cmd+F) and search for a term - step through matches.
  2. Open replace (Ctrl/Cmd+H) and replace a term, then replace-all.
  3. Try a regex search.
- **What good looks like:**
  - All matches are highlighted; you can jump between them; a match count shows.
  - Replace and replace-all change exactly the intended text.
  - Regex mode works for a basic pattern.
  - After a replace, the file can be saved and the change persists.
- **Watch for:** missed or wrong matches; replace-all changing too much; regex mode erroring; the editor lagging on a large file.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BUILD-07` - Diff view shows what changed
- **Customer value:** A customer can see exactly what changed in a file - their own edits or the agent's - before trusting it.
- **Priority:** Medium
- **Pre:** A file with saved changes or git history.
- **Scenario:**
  1. Open the diff / compare view for a changed file.
  2. Read the additions and deletions.
- **What good looks like:**
  - A clear side-by-side (or inline) comparison of before and after.
  - Additions and deletions are visually distinct and easy to read.
  - Unchanged regions stay out of the way; the actual change is easy to find.
  - The diff accurately reflects the real change.
- **Watch for:** a misleading or empty diff; additions/deletions hard to tell apart; the diff not matching the actual file change; the view being slow or broken.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BUILD-08` - Switch between workspace views
- **Customer value:** A customer can move between the code editor, the architecture map, the live preview, and the design view to work the way they want.
- **Priority:** High
- **Pre:** A project open in the builder with multiple views available.
- **Scenario:**
  1. Switch from the code view to the architecture view, then to preview, then to the design view.
  2. Return to the code view.
- **What good looks like:**
  - Each view is clearly labelled and one click away.
  - Switching is fast; each view loads its real content, not a stale or blank panel.
  - Returning to the code view restores your open files and editor state.
  - The transition feels deliberate - no jarring layout jumps.
- **Watch for:** a view loading blank or stale; losing your editor state when you come back; a missing/broken view; slow or janky transitions.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BUILD-09` - Editor reflects the agent's changes
- **Customer value:** When the AI agent edits a file, the customer sees the up-to-date result in the editor - the workspace and the agent stay in sync.
- **Priority:** High
- **Pre:** A project open; a file open in the editor that the agent will modify; able to run an agent task (suite 4).
- **Scenario:**
  1. Open a file in the editor.
  2. Ask the agent to modify that same file (and to create a new one).
  3. After the agent finishes, look at the editor and the file tree.
- **What good looks like:**
  - The editor shows the agent's new version of the open file (refreshing if needed), without corruption.
  - Newly created files appear in the tree.
  - The content the agent reported writing matches what the editor shows.
  - There is no confusing mix of stale and fresh content.
- **Watch for:** the editor stuck on the pre-agent version; the tree not showing new files; a conflict prompt overwriting agent work with stale content; corrupted or duplicated content.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BUILD-10` - Large file handling
- **Customer value:** A customer can open a big file without the workspace freezing.
- **Priority:** Low
- **Pre:** A project containing a large file (e.g. 1000+ lines, or a few MB), or create one.
- **Scenario:**
  1. Open the large file.
  2. Scroll through it and make a small edit.
- **What good looks like:**
  - The editor stays responsive while scrolling and editing.
  - An extremely large file shows a clear "file too large to display" message rather than hanging the browser.
- **Watch for:** the tab or browser freezing; an indefinite spinner; the workspace becoming unresponsive.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BUILD-11` - Workspace layout holds up
- **Customer value:** A customer gets a workspace that stays usable and well-proportioned as they resize panels or their window.
- **Priority:** Medium
- **Pre:** A project open in the builder.
- **Scenario:**
  1. Resize the editor, chat, and preview panels by dragging the dividers.
  2. Resize the browser window narrower and wider.
  3. Collapse and reopen a panel if the UI allows it.
- **What good looks like:**
  - Panels resize smoothly and remember sensible proportions.
  - At narrower widths the layout adapts gracefully - nothing is cut off or overlapping.
  - Collapsing and reopening panels works cleanly.
  - The workspace stays usable throughout - no element becomes unreachable.
- **Watch for:** panels that won't resize or snap weirdly; content clipped or overlapping at smaller sizes; controls becoming unreachable; the layout not surviving a refresh.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `BUILD-12` - Workspace state persists across a refresh
- **Customer value:** A customer who refreshes or steps away comes back to the workspace roughly where they left it, not reset to zero.
- **Priority:** Medium
- **Pre:** A project open with a few files open and a view selected.
- **Scenario:**
  1. Open several files, select a non-default view, scroll within a file.
  2. Refresh the page.
  3. Leave the project and return to it.
- **What good looks like:**
  - After a refresh the workspace reloads cleanly into a usable state.
  - Open files (or at least the project context) are restored sensibly - you are not dumped into a blank workspace.
  - Returning to the project is fast and lands you back in a working state.
  - No unsaved work is silently lost beyond what you'd reasonably expect.
- **Watch for:** every tab closed and the tree collapsed after a refresh; a slow cold reload each time; an error on returning to the project; losing unsaved edits without warning.
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
**Overall workspace experience (1-5) & notes:** 
