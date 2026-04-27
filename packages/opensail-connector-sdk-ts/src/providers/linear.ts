// Linear provider sugar. Linear's API is GraphQL-first; the proxy
// allowlist exposes POST /graphql plus a few REST helpers. The SDK
// surfaces a generic graphql() plus typed sugar for issues.list and
// issues.create — the two most-used operations.

import type { Dispatch } from "./types.js";

const CONNECTOR_ID = "linear";

const ISSUES_LIST_QUERY = `
query IssuesList($first: Int, $filter: IssueFilter) {
  issues(first: $first, filter: $filter) {
    nodes {
      id
      identifier
      title
      state { id name type }
      assignee { id name email }
      url
      createdAt
      updatedAt
    }
    pageInfo { hasNextPage endCursor }
  }
}
`.trim();

const ISSUES_CREATE_MUTATION = `
mutation IssueCreate($input: IssueCreateInput!) {
  issueCreate(input: $input) {
    success
    issue {
      id
      identifier
      title
      url
    }
  }
}
`.trim();

export interface LinearGraphqlArgs {
  query: string;
  variables?: Record<string, unknown>;
  operationName?: string;
}

export interface LinearIssuesListArgs {
  first?: number;
  filter?: Record<string, unknown>;
}

export interface LinearIssuesCreateArgs {
  team_id: string;
  title: string;
  description?: string;
  assignee_id?: string;
  priority?: number;
  labels?: string[];
  [k: string]: unknown;
}

class LinearIssues {
  constructor(private readonly graphqlFn: (args: LinearGraphqlArgs) => Promise<Record<string, unknown>>) {}

  list(args: LinearIssuesListArgs = {}): Promise<Record<string, unknown>> {
    const variables: Record<string, unknown> = {};
    if (args.first !== undefined) variables.first = args.first;
    if (args.filter !== undefined) variables.filter = args.filter;
    return this.graphqlFn({ query: ISSUES_LIST_QUERY, variables });
  }

  create(args: LinearIssuesCreateArgs): Promise<Record<string, unknown>> {
    const { team_id, title, description, assignee_id, priority, labels, ...extra } = args;
    const input: Record<string, unknown> = { teamId: team_id, title };
    if (description !== undefined) input.description = description;
    if (assignee_id !== undefined) input.assigneeId = assignee_id;
    if (priority !== undefined) input.priority = priority;
    if (labels !== undefined) input.labelIds = labels;
    Object.assign(input, extra);
    return this.graphqlFn({ query: ISSUES_CREATE_MUTATION, variables: { input } });
  }
}

export class Linear {
  readonly issues: LinearIssues;
  constructor(private readonly dispatch: Dispatch) {
    this.issues = new LinearIssues((args) => this.graphql(args));
  }

  graphql(args: LinearGraphqlArgs): Promise<Record<string, unknown>> {
    const body: Record<string, unknown> = { query: args.query };
    if (args.variables !== undefined) body.variables = args.variables;
    if (args.operationName !== undefined) body.operationName = args.operationName;
    return this.dispatch({
      connectorId: CONNECTOR_ID,
      method: "POST",
      endpointPath: "graphql",
      body,
    });
  }
}
