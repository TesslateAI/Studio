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
