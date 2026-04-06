/**
 * Feature Flag Provider
 *
 * Consumes the prefetched feature flags promise from api.ts.
 * The fetch fires at module load time (before React mounts), so by the
 * time the provider renders the response is usually already available.
 *
 * Context + types: featureFlagState.ts
 * Hooks: useFeatureFlag.ts
 */

import { useEffect, useState, type ReactNode } from 'react';
import { featureFlagsApi, type FeatureFlagsResponse } from '../lib/api';
import { FeatureFlagContext, type FeatureFlagContextValue } from './featureFlagState';

export function FeatureFlagProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<FeatureFlagContextValue>({
    flags: {},
    env: '',
    loading: true,
  });

  useEffect(() => {
    let cancelled = false;

    featureFlagsApi.getFlags().then((data: FeatureFlagsResponse) => {
      if (!cancelled) {
        setState({ flags: data.flags, env: data.env, loading: false });
      }
    });

    return () => {
      cancelled = true;
    };
  }, []);

  return <FeatureFlagContext.Provider value={state}>{children}</FeatureFlagContext.Provider>;
}
