import type { HttpClient } from "../http.js";
import type {
  ShellCreateOptions,
  ShellOutputResult,
  ShellSession,
  ShellWriteResult,
} from "../types.js";

export class ShellResource {
  constructor(private readonly http: HttpClient) {}

  /** Create a new shell session. */
  async createSession(opts: ShellCreateOptions): Promise<ShellSession> {
    return this.http.post("/api/shell/sessions", opts);
  }

  /** Write data (typically a command + newline) to the session stdin. */
  async write(sessionId: string, data: string): Promise<ShellWriteResult> {
    return this.http.post(`/api/shell/sessions/${sessionId}/write`, { data });
  }

  /**
   * Read new output from the session.
   *
   * The raw output from the server is base64-encoded. This method decodes
   * it and returns the plain text in the `output` field.
   */
  async readOutput(sessionId: string): Promise<ShellOutputResult> {
    const raw: ShellOutputResult = await this.http.get(
      `/api/shell/sessions/${sessionId}/output`,
    );

    // Decode base64 output to plain text
    if (raw.output) {
      try {
        raw.output = atob(raw.output);
      } catch {
        // Already plain text or invalid base64 — return as-is
      }
    }

    return raw;
  }

  /** Close and clean up a shell session. */
  async close(sessionId: string): Promise<void> {
    await this.http.delete(`/api/shell/sessions/${sessionId}`);
  }

  /**
   * Convenience: run a command and return its output.
   *
   * Creates a session, writes the command, waits briefly for output,
   * reads it, and closes the session.
   */
  async run(
    projectId: string,
    command: string,
    opts?: { containerName?: string; waitMs?: number },
  ): Promise<string> {
    const session = await this.createSession({
      project_id: projectId,
      container_name: opts?.containerName,
    });

    // Write the command (append newline + shell exit so the session terminates)
    const exitCmd = "\nexit\n";
    await this.write(session.session_id, command + exitCmd);

    // Wait for output to be produced
    await new Promise((r) => setTimeout(r, opts?.waitMs ?? 2000));

    const result = await this.readOutput(session.session_id);
    await this.close(session.session_id).catch(() => {});
    return result.output;
  }
}
