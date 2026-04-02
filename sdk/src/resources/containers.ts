import type { HttpClient } from "../http.js";
import type {
  Container,
  ContainerStartResult,
  ContainerStopResult,
} from "../types.js";

export class ContainersResource {
  constructor(
    private readonly http: HttpClient,
    private readonly slug: string,
  ) {}

  /** List containers in the project. */
  async list(): Promise<Container[]> {
    return this.http.get(`/api/projects/${this.slug}/containers`);
  }

  /** Start all containers in the project. */
  async startAll(): Promise<ContainerStartResult> {
    return this.http.post(`/api/projects/${this.slug}/containers/start-all`);
  }

  /** Stop all containers in the project. */
  async stopAll(): Promise<ContainerStopResult> {
    return this.http.post(`/api/projects/${this.slug}/containers/stop-all`);
  }
}
