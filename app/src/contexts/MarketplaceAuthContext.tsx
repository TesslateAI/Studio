import { createContext, useContext } from 'react';
import type { MarketplaceSourceResponse } from '../lib/api';

/**
 * Marketplace context shared across the marketplace surface.
 *
 * - Auth state: provided by {@link MarketplaceLayout} so child pages do not
 *   re-check authentication on every mount.
 * - Federated sources (Wave 5): the user-visible source list (system + user
 *   + team) plus the currently selected filter handle. ``null`` means
 *   "All sources" — the merged view across every visible source.
 *
 * Defaults below are intentionally inert so unauthenticated public views
 * still render without a provider in the tree.
 */
export interface MarketplaceAuthContextValue {
  isAuthenticated: boolean;
  isLoading: boolean;
  /** Sources visible to the requester. Empty when unauthenticated or still loading. */
  sources: MarketplaceSourceResponse[];
  /** True while the source list is in flight on first authenticated load. */
  sourcesLoading: boolean;
  /** Last error from /api/marketplace/sources, if any. */
  sourcesError: string | null;
  /** Currently selected source handle, or null for "All sources". */
  selectedSource: string | null;
  setSelectedSource: (handle: string | null) => void;
  /** Force a refetch of the sources list (e.g. after settings page changes). */
  refreshSources: () => Promise<void>;
}

// eslint-disable-next-line react-refresh/only-export-components
export const MarketplaceAuthContext = createContext<MarketplaceAuthContextValue>({
  isAuthenticated: false,
  isLoading: true,
  sources: [],
  sourcesLoading: false,
  sourcesError: null,
  selectedSource: null,
  setSelectedSource: () => {},
  refreshSources: async () => {},
});

/**
 * Hook to access marketplace auth + source state. Must be consumed under a
 * {@link MarketplaceAuthContext.Provider}; callers outside the marketplace
 * tree get inert defaults (auth=false, no sources).
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useMarketplaceAuth(): MarketplaceAuthContextValue {
  return useContext(MarketplaceAuthContext);
}

export default MarketplaceAuthContext;
