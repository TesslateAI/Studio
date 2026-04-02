/**
 * Minimal SSE parser for streaming API responses.
 *
 * Reads a `Response.body` readable stream, splits on double-newline
 * boundaries, extracts `data:` fields, and yields parsed JSON objects.
 */
export async function* parseSSE<T = unknown>(response: Response): AsyncGenerator<T> {
  const body = response.body;
  if (!body) return;

  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE events are separated by double newlines
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const rawEvent = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);

        // Extract the data field(s)
        const dataLines: string[] = [];
        for (const line of rawEvent.split("\n")) {
          if (line.startsWith("data:")) {
            dataLines.push(line.slice(5).trimStart());
          }
        }

        if (dataLines.length === 0) continue;

        const payload = dataLines.join("\n");
        if (payload === "[DONE]") return;

        try {
          yield JSON.parse(payload) as T;
        } catch {
          // Non-JSON data line — skip
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
