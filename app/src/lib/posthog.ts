import posthog from 'posthog-js'

// Singleton flags to prevent multiple initializations
let isInitialized = false
let initializationError: Error | null = null

/**
 * Check if user has Do Not Track enabled
 */
function isDoNotTrackEnabled(): boolean {
  if (typeof navigator === 'undefined') return false

  const dnt =
    navigator.doNotTrack === '1' ||
    (navigator as Navigator & { msDoNotTrack?: string }).msDoNotTrack === '1' ||
    (window as Window & { doNotTrack?: string }).doNotTrack === '1'

  return dnt
}

/**
 * Check if PostHog should be initialized
 */
function shouldInitialize(): boolean {
  // Check for API key
  const apiKey = import.meta.env.VITE_PUBLIC_POSTHOG_KEY
  if (!apiKey) {
    console.debug('[PostHog] No API key configured, skipping initialization')
    return false
  }

  // Respect Do Not Track
  if (isDoNotTrackEnabled()) {
    console.debug('[PostHog] Do Not Track enabled, skipping initialization')
    return false
  }

  // Check for development mode opt-out
  if (import.meta.env.DEV && import.meta.env.VITE_DISABLE_ANALYTICS === 'true') {
    console.debug('[PostHog] Analytics disabled in development')
    return false
  }

  return true
}

/**
 * Initialize PostHog analytics - safe to call multiple times, only initializes once.
 * Returns the posthog instance or null if not configured/disabled.
 *
 * Features:
 * - Respects Do Not Track (DNT) browser setting
 * - Skips initialization if no API key configured
 * - Handles initialization errors gracefully (non-blocking)
 * - Singleton pattern prevents multiple initializations
 */
export function initPostHog(): typeof posthog | null {
  // Return early if already attempted initialization
  if (isInitialized) {
    return initializationError ? null : posthog
  }

  // Check if should initialize
  if (!shouldInitialize()) {
    isInitialized = true // Mark as "done" to prevent retry
    return null
  }

  try {
    const apiKey = import.meta.env.VITE_PUBLIC_POSTHOG_KEY
    const host = import.meta.env.VITE_PUBLIC_POSTHOG_HOST

    posthog.init(apiKey, {
      api_host: host || 'https://app.posthog.com',
      autocapture: true,
      capture_pageview: true,
      capture_pageleave: true,
      disable_session_recording: false,
      // Prevent loading in iframes (security)
      disable_external_dependency_loading: false,
      // Respect user privacy settings
      respect_dnt: true,
      // Batch events for better performance
      request_batching: true,
      // Handle initialization completion
      loaded: () => {
        console.debug('[PostHog] Initialized successfully')
      },
    })

    isInitialized = true
    return posthog
  } catch (error) {
    console.warn('[PostHog] Initialization failed (non-blocking):', error)
    initializationError = error as Error
    isInitialized = true // Prevent retry loops
    return null
  }
}

/**
 * Get the PostHog instance. Returns null if not initialized or initialization failed.
 */
export function getPostHog(): typeof posthog | null {
  if (!isInitialized || initializationError) {
    return null
  }
  return posthog
}

/**
 * Check if PostHog is configured (API key present)
 */
export function isPostHogConfigured(): boolean {
  return !!import.meta.env.VITE_PUBLIC_POSTHOG_KEY
}

/**
 * Check if PostHog is available (configured AND initialized without error)
 */
export function isPostHogAvailable(): boolean {
  return isInitialized && !initializationError
}

/**
 * Safe analytics capture that never throws.
 * Use this for fire-and-forget analytics events.
 */
export function capture(event: string, properties?: Record<string, unknown>): void {
  const ph = getPostHog()
  if (ph) {
    try {
      ph.capture(event, properties)
    } catch {
      // Silently fail - analytics should never break the app
    }
  }
}

// Export the raw posthog instance for advanced usage
// but prefer using getPostHog() to ensure initialization
export { posthog }
