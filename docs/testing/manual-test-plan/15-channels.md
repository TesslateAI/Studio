# Suite 15 - Messaging Channels

> See [README.md](README.md) for format, priorities, severity, environments, and accounts.

**Why this suite matters:** Messaging channels let a customer take their Tesslate agent out of the browser and into the apps they already live in - Telegram, Discord, Slack, WhatsApp, Signal. The promise is simple and powerful: "I can message my agent from my phone and it answers." That end-to-end loop - a real message sent from a real platform, an agent run triggered, a useful reply delivered back to that same conversation - is what this suite exists to prove. A channel that connects but never actually relays a conversation is worthless, so judge this suite on the **round trip**, not on whether a config saved.

**Suite prerequisites:** Tester A logged in. The platform running in a mode where the gateway is available (Cloud or Docker). For the real end-to-end cases you need actual bot credentials on at least one platform - most easily a **Telegram bot token** from BotFather and the Telegram app installed. An agent/project the channel can route messages to. The settings area for Connections / Channels.

---

### `CHANNEL-01` - See which messaging platforms are supported
- **Customer value:** A customer can quickly see which messaging apps they can connect their agent to and what each one needs.
- **Priority:** Medium
- **Pre:** Tester A logged in; the Connections / Channels settings open.
- **Scenario:**
  1. Open the supported-platforms view.
  2. Read the entry for each platform.
- **What good looks like:**
  - Telegram, Discord, Slack, WhatsApp, Signal, and CLI are all listed.
  - Each platform has setup notes explaining what credentials/steps are required (e.g. a bot token, an OAuth app).
  - It's clear which platforms are fully supported by the gateway versus any that are limited.
- **Watch for:** a platform listed with no setup guidance; missing platforms; setup notes too vague to act on.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CHANNEL-02` - Connect a channel with bot credentials
- **Customer value:** A customer connects their agent to a messaging platform by giving the platform a bot to talk through.
- **Priority:** High
- **Pre:** Bot credentials ready for one platform (e.g. a Telegram bot token).
- **Scenario:**
  1. Add a new channel and choose the platform.
  2. Enter the bot credentials and give the channel a name.
  3. Save.
- **What good looks like:**
  - The channel is created and confirmed; it appears in the channel list.
  - Credentials are stored securely - the bot token is **not** displayed back in plaintext after saving.
  - If the platform needs a webhook URL/secret, it is generated and shown so the customer can wire it into the platform.
  - The form makes it clear what to do next to finish hooking up the platform.
- **Watch for:** the token echoed back in plaintext; no confirmation the channel saved; a generated webhook URL hidden where the customer can't find it; an unclear "now what" after saving.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CHANNEL-03` - List, update, and delete channel configs
- **Customer value:** A customer can manage their connected channels over time - see them, adjust them, and remove ones they no longer use.
- **Priority:** Medium
- **Pre:** `CHANNEL-02` done - at least one channel exists.
- **Scenario:**
  1. Open the channel list and confirm your channels are shown.
  2. Edit a channel - change its name and toggle its active flag, then save.
  3. Create a disposable channel, then delete it.
- **What good looks like:**
  - The list shows each channel with its platform, name, and active/inactive state.
  - Edits persist and are reflected immediately; the gateway picks up the change without a restart-the-world ritual.
  - Deleting a channel removes it from the list and the gateway stops using it.
- **Watch for:** stale state after editing; a deleted channel still receiving/processing messages; the list not reflecting active/inactive toggles.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CHANNEL-04` - Send a test message and confirm it arrives
- **Customer value:** Before relying on a channel, a customer can prove it actually delivers messages to the platform.
- **Priority:** High
- **Pre:** A configured channel with valid credentials; access to the target platform/chat to receive the message.
- **Scenario:**
  1. Use the channel's "Test" / send-test action.
  2. Open the actual messaging platform and look for the test message.
- **What good looks like:**
  - The test action reports success in Tesslate Studio.
  - The test message genuinely **arrives** in the platform conversation - you can see it in Telegram/Discord/etc.
  - If the credentials are wrong, the test fails with a clear, specific error rather than a false success.
- **Watch for:** a "sent" confirmation when nothing actually arrives; a generic failure with no reason; a long hang before the test resolves.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CHANNEL-05` - Message the agent from the real platform and get a reply
- **Customer value:** The headline promise - a customer messages their bot from Telegram (or another platform) and the agent answers, right there in the conversation.
- **Priority:** Critical
- **Pre:** A fully connected channel wired to an agent/project (webhook registered with the platform if required); the messaging app on hand.
- **Scenario:**
  1. From the real platform (e.g. Telegram), open a chat with the connected bot.
  2. Send the bot a message - a question or a simple request the agent can act on.
  3. Wait for a response in that same conversation.
- **What good looks like:**
  - The inbound message is received and triggers an agent run.
  - The agent's response is delivered **back into the same platform conversation** - the customer never has to leave Telegram to see it.
  - The reply is a genuine, relevant agent response to what was asked - not an echo, not an error string.
  - Round-trip latency is reasonable; if the agent is still working, there's some sign of life rather than dead silence.
- **Watch for:** the message never reaching the agent; the agent running but the reply never coming back; the reply landing in the wrong conversation; an error message instead of an answer; an unbounded wait with no feedback.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CHANNEL-06` - Conversation context survives across platform messages
- **Customer value:** A customer can have an actual back-and-forth with their agent from the messaging app, not just one-shot questions.
- **Priority:** High
- **Pre:** `CHANNEL-05` working - at least one agent reply received on the platform.
- **Scenario:**
  1. From the platform, send a follow-up message that refers to the previous reply without restating it.
  2. Wait for the agent's response.
- **What good looks like:**
  - The agent understands the follow-up in context - it knows what "that" or "the previous one" refers to.
  - The conversation feels continuous, like chatting with the agent in the browser.
- **Watch for:** the agent treating every message as a fresh, contextless request; it asking the customer to re-explain; replies arriving out of order.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CHANNEL-07` - Pair a platform identity with a verification code
- **Customer value:** A customer can link their personal platform account (their Telegram/Discord identity) to their Tesslate account so the agent knows who it's talking to.
- **Priority:** Medium
- **Pre:** A pairing code generated for a platform account.
- **Scenario:**
  1. Obtain the pairing code for the platform identity.
  2. Enter and verify the pairing code in Tesslate Studio.
  3. Then try an invalid or expired code.
- **What good looks like:**
  - A correct code marks the platform identity as verified and links it to the customer's account.
  - The verified link is visible afterward - the customer can confirm the pairing took.
  - An invalid or expired code is clearly rejected with a helpful message.
- **Watch for:** a code "verifying" but the identity never showing as linked; an expired code silently accepted; no feedback on a bad code.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CHANNEL-08` - Gateway status indicator is honest
- **Customer value:** A customer can tell at a glance whether the messaging gateway is up - so they know whether their channels will actually relay messages right now.
- **Priority:** Low
- **Pre:** Tester A logged in.
- **Scenario:**
  1. Open the gateway status indicator.
  2. Read what it reports.
- **What good looks like:**
  - The indicator clearly shows the gateway as online or offline.
  - When online, it reflects something real - e.g. active adapters / session counts.
  - If the gateway is down, it shows a clear "unavailable" state instead of a blank or a crash.
- **Watch for:** a status that always reads online regardless of reality; a confusing or empty indicator; the page erroring when the gateway is unreachable.
- **Result:** [ ] Pass [ ] Fail [ ] Blocked - **Notes:**

### `CHANNEL-09` - A channel error is surfaced, not swallowed
- **Customer value:** When a connected channel breaks (revoked token, platform outage), the customer finds out instead of silently losing their agent's reach.
- **Priority:** Medium
- **Pre:** A working channel; the ability to break it (e.g. revoke/rotate the bot token at the platform).
- **Scenario:**
  1. Break the channel's credentials at the platform side.
  2. Send a test message, or message the bot from the platform.
  3. Observe how Tesslate Studio reports the channel's health.
- **What good looks like:**
  - The broken channel surfaces a clear error - a test fails with a specific reason, or the channel's state reflects the problem.
  - The customer can tell the channel is the issue and is pointed toward fixing the credentials.
  - Other healthy channels keep working - one broken channel doesn't take the rest down.
- **Watch for:** a broken channel still appearing healthy; messages silently dropped with no error; one bad channel breaking the whole gateway.
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
**Overall channels experience (1-5) & notes:** 
