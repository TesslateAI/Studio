import type { ComponentType } from 'react';
import { SlackApprovalPreview } from './previews/SlackApprovalPreview';
import { TelegramKeyboardPreview } from './previews/TelegramKeyboardPreview';
import { DiscordEmbedPreview } from './previews/DiscordEmbedPreview';
import { WhatsAppBubblePreview } from './previews/WhatsAppBubblePreview';
import { SignalBubblePreview } from './previews/SignalBubblePreview';
import { CliTerminalPreview } from './previews/CliTerminalPreview';

export interface CredentialField {
  key: string;
  label: string;
  placeholder?: string;
  helpText?: string;
}

export interface ChannelPlatform {
  key: string;
  name: string;
  tagline: string;
  brandColor: string;
  /**
   * URL (or data: URI) of the brand silhouette used for tile / Home / list
   * rendering via CSS mask-image. Most brands resolve to simpleicons.org;
   * Slack ships an inline data URI because Slack revoked simpleicons'
   * permission in 2024 and the CDN returns 404 for /slack.
   */
  iconUrl: string;
  preview: ComponentType;
  credentials: CredentialField[];
  setupSteps: string[];
  /** Optional expandable detail revealed by a "show advanced" toggle */
  advancedCredentials?: CredentialField[];
  /** Where the user should go to provision this channel's credentials */
  consoleUrl?: string;
}

const simpleicons = (slug: string) => `https://cdn.simpleicons.org/${slug}`;

/**
 * Inline single-color silhouette of the Slack mark — the canonical
 * four-shape hashtag, flattened into one path. Simple-icons hosted this
 * exact path until 2024; we embed it locally now that Slack revoked the
 * CDN's right to serve it.
 */
const SLACK_ICON_DATA_URI =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="black">' +
      '<path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zM6.313 15.165a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zM8.834 6.313a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zM18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zM17.688 8.834a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312zM15.165 18.956a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zM15.165 17.688a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z"/>' +
      '</svg>'
  );

export const CHANNEL_PLATFORMS: ChannelPlatform[] = [
  {
    key: 'slack',
    name: 'Slack',
    tagline: 'Approval cards, threaded delivery, slash-command triggers.',
    brandColor: '#611f69',
    iconUrl: SLACK_ICON_DATA_URI,
    preview: SlackApprovalPreview,
    credentials: [
      {
        key: 'bot_token',
        label: 'Bot User OAuth Token',
        placeholder: 'xoxb-…',
        helpText: 'Found at "OAuth & Permissions" after installing your app.',
      },
      {
        key: 'signing_secret',
        label: 'Signing Secret',
        placeholder: '8f2c…',
        helpText: 'Found on "Basic Information" under "App Credentials".',
      },
    ],
    advancedCredentials: [
      {
        key: 'app_token',
        label: 'App-Level Token (Socket Mode)',
        placeholder: 'xapp-…',
        helpText: 'Only required if you want Socket Mode instead of webhooks.',
      },
    ],
    setupSteps: [
      'Create a new Slack app at api.slack.com/apps → "From scratch".',
      'Under "OAuth & Permissions", add bot scopes: chat:write, channels:read, im:write, app_mentions:read.',
      'Click "Install to Workspace" and copy the Bot User OAuth Token (xoxb-…).',
      'On "Basic Information", copy the Signing Secret and paste both below.',
    ],
    consoleUrl: 'https://api.slack.com/apps',
  },
  {
    key: 'telegram',
    name: 'Telegram',
    tagline: 'DM your bot to trigger runs. Inline buttons for approvals.',
    brandColor: '#229ED9',
    iconUrl: simpleicons('telegram'),
    preview: TelegramKeyboardPreview,
    credentials: [
      {
        key: 'bot_token',
        label: 'Bot Token',
        placeholder: '123456:ABC-DEF…',
        helpText: 'Issued by @BotFather when you create a new bot.',
      },
    ],
    setupSteps: [
      'Open Telegram and message @BotFather.',
      'Send /newbot, choose a name, then a username ending in "bot".',
      'BotFather replies with an HTTP API token — paste it below.',
      'After saving, message your new bot once to start a chat thread.',
    ],
    consoleUrl: 'https://t.me/BotFather',
  },
  {
    key: 'discord',
    name: 'Discord',
    tagline: 'Embed-rich approvals, slash commands, server-wide delivery.',
    brandColor: '#5865F2',
    iconUrl: simpleicons('discord'),
    preview: DiscordEmbedPreview,
    credentials: [
      {
        key: 'bot_token',
        label: 'Bot Token',
        placeholder: 'MTI…',
        helpText: 'Found under "Bot" → "Reset Token" in your Discord application.',
      },
      {
        key: 'application_id',
        label: 'Application ID',
        placeholder: '1234567890…',
        helpText: 'Found on the "General Information" page.',
      },
      {
        key: 'public_key',
        label: 'Public Key',
        placeholder: 'a1b2c3…',
        helpText: 'Found on the "General Information" page below the App ID.',
      },
    ],
    setupSteps: [
      'Visit discord.com/developers/applications and create a new application.',
      'Open the "Bot" tab, click "Reset Token", and copy the new token.',
      'Copy the Application ID and Public Key from "General Information".',
      'Use the OAuth2 URL Generator to invite the bot to your server with bot + applications.commands scopes.',
    ],
    consoleUrl: 'https://discord.com/developers/applications',
  },
  {
    key: 'whatsapp',
    name: 'WhatsApp',
    tagline: 'Cloud API delivery with quick-reply approval buttons.',
    brandColor: '#25D366',
    iconUrl: simpleicons('whatsapp'),
    preview: WhatsAppBubblePreview,
    credentials: [
      {
        key: 'access_token',
        label: 'Access Token',
        placeholder: 'EAAB…',
        helpText: 'System-user token from Meta Business → WhatsApp Business API.',
      },
      {
        key: 'phone_number_id',
        label: 'Phone Number ID',
        placeholder: '1234567890',
        helpText: 'Found in WhatsApp Business → API Setup → Phone numbers.',
      },
    ],
    setupSteps: [
      'In Meta Business Manager, set up a WhatsApp Business account.',
      'Add a phone number and complete verification.',
      'Generate a system-user access token with whatsapp_business_messaging scope.',
      'Copy the access token and the phone number ID from API Setup.',
    ],
    consoleUrl: 'https://business.facebook.com/wa/manage',
  },
  {
    key: 'signal',
    name: 'Signal',
    tagline: 'Self-hosted signal-cli REST. End-to-end encrypted delivery.',
    brandColor: '#3a76f0',
    iconUrl: simpleicons('signal'),
    preview: SignalBubblePreview,
    credentials: [
      {
        key: 'signal_cli_url',
        label: 'signal-cli REST URL',
        placeholder: 'http://signal-cli.local:8080',
        helpText: 'URL of your self-hosted signal-cli REST API.',
      },
      {
        key: 'phone_number',
        label: 'Phone Number',
        placeholder: '+15551234567',
        helpText: 'The phone number registered with signal-cli.',
      },
    ],
    setupSteps: [
      'Run signal-cli-rest-api in your network (Docker image: bbernhard/signal-cli-rest-api).',
      'Register a phone number with signal-cli register +<number>.',
      'Verify with the SMS code: signal-cli verify +<number> <code>.',
      'Paste the REST URL and phone number below.',
    ],
    consoleUrl: 'https://github.com/bbernhard/signal-cli-rest-api',
  },
  {
    key: 'cli',
    name: 'CLI',
    tagline: 'Approve from your terminal. Watch runs without leaving the shell.',
    brandColor: '#22c55e',
    iconUrl: simpleicons('gnubash'),
    preview: CliTerminalPreview,
    credentials: [],
    setupSteps: [
      'Install the Tesslate CLI: curl -fsSL https://tesslate.com/install.sh | sh.',
      'Authenticate: ts auth login.',
      'Watch approvals live: ts approvals watch.',
      'No tokens to paste — the CLI uses your existing Tesslate session.',
    ],
  },
];

export function getPlatform(key: string): ChannelPlatform | undefined {
  return CHANNEL_PLATFORMS.find((p) => p.key === key.toLowerCase());
}
