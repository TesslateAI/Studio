import { NextRequest } from 'next/server';
import { getLLM, getModel } from '../../../lib/llm';
import { CRM_TOOLS, dispatchTool } from '../../../lib/tools';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const SYSTEM_PROMPT = `You are the Tesslate CRM assistant. You help the user manage contacts,
notes, and activity. You have access to tools for listing, creating, updating, deleting
contacts, adding notes, and fetching activity. Prefer calling tools over guessing.
When you create or modify data, briefly confirm what you did.`;

function sseEvent(name: string, data: unknown): Uint8Array {
  const payload = typeof data === 'string' ? data : JSON.stringify(data);
  return new TextEncoder().encode(`event: ${name}\ndata: ${payload}\n\n`);
}

interface ToolCallAcc {
  id: string;
  name: string;
  args: string;
}

export async function POST(req: NextRequest) {
  // The shell includes an invocation id in the auth header for lifecycle
  // bookkeeping. We accept either "Bearer <id>" or raw id; currently used
  // only for observability.
  const authHeader = req.headers.get('authorization') ?? '';
  const invocationId = authHeader.replace(/^Bearer\s+/i, '').trim() || null;

  const body = await req.json().catch(() => ({}));
  const incoming: Array<{ role: string; content: string }> = body.messages ?? [];

  const messages: any[] = [
    { role: 'system', content: SYSTEM_PROMPT },
    ...incoming.map((m) => ({ role: m.role, content: m.content })),
  ];

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const enqueue = (name: string, data: unknown) => controller.enqueue(sseEvent(name, data));
      enqueue('invocation', { invocation_id: invocationId });

      let llm;
      try {
        llm = getLLM();
      } catch (e: any) {
        enqueue('error', { message: String(e?.message ?? e) });
        controller.close();
        return;
      }

      const model = getModel();
      let loopGuard = 0;

      try {
        // Tool-use loop. Each iteration streams a single assistant turn.
        while (loopGuard++ < 8) {
          const resp = await llm.chat.completions.create({
            model,
            messages,
            tools: CRM_TOOLS,
            tool_choice: 'auto',
            stream: true,
          });

          const toolCalls: Record<number, ToolCallAcc> = {};
          let assistantText = '';

          for await (const chunk of resp) {
            const choice = chunk.choices?.[0];
            if (!choice) continue;
            const delta: any = choice.delta ?? {};
            if (delta.content) {
              assistantText += delta.content;
              enqueue('delta', { text: delta.content });
            }
            if (delta.tool_calls) {
              for (const tc of delta.tool_calls as any[]) {
                const idx = tc.index ?? 0;
                const acc = (toolCalls[idx] ??= { id: '', name: '', args: '' });
                if (tc.id) acc.id = tc.id;
                if (tc.function?.name) acc.name = tc.function.name;
                if (tc.function?.arguments) acc.args += tc.function.arguments;
              }
            }
          }

          const assembled = Object.values(toolCalls).filter((tc) => tc.name);

          // Append the assistant turn (with tool calls if any).
          const assistantMsg: any = { role: 'assistant', content: assistantText || null };
          if (assembled.length > 0) {
            assistantMsg.tool_calls = assembled.map((tc) => ({
              id: tc.id,
              type: 'function',
              function: { name: tc.name, arguments: tc.args },
            }));
          }
          messages.push(assistantMsg);

          if (assembled.length === 0) {
            // No more tool calls; we have the final answer streamed above.
            enqueue('done', { ok: true });
            break;
          }

          // Execute each tool and append results.
          for (const tc of assembled) {
            enqueue('tool_call', { id: tc.id, name: tc.name, arguments: tc.args });
            const result = await dispatchTool(tc.name, tc.args);
            enqueue('tool_result', { id: tc.id, name: tc.name, result });
            messages.push({
              role: 'tool',
              tool_call_id: tc.id,
              content: result,
            });
          }
          // Loop: send the tool results back for the next assistant turn.
        }
      } catch (err: any) {
        enqueue('error', { message: String(err?.message ?? err) });
      } finally {
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
    },
  });
}
