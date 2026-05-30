# Tesslate Studio / OpenSail - Manual Test Plan

> **Audience:** External / outside QA testers.
> **Goal:** Exercise the features customers actually pay for, by hand, and judge whether they **work** and **feel good** - not just whether endpoints return 200.

This plan is **product- and experience-focused**. It deliberately does **not** re-test things already covered by the automated suites (auth gates, route protection, token refresh, 2FA mechanics, RBAC enforcement, webhook signature checks, API-key scope rejection, generic form validation). Those live in `docs/testing/README.md`. Here we test the **value loop**: creating projects, the AI agent building real software, running and previewing apps, the marketplace, the Tesslate App economy, deployment, collaboration, and billing.

**New tester?** If you need to run the platform yourself, start with the general [dev environment onboarding](../../ONBOARDING.md) - it covers the dev tools and Minikube setup that apply to everyone working on OpenSail. Then read this README's **Test environment & accounts** section and [PROCEDURE.md](PROCEDURE.md) for the testing workflow.

---

## How to use this plan

Each suite is its own file (see the [index](#suite-index)). Every suite contains numbered **test cases** in this format:

> ### `PREFIX-NN` - Short title
> - **Customer value:** what this lets a customer do / why they care.
> - **Priority:** Critical / High / Medium / Low.
> - **Pre:** state that must exist before you start.
> - **Scenario:** the real-world steps you perform, as a customer would.
> - **What good looks like:** observable signs the feature genuinely works *and* is pleasant to use.
> - **Watch for:** failure modes and rough edges that would frustrate a real user.
> - **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

A case **passes** only if every "What good looks like" point holds. If the feature technically works but is slow, confusing, or ugly enough to frustrate a customer, mark it **Fail** and describe it - that is a real defect in a product test.

**Priorities**

| Priority | Meaning |
|----------|---------|
| **Critical** | Core value loop. If broken, the product does not deliver its promise. Test every cycle. |
| **High** | Major feature; broken state blocks an important workflow. |
| **Medium** | Secondary feature or polish. |
| **Low** | Edge case, rarely used, or cosmetic. |

**Defect severity (for bug reports)**

| Severity | Definition |
|----------|------------|
| **S1 - Blocker** | Data loss, crash, or a Critical value loop fully broken. |
| **S2 - Major** | Feature broken with no reasonable workaround. |
| **S3 - Minor** | Works but wrong/awkward; a workaround exists. |
| **S4 - Trivial** | Cosmetic, copy, alignment, console noise. |

---

## Test environment & accounts

1. **Browser:** Latest Chrome (primary). Spot-check Firefox / Safari / Edge on Critical cases.
2. **URL:** Use the QA/staging URL the team provides. Do **not** test against production unless told to.
3. **DevTools:** Keep the Network + Console tabs open; note any errors.
4. **Email:** A real inbox (ideally two) for verification, invites, and notifications.
5. **Stripe test mode:** Card `4242 4242 4242 4242`, any future expiry, any CVC - for billing and paid-item cases.
6. **API client:** Postman / Insomnia / `curl` - only needed for the External Agent API suite.
7. **Deployment mode:** the platform runs as **Cloud (Kubernetes)**, **Docker (local dev)**, or **Desktop (Tauri)**. Most suites apply everywhere; mode-specific cases are tagged `[Cloud only]`, `[Desktop only]`, etc. Confirm your environment's mode.

**Test accounts** (create once, reuse across suites):

| Account | Purpose | Notes |
|---------|---------|-------|
| **Tester A** | Primary account for most suites. | Put on a **paid tier** if possible (unlocks BYOK, higher limits). |
| **Tester B** | Collaboration / teams / shared-project cases. | Separate real email. |
| **Admin** | App submission review, yank approvals. | Superuser - request from the team. |

---

## Feature sets - for test assignment

The 21 suites are grouped into 7 **feature sets**. Each set is a coherent area of the product and can be handed to one tester as a unit - so a feature can be owned end to end. Fill in the **Assigned to** column each cycle.

| Set | Feature set | Suites | Cases | Assigned to | Focus |
|-----|-------------|--------|-------|-------------|-------|
| **A** | Core Build Loop | 1 [Onboarding](01-onboarding.md), 2 [Project creation](02-project-creation.md), 3 [Builder workspace](03-builder-workspace.md), 5 [Containers & preview](05-containers-preview.md) | 47 | | Sign up -> create a project -> edit in the IDE -> run & preview it. |
| **B** | AI Agent & Automation | 4 [AI agent](04-ai-agent.md), 16 [Schedules](16-schedules.md), 17 [External Agent API](17-external-agent-api.md) | 42 | | Invoking the agent - interactively, on a schedule, and via API. |
| **C** | Project Workspace Tools | 6 [Architecture panel](06-architecture-panel.md), 7 [Snapshots](07-snapshots-timeline.md), 8 [Kanban](08-kanban.md) | 29 | | Tools layered on a project: visualize, version, plan. |
| **D** | Marketplace & Publishing | 9 [Marketplace](09-marketplace.md), 10 [Creator publishing](10-creator-publishing.md) | 21 | | Discover & install extensions + publish your own. |
| **E** | Tesslate Apps | 11 [Publish app](11-publish-app.md), 12 [Install & run apps](12-install-run-apps.md), 13 [App economy](13-app-economy.md) | 33 | | The full App lifecycle: publish -> install -> run -> bill. |
| **F** | Collaboration & Account | 18 [Teams](18-teams-collaboration.md), 19 [Billing](19-billing-credits.md), 20 [Account & settings](20-account-settings.md) | 36 | | Org, money, and personal account. |
| **G** | Platforms & Integrations | 14 [Deployments](14-deployments.md), 15 [Channels](15-channels.md), 21 [Desktop](21-desktop.md) | 32 | | Connecting outward + the desktop client. |

Total: 240 cases across 7 sets. Set D is the lightest - whoever owns it can pick up a second set or share Set A.

---

## Suite index

Run roughly in order - later suites assume you can already create a project and use the agent.

| # | Suite | File | Focus |
|---|-------|------|-------|
| 1 | Onboarding & first build | [01-onboarding.md](01-onboarding.md) | Sign up -> land in product -> reach a first working result. |
| 2 | Project creation & setup | [02-project-creation.md](02-project-creation.md) | Empty / template / Git import, plus the analyze + config flow. |
| 3 | Builder workspace | [03-builder-workspace.md](03-builder-workspace.md) | Editor, file tree, tabs, moving between views. |
| 4 | **AI agent - code generation & interaction** | [04-ai-agent.md](04-ai-agent.md) | The heart of the product. Interaction mechanics **and** end-to-end builds. |
| 5 | Containers & live preview | [05-containers-preview.md](05-containers-preview.md) | Run the app, hot reload, logs, debug a broken start. |
| 6 | Architecture panel | [06-architecture-panel.md](06-architecture-panel.md) | Visualize & wire up the app's structure. |
| 7 | Snapshots & timeline | [07-snapshots-timeline.md](07-snapshots-timeline.md) | Version work, branch, restore. |
| 8 | Kanban | [08-kanban.md](08-kanban.md) | Plan & track work; agent-driven tasks. |
| 9 | Marketplace - discover & install | [09-marketplace.md](09-marketplace.md) | Browse/search, install agents/skills/MCP/bases/themes. |
| 10 | Creator publishing | [10-creator-publishing.md](10-creator-publishing.md) | Publish your own agent/skill to the marketplace. |
| 11 | Publish a project as an App | [11-publish-app.md](11-publish-app.md) | Draft -> manifest -> submit -> approval journey. |
| 12 | Install & run Apps | [12-install-run-apps.md](12-install-run-apps.md) | Discover, install, use, manage, uninstall Tesslate Apps. |
| 13 | App economy | [13-app-economy.md](13-app-economy.md) | Wallets, spend, yanks/appeals, fork, bundles, admin workbench. |
| 14 | External deployments | [14-deployments.md](14-deployments.md) | Ship a project to Vercel / Netlify / Cloudflare. |
| 15 | Messaging channels | [15-channels.md](15-channels.md) | Connect Telegram/Discord/Slack; chat with an agent from there. |
| 16 | Schedules & automations | [16-schedules.md](16-schedules.md) | Recurring agent runs that fire and deliver. |
| 17 | External Agent API | [17-external-agent-api.md](17-external-agent-api.md) | Programmatic agent invocation as a developer-customer. |
| 18 | Teams & collaboration | [18-teams-collaboration.md](18-teams-collaboration.md) | Create a team, invite, two people co-build on one project. |
| 19 | Billing & credits | [19-billing-credits.md](19-billing-credits.md) | Subscribe, buy credits, manage plan, the out-of-credits moment. |
| 20 | Account, settings & appearance | [20-account-settings.md](20-account-settings.md) | Profile, preferences, connections, BYOK, themes, notifications. |
| 21 | Desktop app | [21-desktop.md](21-desktop.md) | Launch, runtimes, import local folders, local<->cloud sync, tray, updates. |

---

## Smoke test - run first, every cycle

A fast subset that proves the build is worth testing. If any fails, **stop and file a blocker**.

1. `ONBOARD-01` - Sign up and reach the product.
2. `CREATE-01` - Create a project.
3. `AGENT-B1` - Ask the agent to build a feature; it produces working code.
4. `RUN-01` / `RUN-04` - Start the project; the live preview renders the app.
5. `MARKET-04` - Install a free marketplace agent.
6. `APP-USE-02` - Install an approved Tesslate App.
7. `BILLING-01` - Billing page shows the correct tier and credits.

---

## Appendix A - Bug report template

```
Title:        [Suite/Area] Short description of the defect
Test case:    e.g. AGENT-B3
Severity:     S1 Blocker / S2 Major / S3 Minor / S4 Trivial
Environment:  URL, mode (Cloud/Docker/Desktop), browser + version, OS
Account:      Which test account / tier
Preconditions:What state existed before
Steps to reproduce:
  1.
  2.
Expected (what good looks like):
Actual result:
Evidence:     Screenshots / recording / console + network trace / request IDs
Frequency:    Always / Intermittent (X of Y) / Once
Notes:        Workaround, related cases
```

Rules: one defect per report; always attach console + network evidence for errors; for intermittent bugs record the hit rate; re-test on a clean account/session before filing to rule out stale state.

---

## Appendix B - Test cycle summary

| Field | Value |
|-------|-------|
| Cycle / build | |
| Environment & mode | |
| Tester(s) | |
| Date range | |
| Total cases / Pass / Fail / Blocked / Not run | |
| Defects S1 / S2 / S3 / S4 | |
| Sign-off (go / no-go) | |

Each suite file ends with its own per-suite roll-up table - fill those in, then total them here.

---

## Appendix C - Glossary

| Term | Meaning |
|------|---------|
| **Project** | A customer's app/workspace - files, containers, chat. |
| **Builder / workspace** | The IDE-like screen: editor, chat, preview, architecture. |
| **Agent** | The AI that generates and edits code from chat prompts. |
| **Skill** | A reusable instruction set attachable to an agent. |
| **MCP server** | A connector giving the agent external tools (Slack, Linear, etc.). |
| **Base** | A starter template a new project can be created from. |
| **Tesslate App** | A project published as an installable marketplace app, with its own approval, install, runtime, and billing lifecycle. |
| **Snapshot** | A saved point-in-time version of a project. |
| **Channel / Gateway** | The messaging layer connecting agents to Telegram/Discord/Slack/etc. |
| **Credits / Wallet** | Billing balances - credits fund AI usage; wallets settle App spend. |
| **BYOK** | "Bring Your Own Key" - using your own LLM provider API key. |
| **Yank** | Unpublishing/recalling an App version. |

---

*Track results in a copy of each suite file per cycle - keep the originals as the master.*
