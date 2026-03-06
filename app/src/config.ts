/**
 * Runtime Configuration
 *
 * This config reads from window._env_ which is injected by nginx at container startup.
 * In development mode, it falls back to import.meta.env (Vite's .env files).
 *
 * This allows us to:
 * - Build ONE Docker image for all environments
 * - Inject different configs at runtime via K8s ConfigMaps
 * - No rebuild needed for config changes
 */

interface RuntimeEnv {
  API_URL: string;
  POSTHOG_KEY: string;
  POSTHOG_HOST: string;
}

declare global {
  interface Window {
    _env_?: RuntimeEnv;
  }
}

/**
 * Application configuration with runtime environment variable support
 */
export const config = {
  /**
   * API base URL - injected at runtime by nginx or from .env in dev
   * Uses nullish coalescing (??) to allow empty strings (unlike ||)
   */
  API_URL: window._env_?.API_URL ?? import.meta.env.VITE_API_URL ?? 'http://localhost:8000',

  /**
   * PostHog analytics key - injected at runtime or from .env in dev
   * Empty string disables analytics
   */
  POSTHOG_KEY: window._env_?.POSTHOG_KEY ?? import.meta.env.VITE_PUBLIC_POSTHOG_KEY ?? '',

  /**
   * PostHog host URL - injected at runtime or from .env in dev
   */
  POSTHOG_HOST:
    window._env_?.POSTHOG_HOST ??
    import.meta.env.VITE_PUBLIC_POSTHOG_HOST ??
    'https://app.posthog.com',
} as const;

// Validate and log config
if (import.meta.env.DEV) {
  // Development mode: log config source
  console.log('[Config] Using runtime config:', {
    API_URL: config.API_URL,
    POSTHOG_KEY: config.POSTHOG_KEY ? '***' : '(empty)',
    POSTHOG_HOST: config.POSTHOG_HOST,
    source: window._env_ ? 'window._env_ (runtime)' : 'import.meta.env (dev)',
  });
} else if (!window._env_) {
  // Production mode: warn if runtime config failed to load
  console.warn(
    '[Config] Runtime config (window._env_) not found! ' +
      'This may indicate /config.js failed to load. ' +
      'Check nginx logs and verify the entrypoint script ran correctly. ' +
      'Using fallback values from build time.',
    {
      API_URL: config.API_URL,
      POSTHOG_KEY: config.POSTHOG_KEY ? '***' : '(empty)',
      POSTHOG_HOST: config.POSTHOG_HOST,
    }
  );
}
