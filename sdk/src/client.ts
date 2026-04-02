import { HttpClient } from "./http.js";
import { AgentResource } from "./resources/agent.js";
import { ProjectsResource } from "./resources/projects.js";
import { ShellResource } from "./resources/shell.js";

export interface TesslateClientOptions {
  /** API key (tsk_...). */
  apiKey: string;
  /** Base URL of the Tesslate Studio instance (default: https://your-domain.com). */
  baseUrl?: string;
  /** Request timeout in milliseconds (default: 30 000). */
  timeout?: number;
}

export class TesslateClient {
  readonly projects: ProjectsResource;
  readonly agent: AgentResource;
  readonly shell: ShellResource;

  constructor(opts: TesslateClientOptions) {
    const http = new HttpClient({
      baseUrl: opts.baseUrl ?? "https://your-domain.com",
      apiKey: opts.apiKey,
      timeout: opts.timeout,
    });

    this.projects = new ProjectsResource(http);
    this.agent = new AgentResource(http);
    this.shell = new ShellResource(http);
  }
}
