// Slack provider sugar. Mirrors the curated allowlist in
// orchestrator/app/services/apps/connector_proxy/provider_adapters/slack.py.
// The dotted Slack method shape (chat.postMessage) is preserved as nested
// namespaces so call sites read like the upstream docs.

import type { Dispatch } from "./types.js";

const CONNECTOR_ID = "slack";

export interface SlackChatPostMessageArgs {
  channel: string;
  text?: string;
  blocks?: Array<Record<string, unknown>>;
  thread_ts?: string;
  attachments?: Array<Record<string, unknown>>;
  [k: string]: unknown;
}

export interface SlackChatUpdateArgs {
  channel: string;
  ts: string;
  text?: string;
  blocks?: Array<Record<string, unknown>>;
  [k: string]: unknown;
}

export interface SlackChatDeleteArgs {
  channel: string;
  ts: string;
  [k: string]: unknown;
}

export interface SlackConversationsListArgs {
  limit?: number;
  cursor?: string;
  types?: string;
  exclude_archived?: boolean;
  [k: string]: unknown;
}

export interface SlackConversationsHistoryArgs {
  channel: string;
  limit?: number;
  cursor?: string;
  [k: string]: unknown;
}

export interface SlackUsersListArgs {
  limit?: number;
  cursor?: string;
}

class SlackChat {
  constructor(private readonly dispatch: Dispatch) {}
  postMessage(args: SlackChatPostMessageArgs): Promise<Record<string, unknown>> {
    return this.dispatch({
      connectorId: CONNECTOR_ID,
      method: "POST",
      endpointPath: "chat.postMessage",
      body: args,
    });
  }
  update(args: SlackChatUpdateArgs): Promise<Record<string, unknown>> {
    return this.dispatch({
      connectorId: CONNECTOR_ID,
      method: "POST",
      endpointPath: "chat.update",
      body: args,
    });
  }
  delete(args: SlackChatDeleteArgs): Promise<Record<string, unknown>> {
    return this.dispatch({
      connectorId: CONNECTOR_ID,
      method: "POST",
      endpointPath: "chat.delete",
      body: args,
    });
  }
}

class SlackConversations {
  constructor(private readonly dispatch: Dispatch) {}
  list(args: SlackConversationsListArgs = {}): Promise<Record<string, unknown>> {
    const { exclude_archived, ...rest } = args;
    return this.dispatch({
      connectorId: CONNECTOR_ID,
      method: "GET",
      endpointPath: "conversations.list",
      query: {
        ...(rest as Record<string, string | number | boolean | string[] | undefined>),
        ...(exclude_archived !== undefined
          ? { exclude_archived: exclude_archived ? "true" : "false" }
          : {}),
      },
    });
  }
  history(args: SlackConversationsHistoryArgs): Promise<Record<string, unknown>> {
    return this.dispatch({
      connectorId: CONNECTOR_ID,
      method: "GET",
      endpointPath: "conversations.history",
      query: args as Record<string, string | number | boolean | string[] | undefined>,
    });
  }
}

class SlackUsers {
  constructor(private readonly dispatch: Dispatch) {}
  list(args: SlackUsersListArgs = {}): Promise<Record<string, unknown>> {
    return this.dispatch({
      connectorId: CONNECTOR_ID,
      method: "GET",
      endpointPath: "users.list",
      query: args as Record<string, string | number | boolean | string[] | undefined>,
    });
  }
  lookupByEmail(args: { email: string }): Promise<Record<string, unknown>> {
    return this.dispatch({
      connectorId: CONNECTOR_ID,
      method: "GET",
      endpointPath: "users.lookupByEmail",
      query: { email: args.email },
    });
  }
}

export class Slack {
  readonly chat: SlackChat;
  readonly conversations: SlackConversations;
  readonly users: SlackUsers;
  constructor(dispatch: Dispatch) {
    this.chat = new SlackChat(dispatch);
    this.conversations = new SlackConversations(dispatch);
    this.users = new SlackUsers(dispatch);
  }
}
