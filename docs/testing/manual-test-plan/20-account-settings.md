# Suite 20 - Account, settings & appearance

> See [README.md](README.md) for format, priorities, severity, environments, and accounts.

**Why this suite matters:** Settings are the small promises a product makes to a customer: "this is your name, your look, your connected accounts, and we'll remember them." When these break, the damage isn't dramatic - it's erosion of trust. A theme that applies on one page but not another, a preference that resets on refresh, a notification that fires three times, a connected GitHub account that quietly stops working - each one tells the customer the product is sloppy. This is a deliberately **light, experience-focused** suite: it checks that personalization, account connections, and notifications genuinely *stick* and *feel polished*.

**Suite prerequisites:** Tester A logged in. A sample avatar image ready. For the Git provider case, access to a GitHub (or other supported provider) account. For BYOK, ideally access to both a free-tier and a paid-tier account. For notifications, browser notification permission can be granted when prompted.

---

### `ACCOUNT-01` - View and edit the profile
- **Customer value:** A customer keeps their identity on the platform accurate - their name, bio, and how they're represented.
- **Priority:** Medium
- **Pre:** Tester A logged in; Settings -> Profile.
- **Scenario:**
  1. Edit the display name, username, bio, and any social links.
  2. Save.
  3. Navigate elsewhere (dashboard, a project, the marketplace) and look for the name/username.
- **What good looks like:**
  - The edits save with clear confirmation and persist after a refresh.
  - The updated name/username shows consistently wherever the customer is represented.
  - Social links are stored and rendered as working links.
- **Watch for:** changes silently not saving; the name updating in settings but stale elsewhere; a taken/invalid username rejected with no clear explanation of what's allowed.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ACCOUNT-02` - Upload an avatar
- **Customer value:** A customer puts a face (or logo) on their account so they're recognizable.
- **Priority:** Medium
- **Pre:** `ACCOUNT-01`; an image file ready.
- **Scenario:**
  1. Upload an avatar image.
  2. After it saves, check the avatar in the nav, profile, and anywhere the user appears.
- **What good looks like:**
  - The upload gives clear feedback and the new avatar appears everywhere quickly.
  - The image is cropped/scaled cleanly - not stretched, squished, or pixelated.
  - An oversized or unsupported file is rejected with a clear, friendly message about limits.
- **Watch for:** the avatar updating in one place but not another; a broken image icon; a silent failure on a too-large file.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ACCOUNT-03` - Set a creator handle
- **Customer value:** A customer who wants to publish marketplace items or Apps claims their public creator identity.
- **Priority:** Medium
- **Pre:** Tester A logged in.
- **Scenario:**
  1. Set a creator handle in settings.
  2. Save and confirm where the handle appears (e.g. App runtime URLs, creator profile).
- **What good looks like:**
  - The handle saves and is shown as the customer's public creator identity.
  - A reserved or already-taken handle is rejected with a clear reason and the customer can pick another.
  - Format rules (allowed characters) are communicated rather than just failing.
- **Watch for:** a cryptic error on an invalid handle; the handle saving but not actually used anywhere; no feedback on success.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ACCOUNT-04` - Change the theme preset
- **Customer value:** A customer picks the look of the product that suits them.
- **Priority:** Medium
- **Pre:** Settings -> Preferences.
- **Scenario:**
  1. Open the theme picker and select a different preset.
  2. Watch the UI; then refresh the page.
- **What good looks like:**
  - The UI re-themes immediately on selection - no need to reload.
  - The theme picker shows a meaningful preview of each option.
  - The choice persists after a refresh and after logging out and back in.
- **Watch for:** the theme reverting on refresh; a flash of the old theme; a preset that looks broken when applied.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ACCOUNT-05` - Toggle dark / light mode
- **Customer value:** A customer matches the product to their environment or eyes.
- **Priority:** Medium
- **Pre:** Preferences open.
- **Scenario:**
  1. Toggle between dark and light mode.
  2. Inspect text, buttons, and panels in the new mode; refresh.
- **What good looks like:**
  - The mode switches cleanly and the choice persists.
  - In both modes text is readable and controls are clearly visible - no invisible or washed-out text.
- **Watch for:** low-contrast or unreadable text in one mode; mixed mode (some panels dark, some light); the toggle not persisting.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ACCOUNT-06` - Workspace preferences (chat position & diagram model)
- **Customer value:** A customer tailors the builder layout and AI behavior to how they like to work.
- **Priority:** Low
- **Pre:** Preferences open.
- **Scenario:**
  1. Change the chat panel position (left / center / right) and save.
  2. Open a project's builder and confirm the chat panel is where you set it.
  3. Change the diagram/model preference and save.
- **What good looks like:**
  - The chat panel appears in the chosen position in the builder and stays there after a refresh.
  - The diagram model preference saves and is honored when diagrams are generated.
  - Each preference is clearly labeled so the customer knows what it does.
- **Watch for:** the chat position not actually moving the panel; the preference resetting; the diagram setting having no visible effect.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ACCOUNT-07` - Connect and disconnect a Git provider
- **Customer value:** A customer connects GitHub so they can import their private repositories and deploy from them.
- **Priority:** High
- **Pre:** Settings -> Connections; a GitHub (or supported provider) account.
- **Scenario:**
  1. Connect the Git provider via OAuth.
  2. Confirm the account shows as linked.
  3. (Optionally) verify it works by importing a private repo (see suite 2).
  4. Disconnect the provider.
- **What good looks like:**
  - The OAuth flow completes smoothly and returns you to the connections page with the account clearly shown as linked (account name visible).
  - While connected, private-repo import/deploy works.
  - Disconnecting cleanly removes the link; the product won't let you disconnect your only login method if that would lock you out.
- **Watch for:** the OAuth flow dead-ending or not reflecting the connection; the link showing connected but private imports still failing; a token leaking into a URL or error message.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ACCOUNT-08` - Add a BYOK provider key (and the paid-tier gate)
- **Customer value:** A customer on a paid plan brings their own LLM provider key; a free customer sees a clear upgrade nudge.
- **Priority:** High
- **Pre:** Access to a paid-tier account and, ideally, a free-tier account; a provider API key (e.g. OpenAI/Anthropic).
- **Scenario:**
  1. On a **free-tier** account, go to add a BYOK key.
  2. On a **paid-tier** account, add a provider key and save.
- **What good looks like:**
  - On the free tier, BYOK is clearly gated with an inviting upgrade prompt - it explains *why* and feels like an offer, not a blunt "no".
  - On a paid tier, the key saves; only a masked preview is shown afterward; it can be revoked.
  - The gating is a smooth UX moment, not a confusing error.
- **Watch for:** the free-tier gate showing as a raw error or a dead button; the full key being shown back after saving; no way to revoke a saved key.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ACCOUNT-09` - Theme applies consistently across the product
- **Customer value:** A customer who picked a look expects the *whole* product to honor it, not just the page they set it on.
- **Priority:** Medium
- **Pre:** A non-default theme selected (from `ACCOUNT-04`).
- **Scenario:**
  1. With a distinctive theme active, walk through the dashboard, a project builder (editor + chat + preview), the marketplace, and settings.
  2. Open a few modals, panels, and dropdowns along the way.
- **What good looks like:**
  - Colors, surfaces, borders, and typography are consistent on every page and in every modal/panel.
  - Nothing renders with default/unstyled colors as you move around.
  - Transitions and hover states feel coherent with the theme - polished, not janky.
- **Watch for:** one page or modal stuck on the default theme; mismatched borders/backgrounds; a flash of unstyled content on navigation.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ACCOUNT-10` - In-app notification on agent completion
- **Customer value:** A customer working in the app gets a gentle confirmation the moment a long agent task finishes.
- **Priority:** Medium
- **Pre:** A project open and focused; an agent task that will take a little while.
- **Scenario:**
  1. Start an agent task and keep the app tab focused.
  2. Wait for the task to finish.
- **What good looks like:**
  - An in-app toast or indicator reports completion clearly, naming what finished.
  - It appears once, is readable, and dismisses cleanly - it doesn't pile up or block the UI.
- **Watch for:** no completion signal at all; the toast firing repeatedly; a toast that covers something important and won't dismiss.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `ACCOUNT-11` - Browser push and approval notifications when away
- **Customer value:** A customer who tabs away (or steps out) is pulled back when the agent finishes or needs their approval - so they don't have to babysit it.
- **Priority:** Medium
- **Pre:** Browser notification permission granted; an agent task ready to run; for the approval part, the chat edit-mode set to **ask**.
- **Scenario:**
  1. Start an agent task, then switch to a different browser tab or app so the Tesslate tab is unfocused.
  2. When the task finishes, observe whether a browser push notification fires.
  3. Repeat with an ask-mode task that hits an approval gate while the tab is unfocused.
  4. Then bring the tab back to focus and run another task - confirm you get the in-app toast, not a duplicate push.
- **What good looks like:**
  - A browser push notification fires when the task completes while the tab is unfocused.
  - An approval-required notification fires when the agent is waiting on the customer.
  - When the tab is focused, the in-app toast is used instead - the customer never gets the *same* event twice (no duplicate push + toast).
  - Notifications are clear about which project/task they refer to.
- **Watch for:** no push when away; duplicate notifications for one event; a push firing even though the tab was focused; vague notifications with no project context.
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
**Overall account & settings experience (1-5) & notes:** 
