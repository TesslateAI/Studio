/**
 * Centralized deployment provider configuration.
 *
 * Single source of truth for provider icons, colors, and display names.
 * All components rendering provider info should import from here.
 */

export interface ProviderConfig {
  icon: string;
  displayName: string;
  color: string;
  textColor: string;
}

/**
 * Helper to determine if text should be light or dark on a given background.
 * Uses relative luminance formula.
 */
function shouldUseDarkText(hex: string): boolean {
  const c = hex.replace('#', '');
  const r = parseInt(c.substring(0, 2), 16);
  const g = parseInt(c.substring(2, 4), 16);
  const b = parseInt(c.substring(4, 6), 16);
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance > 0.6;
}

export const DEPLOYMENT_PROVIDERS: Record<string, ProviderConfig> = {
  vercel: { icon: '▲', displayName: 'Vercel', color: '#000000', textColor: 'text-white' },
  netlify: { icon: '◆', displayName: 'Netlify', color: '#00C7B7', textColor: 'text-white' },
  cloudflare: { icon: '🔥', displayName: 'Cloudflare Pages', color: '#F38020', textColor: 'text-white' },
  digitalocean: { icon: '🌊', displayName: 'DigitalOcean App Platform', color: '#0080FF', textColor: 'text-white' },
  railway: { icon: '🚂', displayName: 'Railway', color: '#0B0D0E', textColor: 'text-white' },
  fly: { icon: '✈️', displayName: 'Fly.io', color: '#7B3FE4', textColor: 'text-white' },
  heroku: { icon: '🟣', displayName: 'Heroku', color: '#430098', textColor: 'text-white' },
  render: { icon: '🔷', displayName: 'Render', color: '#46E3B7', textColor: 'text-white' },
  koyeb: { icon: '🟢', displayName: 'Koyeb', color: '#121212', textColor: 'text-white' },
  zeabur: { icon: '⚡', displayName: 'Zeabur', color: '#6C5CE7', textColor: 'text-white' },
  northflank: { icon: '🔶', displayName: 'Northflank', color: '#01E277', textColor: 'text-white' },
  'github-pages': { icon: '📄', displayName: 'GitHub Pages', color: '#222222', textColor: 'text-white' },
  surge: { icon: '🌊', displayName: 'Surge', color: '#D93472', textColor: 'text-white' },
  'deno-deploy': { icon: '🦕', displayName: 'Deno Deploy', color: '#000000', textColor: 'text-white' },
  firebase: { icon: '🔥', displayName: 'Firebase Hosting', color: '#FFCA28', textColor: 'text-black' },
  'aws-apprunner': { icon: '☁️', displayName: 'AWS App Runner', color: '#FF9900', textColor: 'text-white' },
  'gcp-cloudrun': { icon: '☁️', displayName: 'GCP Cloud Run', color: '#4285F4', textColor: 'text-white' },
  'azure-container-apps': { icon: '☁️', displayName: 'Azure Container Apps', color: '#0078D4', textColor: 'text-white' },
  'do-container': { icon: '🌊', displayName: 'DO Container Apps', color: '#0080FF', textColor: 'text-white' },
  dockerhub: { icon: '🐳', displayName: 'Docker Hub', color: '#2496ED', textColor: 'text-white' },
  ghcr: { icon: '📦', displayName: 'GitHub Container Registry', color: '#222222', textColor: 'text-white' },
  download: { icon: '💾', displayName: 'Download / Export', color: '#6B7280', textColor: 'text-white' },
};

/** Get provider config with fallback defaults. */
export function getProviderConfig(provider: string): ProviderConfig {
  return DEPLOYMENT_PROVIDERS[provider] ?? {
    icon: '🚀',
    displayName: provider.charAt(0).toUpperCase() + provider.slice(1),
    color: '#6B7280',
    textColor: 'text-white',
  };
}

/** Get just the icon for a provider. */
export function getProviderIcon(provider: string): string {
  return getProviderConfig(provider).icon;
}

/** Get just the hex color for a provider. */
export function getProviderColor(provider: string): string {
  return getProviderConfig(provider).color;
}

/** Get the display name for a provider. */
export function getProviderDisplayName(provider: string): string {
  return getProviderConfig(provider).displayName;
}

/**
 * Per-field credential help: tells users where to find each value.
 * Keys are provider names, values map field names → help strings.
 */
export const PROVIDER_CREDENTIAL_HELP: Record<string, Record<string, string>> = {
  vercel: {
    token: 'Go to vercel.com → Settings → Tokens → Create Token.',
    team_id: 'Found in your Vercel team Settings → General → "Team ID" field. Leave blank for personal account.',
  },
  netlify: {
    token: 'Go to app.netlify.com → User Settings → Applications → Personal access tokens → New access token.',
  },
  cloudflare: {
    api_token: 'Go to dash.cloudflare.com → My Profile → API Tokens → Create Token. Use the "Edit Cloudflare Workers" template or create a custom token with Workers permissions.',
    account_id: 'Found on the right side of your Cloudflare dashboard Overview page, under "Account ID".',
    dispatch_namespace: 'Optional. Only needed for Workers for Platforms. Found in Workers & Pages → Dispatch Namespaces.',
  },
  heroku: {
    api_key: 'Go to dashboard.heroku.com → Account Settings → scroll to "API Key" → Reveal and copy.',
  },
  railway: {
    token: 'Go to railway.app → Account Settings → Tokens → Create Token.',
  },
  render: {
    api_key: 'Go to dashboard.render.com → Account Settings → API Keys → Create API Key.',
  },
  koyeb: {
    api_token: 'Go to app.koyeb.com → Account → API → Create API Access Token.',
    org_slug: 'Optional. Your Koyeb organization slug, visible in your organization URL (app.koyeb.com/org/<slug>).',
  },
  zeabur: {
    api_key: 'Go to zeabur.com → Settings → Developer → Generate API Key.',
  },
  surge: {
    email: 'The email address you used to register with Surge.sh.',
    token: 'Run "surge token" in your terminal to retrieve your token, or check your ~/.netrc file.',
  },
  'deno-deploy': {
    token: 'Go to dash.deno.com → Account Settings → Access Tokens → New Access Token.',
    org_id: 'Found in your Deno Deploy dashboard URL: dash.deno.com/orgs/<org_id>.',
  },
  firebase: {
    service_account_json: 'Go to Firebase Console → Project Settings → Service accounts → "Generate new private key". Paste the entire JSON contents.',
    site_id: 'Go to Firebase Console → Hosting → your site ID is shown at the top (e.g., "my-app-12345"). This is the subdomain of your .web.app URL.',
  },
  northflank: {
    api_token: 'Go to app.northflank.com → Account → API → Create new API token.',
    org_slug: 'Optional. Your Northflank team slug, found in the URL: app.northflank.com/t/<slug>.',
  },
  'github-pages': {
    token: 'Go to github.com → Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token. Enable "repo" scope.',
  },
  digitalocean: {
    api_token: 'Go to cloud.digitalocean.com → API → Tokens → Generate New Token. Enable both read and write scopes.',
    registry_name: 'Optional. Your DigitalOcean Container Registry name, found at cloud.digitalocean.com → Container Registry.',
  },
  'aws-apprunner': {
    aws_access_key_id: 'Go to AWS Console → IAM → Users → your user → Security credentials → Create access key. Select "Application running outside AWS" use case.',
    aws_secret_access_key: 'Shown once when you create the access key in IAM. Copy it immediately — it cannot be retrieved later.',
    aws_region: 'The AWS region for deployment (e.g., us-east-1). See the region selector in the top-right of the AWS Console.',
  },
  'gcp-cloudrun': {
    service_account_json: 'Go to GCP Console → IAM & Admin → Service Accounts → select or create an account → Keys → Add Key → Create new key → JSON. Paste the full JSON contents.',
    gcp_region: 'The GCP region for deployment (e.g., us-central1). See cloud.google.com/run/docs/locations for available regions.',
  },
  'azure-container-apps': {
    client_secret: 'Go to Azure Portal → Microsoft Entra ID → App registrations → your app → Certificates & secrets → New client secret.',
    tenant_id: 'Found in Azure Portal → Microsoft Entra ID → Overview → "Tenant ID".',
    client_id: 'Found in Azure Portal → Microsoft Entra ID → App registrations → your app → Overview → "Application (client) ID".',
    subscription_id: 'Go to Azure Portal → Subscriptions → copy the Subscription ID.',
    resource_group: 'The name of the resource group for deployment. Found at Azure Portal → Resource groups.',
    registry_name: 'Your Azure Container Registry name (e.g., "myregistry"). Found at Azure Portal → Container registries.',
    azure_region: 'The Azure region for deployment (e.g., eastus). See the location column in Azure Portal → Resource groups.',
  },
  'do-container': {
    api_token: 'Go to cloud.digitalocean.com → API → Tokens → Generate New Token with read and write scopes.',
    registry_name: 'Your DigitalOcean Container Registry name, found at cloud.digitalocean.com → Container Registry.',
  },
  fly: {
    api_token: 'Run "fly tokens create deploy" in your terminal, or go to fly.io → Account → Access Tokens → Create Token.',
    org_slug: 'Optional. Your Fly.io organization slug, visible at fly.io/dashboard → select your org from the dropdown.',
  },
  dockerhub: {
    username: 'Your Docker Hub username. Found at hub.docker.com when logged in (top-right profile menu).',
    token: 'Go to hub.docker.com → Account Settings → Security → New Access Token. Use "Read & Write" permissions.',
  },
  ghcr: {
    username: 'Your GitHub username (the one you log in with at github.com).',
    token: 'Go to github.com → Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token. Enable "write:packages" and "read:packages" scopes.',
  },
  download: {},
};

/** Get Tailwind bg color class from hex. */
export function getProviderBgClass(provider: string): string {
  const config = getProviderConfig(provider);
  return `bg-[${config.color}]`;
}

/** Get text color class (light or dark) based on provider brand color. */
export function getProviderTextClass(provider: string): string {
  const config = getProviderConfig(provider);
  return shouldUseDarkText(config.color) ? 'text-black' : 'text-white';
}
