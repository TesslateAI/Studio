// GitHub provider sugar. Mirrors the curated allowlist in
// orchestrator/app/services/apps/connector_proxy/provider_adapters/github.py.

import type { Dispatch, QueryValue } from "./types.js";

const CONNECTOR_ID = "github";

export interface GitHubGetCommitsArgs {
  owner: string;
  repo: string;
  sha?: string;
  path?: string;
  per_page?: number;
  page?: number;
  [k: string]: unknown;
}

export interface GitHubIssuesListArgs {
  owner: string;
  repo: string;
  state?: "open" | "closed" | "all";
  labels?: string;
  per_page?: number;
  [k: string]: unknown;
}

export interface GitHubIssuesCreateArgs {
  owner: string;
  repo: string;
  title: string;
  body?: string;
  labels?: string[];
  assignees?: string[];
  [k: string]: unknown;
}

class GitHubRepos {
  constructor(private readonly dispatch: Dispatch) {}
  get(args: { owner: string; repo: string }): Promise<Record<string, unknown>> {
    return this.dispatch({
      connectorId: CONNECTOR_ID,
      method: "GET",
      endpointPath: `repos/${args.owner}/${args.repo}`,
    });
  }
  getCommits(args: GitHubGetCommitsArgs): Promise<Array<Record<string, unknown>>> {
    const { owner, repo, ...query } = args;
    return this.dispatch({
      connectorId: CONNECTOR_ID,
      method: "GET",
      endpointPath: `repos/${owner}/${repo}/commits`,
      query: query as Record<string, QueryValue>,
    });
  }
  listBranches(args: {
    owner: string;
    repo: string;
    per_page?: number;
  }): Promise<Array<Record<string, unknown>>> {
    return this.dispatch({
      connectorId: CONNECTOR_ID,
      method: "GET",
      endpointPath: `repos/${args.owner}/${args.repo}/branches`,
      query: args.per_page !== undefined ? { per_page: args.per_page } : undefined,
    });
  }
}

class GitHubIssues {
  constructor(private readonly dispatch: Dispatch) {}
  list(args: GitHubIssuesListArgs): Promise<Array<Record<string, unknown>>> {
    const { owner, repo, ...query } = args;
    return this.dispatch({
      connectorId: CONNECTOR_ID,
      method: "GET",
      endpointPath: `repos/${owner}/${repo}/issues`,
      query: query as Record<string, QueryValue>,
    });
  }
  create(args: GitHubIssuesCreateArgs): Promise<Record<string, unknown>> {
    const { owner, repo, ...body } = args;
    return this.dispatch({
      connectorId: CONNECTOR_ID,
      method: "POST",
      endpointPath: `repos/${owner}/${repo}/issues`,
      body,
    });
  }
  addComment(args: {
    owner: string;
    repo: string;
    issue_number: number;
    body: string;
  }): Promise<Record<string, unknown>> {
    return this.dispatch({
      connectorId: CONNECTOR_ID,
      method: "POST",
      endpointPath: `repos/${args.owner}/${args.repo}/issues/${args.issue_number}/comments`,
      body: { body: args.body },
    });
  }
}

class GitHubUser {
  constructor(private readonly dispatch: Dispatch) {}
  get(): Promise<Record<string, unknown>> {
    return this.dispatch({
      connectorId: CONNECTOR_ID,
      method: "GET",
      endpointPath: "user",
    });
  }
  listRepos(args: { per_page?: number } = {}): Promise<Array<Record<string, unknown>>> {
    return this.dispatch({
      connectorId: CONNECTOR_ID,
      method: "GET",
      endpointPath: "user/repos",
      query: args.per_page !== undefined ? { per_page: args.per_page } : undefined,
    });
  }
}

export class GitHub {
  readonly repos: GitHubRepos;
  readonly issues: GitHubIssues;
  readonly user: GitHubUser;
  constructor(dispatch: Dispatch) {
    this.repos = new GitHubRepos(dispatch);
    this.issues = new GitHubIssues(dispatch);
    this.user = new GitHubUser(dispatch);
  }
}
