import { MarkerPill } from './MarkerPill';

export interface Marker {
  key: string;
  label: string;
  category: 'system' | 'project' | 'tool';
  description: string;
}

interface MarkerPaletteProps {
  onInsertMarker: (marker: string) => void;
}

export const AVAILABLE_MARKERS: Marker[] = [
  // System markers
  { key: 'mode', label: 'Edit Mode', category: 'system', description: 'Current edit mode (allow/ask/plan)' },
  { key: 'mode_instructions', label: 'Mode Instructions', category: 'system', description: 'Detailed instructions for current mode' },
  { key: 'timestamp', label: 'Timestamp', category: 'system', description: 'Current ISO timestamp' },

  // Project markers
  { key: 'project_name', label: 'Project Name', category: 'project', description: 'Name of the current project' },
  { key: 'project_description', label: 'Project Description', category: 'project', description: 'Project description' },
  { key: 'project_path', label: 'Project Path', category: 'project', description: 'Project directory path' },
  { key: 'git_branch', label: 'Git Branch', category: 'project', description: 'Current git branch' },

  // Tool markers
  { key: 'tool_list', label: 'Tool List', category: 'tool', description: 'Comma-separated list of available tools' },
];

export function MarkerPalette({ onInsertMarker }: MarkerPaletteProps) {
  const systemMarkers = AVAILABLE_MARKERS.filter(m => m.category === 'system');
  const projectMarkers = AVAILABLE_MARKERS.filter(m => m.category === 'project');
  const toolMarkers = AVAILABLE_MARKERS.filter(m => m.category === 'tool');

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <h4 className="text-xs font-semibold text-[var(--text)]/60 uppercase tracking-wider">
          System Markers
        </h4>
        <div className="flex flex-wrap gap-2">
          {systemMarkers.map((marker) => (
            <MarkerPill
              key={marker.key}
              marker={marker.key}
              label={marker.label}
              category={marker.category}
              description={marker.description}
              onClick={() => onInsertMarker(marker.key)}
            />
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <h4 className="text-xs font-semibold text-[var(--text)]/60 uppercase tracking-wider">
          Project Markers
        </h4>
        <div className="flex flex-wrap gap-2">
          {projectMarkers.map((marker) => (
            <MarkerPill
              key={marker.key}
              marker={marker.key}
              label={marker.label}
              category={marker.category}
              description={marker.description}
              onClick={() => onInsertMarker(marker.key)}
            />
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <h4 className="text-xs font-semibold text-[var(--text)]/60 uppercase tracking-wider">
          Tool Markers
        </h4>
        <div className="flex flex-wrap gap-2">
          {toolMarkers.map((marker) => (
            <MarkerPill
              key={marker.key}
              marker={marker.key}
              label={marker.label}
              category={marker.category}
              description={marker.description}
              onClick={() => onInsertMarker(marker.key)}
            />
          ))}
        </div>
      </div>

      <div className="text-xs text-[var(--text)]/50 mt-4 p-3 bg-[var(--text)]/5 rounded-lg border border-[var(--text)]/10">
        <p className="font-semibold mb-1">How to use markers:</p>
        <p>Click any marker above to insert it at the cursor position in your system prompt. Markers are replaced with actual values when the agent runs.</p>
      </div>
    </div>
  );
}
