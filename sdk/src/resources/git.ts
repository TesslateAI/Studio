import type { HttpClient } from "../http.js";
import type {
  GitBranchesResult,
  GitCommitResult,
  GitPullResult,
  GitPushResult,
  GitStatus,
} from "../types.js";

export class GitResource {
  constructor(
    private readonly http: HttpClient,
    private readonly projectId: string,
  ) {}

  /** Get git status (branch, changes, ahead/behind). */
  async status(): Promise<GitStatus> {
    return this.http.get(`/api/projects/${this.projectId}/git/status`);
  }

  /** Commit staged changes (or specific files). */
  async commit(message: string, files?: string[]): Promise<GitCommitResult> {
    return this.http.post(`/api/projects/${this.projectId}/git/commit`, {
      message,
      files: files ?? null,
    });
  }

  /** Push to remote. */
  async push(opts?: {
    branch?: string;
    remote?: string;
    force?: boolean;
  }): Promise<GitPushResult> {
    return this.http.post(`/api/projects/${this.projectId}/git/push`, opts ?? {});
  }

  /** Pull from remote. */
  async pull(opts?: { branch?: string; remote?: string }): Promise<GitPullResult> {
    return this.http.post(`/api/projects/${this.projectId}/git/pull`, opts ?? {});
  }

  /** List branches. */
  async branches(): Promise<GitBranchesResult> {
    return this.http.get(`/api/projects/${this.projectId}/git/branches`);
  }

  /** Create a new branch. */
  async createBranch(name: string, checkout = false): Promise<void> {
    await this.http.post(`/api/projects/${this.projectId}/git/branch`, {
      name,
      checkout,
    });
  }

  /** Switch to an existing branch. */
  async switchBranch(name: string): Promise<void> {
    await this.http.post(`/api/projects/${this.projectId}/git/switch`, {
      branch: name,
    });
  }
}
