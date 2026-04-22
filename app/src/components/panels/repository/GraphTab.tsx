import { InfoState } from './EmptyStates';

interface GraphTabProps {
  projectSlug: string;
}

// Placeholder — real implementation lands in a follow-up commit.
export function GraphTab({ projectSlug: _projectSlug }: GraphTabProps) {
  return <InfoState title="Commit graph coming soon." />;
}
