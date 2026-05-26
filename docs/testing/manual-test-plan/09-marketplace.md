# Suite 9 - Marketplace: Discover & Install

> See [README.md](README.md) for format, priorities, severity, environments, and accounts.

**Why this suite matters:** The marketplace is how a customer makes the product *theirs* - they extend the AI agent with specialist skills, plug in connectors to Slack/Linear/GitHub, start projects from ready-made bases, and reskin everything with a theme. A customer's first marketplace win ("I installed a better agent and it just worked in my project") is a major retention moment. This suite judges the **discover -> install -> it actually works** loop, not just whether catalog pages render. An item that installs but never shows up where it's supposed to, or a connector that "connects" but can't list a single tool, is a **Fail**.

**Suite prerequisites:** Tester A logged in, on a tier with credits. At least one project created and open in the builder (suite 2). For the paid-item case, Stripe test mode and card `4242 4242 4242 4242`. For the OAuth MCP case, an account with the connector's provider (e.g. a GitHub or Linear account).

---

### `MARKET-01` - Browse the marketplace as a logged-in customer
- **Customer value:** A customer opens the marketplace and immediately sees useful things to add to their workflow.
- **Priority:** High
- **Pre:** Tester A logged in.
- **Scenario:**
  1. Open the Marketplace from the main navigation.
  2. Scan the landing view - featured carousels, categories, recommended items.
  3. Scroll through a category list.
- **What good looks like:**
  - Items load quickly with a name, creator, icon, and a rating or install count.
  - Featured carousels and categories are populated, not empty placeholders.
  - The page communicates *what each item is for* - a customer can tell an agent from a skill from a connector at a glance.
  - Scrolling and paging stay smooth with many items on screen.
- **Watch for:** broken/missing icons; "0 items" categories; a wall of undifferentiated cards; long blank loading with no skeleton.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `MARKET-02` - Public marketplace browse (logged out)
- **Customer value:** A prospective customer can evaluate the marketplace before signing up - a key part of the buying decision.
- **Priority:** High
- **Pre:** Logged out (use a fresh browser profile or incognito).
- **Scenario:**
  1. Open the marketplace URL directly without logging in.
  2. Browse categories, search, and open an item detail page.
  3. Click Install / Get on an item.
- **What good looks like:**
  - The catalog browses fully without a login wall - search, filter, and detail pages all work.
  - Item detail pages show the full description and creator info to an anonymous visitor.
  - Clicking Install cleanly prompts sign-in / sign-up, then returns the visitor to where they were.
- **Watch for:** the whole page redirecting to login; broken images for anonymous users; the install prompt losing the customer's place after they sign in.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `MARKET-03` - Browse each item type
- **Customer value:** A customer knows the marketplace offers more than agents - skills, connectors, starter bases, and themes - and can browse each.
- **Priority:** Medium
- **Pre:** Marketplace open.
- **Scenario:**
  1. Open each browse type in turn: **agents**, **skills**, **MCP servers / connectors**, **bases**, **themes**.
  2. Page through each list.
- **What good looks like:**
  - Each type has its own populated listing with items relevant to that type.
  - The card layout suits the type (e.g. themes show a visual preview; bases describe their stack).
  - Pagination or infinite scroll works without duplicating or dropping items.
- **Watch for:** an empty type with no friendly explanation; one type's cards rendering with another type's fields; pagination resetting your scroll.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `MARKET-04` - Install a free marketplace agent
- **Customer value:** The core marketplace promise - a customer finds a better agent and adds it to their project in seconds.
- **Priority:** Critical
- **Pre:** Tester A logged in; at least one project exists.
- **Scenario:**
  1. Find a free agent in the marketplace and open its detail page.
  2. Click Install; pick the target project (or projects).
  3. Confirm, then open that project's builder.
  4. Open the agent/model selector in the chat panel.
- **What good looks like:**
  - Install completes quickly with clear confirmation - no ambiguous spinner.
  - The newly installed agent appears in the project's agent selector.
  - The agent also shows up in your Library as installed.
  - Selecting the new agent and sending a prompt actually runs *that* agent.
- **Watch for:** install "succeeds" but the agent is nowhere in the project; the agent appears but can't be selected; needing a full page reload before it shows up.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `MARKET-05` - Search, filter, and sort the catalog
- **Customer value:** A customer with a specific need ("a connector for Notion") can find it fast instead of scrolling endlessly.
- **Priority:** Medium
- **Pre:** Marketplace open with enough items to make search meaningful.
- **Scenario:**
  1. Search a keyword you expect to match (e.g. an item name or "github").
  2. Apply a category filter.
  3. Change the sort order - newest, most installed, top rated.
  4. Search a nonsense string that matches nothing.
- **What good looks like:**
  - Search returns relevant results quickly and updates as you refine.
  - Filters genuinely narrow the list; combining filter + search works together.
  - Each sort order visibly reorders the results in the expected direction.
  - A no-match search shows a friendly empty state with a way back, not a blank page or error.
- **Watch for:** stale results from a previous query; filters that do nothing; sort that doesn't change order; an empty state that looks like a crash.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `MARKET-06` - Item detail page tells the full story
- **Customer value:** Before installing, a customer wants to understand exactly what an item does and whether to trust it.
- **Priority:** Medium
- **Pre:** Marketplace open.
- **Scenario:**
  1. Open the detail page for an agent, then for a connector.
  2. Read the description, capabilities, creator info, version, and any reviews or stats.
- **What good looks like:**
  - The description is complete and readable - a customer can decide from it alone.
  - Creator/author, version, and install count or rating are all shown.
  - The install/purchase action is obvious and its price (free or paid) is unambiguous.
  - For connectors, the page makes clear what access/credentials it will need.
- **Watch for:** thin or truncated descriptions; missing creator attribution; an item where you can't tell if it's free or paid until checkout.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `MARKET-07` - Purchase a paid marketplace item
- **Customer value:** A customer can buy premium agents/skills and have them unlock immediately - the marketplace's revenue loop.
- **Priority:** High
- **Pre:** Tester A logged in; Stripe test mode; a paid item exists.
- **Scenario:**
  1. Open a paid item's detail page; confirm the price is shown.
  2. Click Purchase / Buy; complete the Stripe test checkout with `4242 4242 4242 4242`.
  3. Return to the app; open your Library.
  4. Separately, start another purchase and cancel at the Stripe screen.
- **What good looks like:**
  - Checkout opens with the correct item and price.
  - On success you return to a clear confirmation, and the item is now available in your Library / installable.
  - Cancelling checkout returns you cleanly with no charge and no half-purchased state.
- **Watch for:** the item not unlocking after a successful payment; being charged but the item still locked; a cancelled checkout leaving a "pending purchase" stuck.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `MARKET-08` - Install an MCP connector with static credentials
- **Customer value:** A customer connects an external tool (one that uses an API token) so their agent can act on it.
- **Priority:** High
- **Pre:** Tester A logged in; an API token for an MCP connector that authenticates with a static token.
- **Scenario:**
  1. Find an MCP server / connector in the marketplace and install it.
  2. When prompted, enter the API token and save.
  3. Run the connector's connection Test.
- **What good looks like:**
  - The connector installs and asks for exactly the credentials it needs.
  - The Test succeeds and reports a healthy connection.
  - The saved token is treated as a secret - never echoed back in plaintext.
- **Watch for:** a Test that always "passes" without really reaching the provider; a wrong token accepted silently; the token visible in the UI or logs afterward.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `MARKET-09` - Install an MCP connector via OAuth
- **Customer value:** A customer connects a service through a one-click OAuth login instead of hunting for an API key.
- **Priority:** High
- **Pre:** Tester A logged in; an account with the connector's OAuth provider.
- **Scenario:**
  1. Install an OAuth-based MCP connector.
  2. Complete the provider's OAuth consent flow.
  3. Run the connection Test.
  4. If possible, observe what an expired/revoked token looks like.
- **What good looks like:**
  - The OAuth flow launches, completes, and returns you to the app connected.
  - The Test succeeds; the connector is usable right after.
  - If a token later expires, the UI offers a clear "reconnect" path rather than failing silently.
- **Watch for:** the OAuth window returning to a broken page; the connector showing "connected" while the Test fails; no recovery path when a token goes stale.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `MARKET-10` - Discover an MCP connector's tools
- **Customer value:** After connecting a tool, a customer wants to see what the agent can now actually do with it.
- **Priority:** Medium
- **Pre:** `MARKET-08` or `MARKET-09` completed.
- **Scenario:**
  1. Open the installed connector and run its "discover" / list-tools action.
  2. Read through the discovered tools and resources.
- **What good looks like:**
  - The connector lists its available tools/resources with human-readable descriptions.
  - The list is genuinely populated (not empty) - proving the connection really works.
  - A customer can tell, from the descriptions, what their agent gained.
- **Watch for:** an empty tool list on a connector that supposedly connected; cryptic tool names with no descriptions; the discover action hanging.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `MARKET-11` - Assign a skill to an agent
- **Customer value:** A customer specializes an agent by attaching a skill so it follows a specific workflow or knowledge set.
- **Priority:** Medium
- **Pre:** An installed agent and an available skill (install one if needed).
- **Scenario:**
  1. Open the agent's edit/configure view.
  2. Assign the skill to the agent and save.
  3. Toggle the skill enabled/disabled, then unassign it.
- **What good looks like:**
  - The skill attaches to the agent and is clearly listed as assigned.
  - Enable/disable and unassign all take effect and persist.
  - The agent's behavior reflects the skill when it is enabled (cross-check with suite 4's `AGENT-B9` if you run a prompt).
- **Watch for:** the assignment not persisting after a reload; a disabled skill still influencing the agent; no visible indication of which skills an agent has.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `MARKET-12` - Library: manage installed agents, skills, connectors, bases, models, themes
- **Customer value:** A customer's installed items have one home where they can review, tune, and prune them.
- **Priority:** Medium
- **Pre:** Several items installed across types (agents, a skill, a connector, a theme).
- **Scenario:**
  1. Open the Library and visit each tab - agents, bases, skills, connectors, models, themes.
  2. Edit an agent: change its model, context window, and thinking effort; save.
  3. Disable an item, then re-enable it.
  4. Delete a disposable installed item.
- **What good looks like:**
  - Each tab lists the right installed items with clear status.
  - Editing an agent's model/context window saves and is honored on the next run.
  - Enable/disable visibly changes availability; delete removes the item cleanly.
  - Changes here are reflected in the project's agent selector.
- **Watch for:** edits silently reverting; a "deleted" item still showing in projects; an item disabled in the Library still selectable in chat; tabs showing the wrong type.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `MARKET-13` - Create a project from a marketplace base
- **Customer value:** A customer skips boilerplate by starting from a ready-made base (e.g. a Next.js + auth starter).
- **Priority:** Medium
- **Pre:** Marketplace open; at least one base available.
- **Scenario:**
  1. Open a base's detail page and review its stack.
  2. Use it to create a new project.
  3. Open the new project's file tree and start it (suite 5).
- **What good looks like:**
  - The base's description matches what you actually get.
  - The new project is pre-populated with the base's files and is immediately startable.
  - It works end to end - no missing files or broken setup out of the gate.
- **Watch for:** a base that produces an empty or broken project; files that don't match the advertised stack; a project that won't start.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `MARKET-14` - Apply a marketplace theme
- **Customer value:** A customer reskins their workspace to a look they like with one install.
- **Priority:** Low
- **Pre:** Marketplace open; at least one theme available.
- **Scenario:**
  1. Open a theme's detail page and review its preview.
  2. Install and apply the theme.
  3. Navigate a few screens to see it in effect.
- **What good looks like:**
  - The theme installs and applies without a reload glitch.
  - The applied look matches the preview - colors, typography, spacing.
  - The UI stays readable and consistent across screens; you can revert to the default.
- **Watch for:** an applied theme that breaks contrast/legibility; the preview not matching reality; no way to switch back.
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
**Overall marketplace experience (1-5) & notes:** 
