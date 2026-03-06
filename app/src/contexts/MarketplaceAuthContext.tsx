import { createContext, useContext } from 'react';

interface MarketplaceAuthContextValue {
  isAuthenticated: boolean;
  isLoading: boolean;
}

/**
 * Context for sharing marketplace auth state
 * Provided by MarketplaceLayout, consumed by marketplace pages/components
 *
 * This avoids duplicate auth checks - the layout determines auth state once,
 * and all children can access it without additional API calls
 */
export const MarketplaceAuthContext = createContext<MarketplaceAuthContextValue>({
  isAuthenticated: false,
  isLoading: true,
});

/**
 * Hook to access marketplace auth state
 * Use this in marketplace pages and components to determine:
 * - Whether to show "Install" vs "Sign Up" buttons
 * - Whether to show authenticated-only features
 */
export function useMarketplaceAuth(): MarketplaceAuthContextValue {
  return useContext(MarketplaceAuthContext);
}

export default MarketplaceAuthContext;
