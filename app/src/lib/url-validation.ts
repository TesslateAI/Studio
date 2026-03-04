/**
 * URL Validation utilities to prevent Open Redirect vulnerabilities
 *
 * Architecture:
 * - Default domains are defined here as a baseline
 * - Additional domains can be loaded from backend config via loadAllowedDomains()
 * - Backend should also validate URLs before returning them (defense in depth)
 */

// Default allowed domains - can be extended via loadAllowedDomains()
const DEFAULT_OAUTH_DOMAINS = [
  'github.com',
  'gitlab.com',
  'bitbucket.org',
  'vercel.com',
  'netlify.com',
  'api.netlify.com',
  'dash.cloudflare.com',
  'accounts.google.com',
  'login.microsoftonline.com',
];

const DEFAULT_CHECKOUT_DOMAINS = [
  'checkout.stripe.com',
  'billing.stripe.com',
];

const DEFAULT_DEPLOYMENT_DOMAINS = [
  'vercel.app',
  'netlify.app',
  'pages.dev',  // Cloudflare Pages
  'workers.dev', // Cloudflare Workers
];

// Allowed Git provider domains for clone URLs
const GIT_PROVIDER_DOMAINS = [
  'github.com',
  'gitlab.com',
  'bitbucket.org',
];

// Runtime domain lists - initialized with defaults, can be extended
let allowedOAuthDomains = [...DEFAULT_OAUTH_DOMAINS];
let allowedCheckoutDomains = [...DEFAULT_CHECKOUT_DOMAINS];
let allowedDeploymentDomains = [...DEFAULT_DEPLOYMENT_DOMAINS];

/**
 * Configuration for allowed domains - can be loaded from backend
 */
export interface AllowedDomainsConfig {
  oauth?: string[];
  checkout?: string[];
  deployment?: string[];
}

/**
 * Load additional allowed domains from backend configuration.
 * Called during app initialization in App.tsx with domains fetched from:
 *   - /api/config (app_domain for deployment-specific URLs)
 *   - /api/deployment-credentials/providers (OAuth + deployment domains)
 *   - /api/billing/config (checkout domains)
 *
 * Merges provided domains with hardcoded defaults (dedup via Set).
 */
export function loadAllowedDomains(config: AllowedDomainsConfig): void {
  if (config.oauth) {
    // Merge with defaults, avoiding duplicates
    allowedOAuthDomains = [...new Set([...DEFAULT_OAUTH_DOMAINS, ...config.oauth])];
  }
  if (config.checkout) {
    allowedCheckoutDomains = [...new Set([...DEFAULT_CHECKOUT_DOMAINS, ...config.checkout])];
  }
  if (config.deployment) {
    allowedDeploymentDomains = [...new Set([...DEFAULT_DEPLOYMENT_DOMAINS, ...config.deployment])];
  }
}

/**
 * Get current allowed domains (for debugging/display purposes)
 */
export function getAllowedDomains(): AllowedDomainsConfig {
  return {
    oauth: [...allowedOAuthDomains],
    checkout: [...allowedCheckoutDomains],
    deployment: [...allowedDeploymentDomains],
  };
}

/**
 * Validates that a URL is safe for OAuth redirect
 * Only allows URLs from known OAuth provider domains
 */
export function isValidOAuthUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    // Must be HTTPS for security
    if (parsed.protocol !== 'https:') {
      return false;
    }
    // Check if hostname ends with an allowed OAuth domain
    return allowedOAuthDomains.some((domain: string) =>
      parsed.hostname === domain || parsed.hostname.endsWith('.' + domain)
    );
  } catch {
    return false;
  }
}

/**
 * Validates that a URL is safe for checkout redirect
 * Only allows URLs from known payment provider domains
 */
export function isValidCheckoutUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    // Must be HTTPS for security
    if (parsed.protocol !== 'https:') {
      return false;
    }
    // Check if hostname ends with an allowed checkout domain
    return allowedCheckoutDomains.some((domain: string) =>
      parsed.hostname === domain || parsed.hostname.endsWith('.' + domain)
    );
  } catch {
    return false;
  }
}

/**
 * Validates that a URL is safe for deployment redirect
 * Only allows URLs from known deployment provider domains
 */
export function isValidDeploymentUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    // Must be HTTPS for security
    if (parsed.protocol !== 'https:') {
      return false;
    }
    // Check if hostname ends with an allowed deployment domain
    return allowedDeploymentDomains.some((domain: string) =>
      parsed.hostname === domain || parsed.hostname.endsWith('.' + domain)
    );
  } catch {
    return false;
  }
}

/**
 * Validates that a URL is a valid Git repository clone URL
 * Only allows URLs from known Git hosting providers
 */
export function isValidGitCloneUrl(url: string): boolean {
  try {
    // Handle SSH URLs (git@host:owner/repo.git)
    const sshPattern = /^git@([\w.-]+):[\w.-]+\/[\w.-]+(?:\.git)?$/;
    const sshMatch = url.match(sshPattern);
    if (sshMatch) {
      const host = sshMatch[1];
      return GIT_PROVIDER_DOMAINS.some((domain) => host === domain);
    }

    // Handle HTTPS URLs
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:') {
      return false;
    }
    return GIT_PROVIDER_DOMAINS.some((domain: string) =>
      parsed.hostname === domain || parsed.hostname.endsWith('.' + domain)
    );
  } catch {
    return false;
  }
}

/**
 * Validates that a path is safe for internal navigation
 * Prevents redirects to external URLs via javascript:, data:, or absolute URLs
 */
export function isValidInternalPath(path: string | null | undefined): boolean {
  if (!path) {
    return false;
  }

  // Must start with / for relative path
  if (!path.startsWith('/')) {
    return false;
  }

  // Must not start with // (protocol-relative URL that could redirect externally)
  if (path.startsWith('//')) {
    return false;
  }

  // Must not contain : before the first / (prevents javascript:, data:, http:, etc.)
  const colonIndex = path.indexOf(':');
  const slashIndex = path.indexOf('/', 1); // Skip the first /
  if (colonIndex !== -1 && (slashIndex === -1 || colonIndex < slashIndex)) {
    return false;
  }

  // Check for URL-encoded versions of dangerous characters
  const decodedPath = decodeURIComponent(path);
  if (decodedPath !== path) {
    // Re-validate the decoded path
    if (!decodedPath.startsWith('/') || decodedPath.startsWith('//')) {
      return false;
    }
    const decodedColon = decodedPath.indexOf(':');
    const decodedSlash = decodedPath.indexOf('/', 1);
    if (decodedColon !== -1 && (decodedSlash === -1 || decodedColon < decodedSlash)) {
      return false;
    }
  }

  return true;
}

/**
 * Sanitizes an internal path, returning a safe default if invalid
 */
export function sanitizeInternalPath(path: string | null | undefined, defaultPath: string = '/dashboard'): string {
  if (isValidInternalPath(path)) {
    return path!;
  }
  return defaultPath;
}
