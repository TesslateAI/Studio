import type { HttpClient } from "../http.js";
import { parseSSE } from "../sse.js";
import type {
  AgentEvent,
  AgentInvokeOptions,
  AgentInvokeResult,
  AgentTaskStatus,
} from "../types.js";

export class AgentResource {
  constructor(private readonly http: HttpClient) {}

  /** Invoke an agent on a project. Returns immediately with a task ID. */
  async invoke(opts: AgentInvokeOptions): Promise<AgentInvokeResult> {
    return this.http.post("/api/external/agent/invoke", opts);
  }

  /** Poll for the current status of an agent task. */
  async status(taskId: string): Promise<AgentTaskStatus> {
    return this.http.get(`/api/external/agent/status/${taskId}`);
  }

  /** Subscribe to real-time agent events via SSE. */
  async *events(taskId: string): AsyncGenerator<AgentEvent> {
    const res = await this.http.stream(`/api/external/agent/events/${taskId}`);
    yield* parseSSE<AgentEvent>(res);
  }

  /**
   * Invoke an agent and wait for it to complete.
   *
   * Polls the status endpoint at the given interval until the task
   * reaches a terminal state (`completed`, `failed`, or `cancelled`).
   */
  async invokeAndWait(
    opts: AgentInvokeOptions,
    pollIntervalMs = 2000,
  ): Promise<AgentTaskStatus> {
    const { task_id } = await this.invoke(opts);
    const terminal = new Set(["completed", "failed", "cancelled"]);

    for (;;) {
      const s = await this.status(task_id);
      if (terminal.has(s.status)) return s;
      await new Promise((r) => setTimeout(r, pollIntervalMs));
    }
  }
}
