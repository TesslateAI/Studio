/**
 * Feature flag hooks.
 *
 * Separated from FeatureFlagContext.tsx for react-refresh compatibility.
 */

import { useContext } from 'react';
import { FeatureFlagContext, type FeatureFlagContextValue } from './featureFlagState';

/**
 * Get a single feature flag value. Returns false while loading or if unknown.
 */
export function useFeatureFlag(flag: string): boolean {
  const { flags } = useContext(FeatureFlagContext);
  return flags[flag] ?? false;
}

/**
 * Get all feature flags and metadata.
 */
export function useFeatureFlags(): FeatureFlagContextValue {
  return useContext(FeatureFlagContext);
}
