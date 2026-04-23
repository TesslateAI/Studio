# @tesslate/embed-sdk

Client-side SDK for Tesslate Apps rendered inside the Studio shell iframe. It
wraps `window.postMessage` with a typed request/response + event protocol
(`EmbedEnvelope`, protocol version `v: 1`). Every inbound and outbound message
is origin-checked against the `targetOrigin` you pass in — wildcard is rejected.
The paired host component (Studio's `IframeAppHost`, Wave 4) speaks the same
envelope shape and enforces the inverse origin pin.

Because the embed SDK talks to the shell via `postMessage` rather than HTTP, it
does not touch the Studio REST API — there is no Bearer token and no CSRF to
worry about at this layer. Authentication is established by the shell when it
mints the iframe URL.

```ts
import { createEmbedClient } from "@tesslate/embed-sdk";

const client = createEmbedClient({
  targetOrigin: "https://opensail.tesslate.com",
  timeoutMs: 10_000,
});

// Request / response
const session = await client.request<
  { app_instance_id: string },
  { session_id: string; api_key: string }
>("runtime.begin_session", { app_instance_id: "…" });

// Subscribe to events
const off = client.on<{ usd: number }>("billing.tick", (p) => {
  console.log("spent", p.usd);
});

// Later
off();
client.dispose();
```
