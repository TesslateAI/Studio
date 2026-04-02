import type { HttpClient } from "../http.js";
import type { Project, ProjectCreateOptions, ProjectCreateResult } from "../types.js";
import { ContainersResource } from "./containers.js";
import { FilesResource } from "./files.js";
import { GitResource } from "./git.js";

export class ProjectsResource {
  constructor(private readonly http: HttpClient) {}

  /** List all projects owned by the authenticated user. */
  async list(): Promise<Project[]> {
    return this.http.get("/api/projects/");
  }

  /** Create a new project. */
  async create(opts: ProjectCreateOptions): Promise<ProjectCreateResult> {
    return this.http.post("/api/projects/", opts);
  }

  /** Get a project by slug or ID. */
  async get(slug: string): Promise<Project> {
    return this.http.get(`/api/projects/${slug}`);
  }

  /** Delete a project. */
  async delete(slug: string): Promise<void> {
    await this.http.delete(`/api/projects/${slug}`);
  }

  /** Get a FilesResource bound to a specific project slug. */
  files(slug: string): FilesResource {
    return new FilesResource(this.http, slug);
  }

  /** Get a ContainersResource bound to a specific project slug. */
  containers(slug: string): ContainersResource {
    return new ContainersResource(this.http, slug);
  }

  /** Get a GitResource bound to a specific project ID. */
  git(projectId: string): GitResource {
    return new GitResource(this.http, projectId);
  }
}
