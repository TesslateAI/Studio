import { Check, CheckCircle, XCircle, AlertTriangle } from 'lucide-react';

interface ApprovalRequestCardProps {
  approvalId: string;
  toolName: string;
  toolParameters: any;
  toolDescription: string;
  onRespond: (approvalId: string, response: 'allow_once' | 'allow_all' | 'stop', toolName: string) => void;
}

// Define write tools that should switch mode when "Allow All" is clicked
const WRITE_TOOLS = new Set(['write_file', 'patch_file', 'multi_edit']);

export function ApprovalRequestCard({
  approvalId,
  toolName,
  toolParameters,
  toolDescription,
  onRespond
}: ApprovalRequestCardProps) {
  return (
    <div className="bg-yellow-500/10 border-2 border-yellow-500/30 rounded-lg p-4">
      <div className="flex items-start gap-3 mb-4">
        <AlertTriangle className="w-5 h-5 text-yellow-500 flex-shrink-0 mt-0.5" />
        <div>
          <h4 className="font-semibold text-[var(--text)] mb-1">
            Approval Required
          </h4>
          <p className="text-sm text-[var(--text)]/70 mb-2">
            The agent wants to execute: <code className="font-mono text-xs bg-black/20 px-1 py-0.5 rounded">{toolName}</code>
          </p>
          <p className="text-xs text-[var(--text)]/60">
            {toolDescription}
          </p>
        </div>
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => onRespond(approvalId, 'allow_once', toolName)}
          className="flex-1 px-3 py-2 bg-green-500/20 hover:bg-green-500/30 border border-green-500/40 rounded-lg text-green-500 text-sm font-medium transition-all flex items-center justify-center gap-2"
        >
          <Check className="w-4 h-4" />
          Allow Once
        </button>

        <button
          onClick={() => onRespond(approvalId, 'allow_all', toolName)}
          className="flex-1 px-3 py-2 bg-orange-500/20 hover:bg-orange-500/30 border border-orange-500/40 rounded-lg text-orange-500 text-sm font-medium transition-all flex items-center justify-center gap-2"
        >
          <CheckCircle className="w-4 h-4" />
          {WRITE_TOOLS.has(toolName) ? 'Allow All Edits' : 'Allow Every Time'}
        </button>

        <button
          onClick={() => onRespond(approvalId, 'stop', toolName)}
          className="flex-1 px-3 py-2 bg-red-500/20 hover:bg-red-500/30 border border-red-500/40 rounded-lg text-red-500 text-sm font-medium transition-all flex items-center justify-center gap-2"
        >
          <XCircle className="w-4 h-4" />
          Stop
        </button>
      </div>
    </div>
  );
}
