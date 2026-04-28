import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import type { ComponentProps } from 'react';
import type { NavigationSidebar } from '../components/ui/NavigationSidebar';

type BuilderSection = ComponentProps<typeof NavigationSidebar>['builderSection'];

interface BuilderShellContextValue {
  builderSection: BuilderSection;
  setBuilderSection: (section: BuilderSection | undefined) => void;
  isLeftSidebarExpanded: boolean;
  setIsLeftSidebarExpanded: (expanded: boolean) => void;
}

const BuilderShellContext = createContext<BuilderShellContextValue | null>(null);

const SIDEBAR_LS_KEY = 'navigationSidebarExpanded';

function readInitialExpanded(): boolean {
  try {
    const raw = localStorage.getItem(SIDEBAR_LS_KEY);
    if (raw === null) return true;
    return raw === 'true';
  } catch {
    return true;
  }
}

export function BuilderShellProvider({ children }: { children: ReactNode }) {
  // BuilderSection is itself a function (render prop). useState's setter
  // interprets a function arg as an updater and would CALL it on the previous
  // value — wrong for storing a render-prop function. Wrap with the lazy
  // `() => fn` form so React stores the value verbatim.
  const [builderSection, setBuilderSectionRaw] = useState<BuilderSection | undefined>(undefined);
  const setBuilderSection = useCallback((section: BuilderSection | undefined) => {
    setBuilderSectionRaw(() => section);
  }, []);
  const [isLeftSidebarExpanded, setIsLeftSidebarExpanded] = useState<boolean>(() =>
    readInitialExpanded()
  );

  const value = useMemo<BuilderShellContextValue>(
    () => ({
      builderSection,
      setBuilderSection,
      isLeftSidebarExpanded,
      setIsLeftSidebarExpanded,
    }),
    [builderSection, setBuilderSection, isLeftSidebarExpanded]
  );

  return <BuilderShellContext.Provider value={value}>{children}</BuilderShellContext.Provider>;
}

export function useBuilderShell(): BuilderShellContextValue {
  const ctx = useContext(BuilderShellContext);
  if (!ctx) {
    throw new Error('useBuilderShell must be used within BuilderShellProvider');
  }
  return ctx;
}

/** Register the page's `builderSection` render prop with the shared shell.
 * Pages call this on mount; the registration is cleared on unmount so the
 * sidebar reverts to its default chrome on other routes.
 *
 * Note: `setBuilderSection` writes to a useState slot. Since BuilderSection IS
 * a function, we have to use the lazy `() => fn` form — otherwise React
 * interprets the value as a state updater and calls it with the prev state. */
export function useRegisterBuilderSection(section: BuilderSection | undefined) {
  const { setBuilderSection } = useBuilderShell();
  useEffect(() => {
    setBuilderSection(section);
    return () => setBuilderSection(undefined);
  }, [section, setBuilderSection]);
}
