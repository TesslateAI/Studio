import { GitBranch } from 'lucide-react';

interface ArchitecturePanelProps {
  projectId: number;
}

export function ArchitecturePanel({ projectId }: ArchitecturePanelProps) {
  return (
    <div className="h-full overflow-y-auto">
      <div className="panel-section p-6">
        <div className="bg-white/5 border border-white/10 rounded-lg p-4 overflow-x-auto">
          <pre className="text-xs text-gray-300 font-mono">
{`graph TD
    A[User] --> B[Frontend]
    B --> C[API Layer]
    C --> D[Database]
    C --> E[Auth Service]
    B --> F[CDN]`}
          </pre>
        </div>
        <p className="text-xs text-gray-500 mt-4">
          Mermaid diagram showing your app architecture
        </p>
      </div>
    </div>
  );
}
