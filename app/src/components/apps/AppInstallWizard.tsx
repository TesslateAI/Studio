/**
 * AppInstallWizard — thin delegate to the new `AppInstallModal`.
 *
 * The Phase 5 rewrite collapsed the multi-step wizard into a single
 * review screen with collapsible advanced sections (UX surface #3 in
 * the plan). Existing import sites (`pages/Marketplace.tsx`,
 * `pages/AppsMarketplacePage.tsx`, `pages/AppDetailPage.tsx`,
 * `__tests__/...`) still import `AppInstallWizard` by name; we
 * preserve the symbol as a forwarding wrapper so nothing has to be
 * touched at the call sites.
 *
 * The new surface lives in `./AppInstallModal.tsx`. Update tests and
 * call sites to import from there directly when convenient.
 */
import { AppInstallModal, type AppInstallModalProps } from './AppInstallModal';

export type AppInstallWizardProps = AppInstallModalProps;

export function AppInstallWizard(props: AppInstallWizardProps) {
  return <AppInstallModal {...props} />;
}

export default AppInstallWizard;
