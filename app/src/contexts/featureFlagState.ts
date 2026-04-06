/**
 * Feature flag shared state — context + types.
 * Separated from the provider component for react-refresh compatibility.
 */

import { createContext } from 'react';

export interface FeatureFlagContextValue {
  flags: Record<string, boolean>;
  env: string;
  loading: boolean;
}

export const FeatureFlagContext = createContext<FeatureFlagContextValue>({
  flags: {},
  env: '',
  loading: true,
});
