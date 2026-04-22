import { InfoState } from './EmptyStates';

interface OverviewTabProps {
  projectSlug: string;
}

// Placeholder — real implementation lands in a follow-up commit.
// Referenced by the RepositoryPanel shell so the tab switcher stays wired.
export function OverviewTab({ projectSlug: _projectSlug }: OverviewTabProps) {
  return <InfoState title="Overview coming soon." />;
}
