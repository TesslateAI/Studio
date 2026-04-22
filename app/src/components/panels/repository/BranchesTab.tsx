import { InfoState } from './EmptyStates';

interface BranchesTabProps {
  projectSlug: string;
}

// Placeholder — real implementation lands in a follow-up commit.
export function BranchesTab({ projectSlug: _projectSlug }: BranchesTabProps) {
  return <InfoState title="Branches coming soon." />;
}
