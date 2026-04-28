/**
 * Static Block-Kit-styled approval preview rendered on the Slack tile and
 * inside the Slack setup drawer. Mirrors the actual block layout produced by
 * `orchestrator/app/services/channels/approval_cards.py` so the user sees
 * the literal thing they'll get in Slack once connected.
 */
export function SlackApprovalPreview() {
  return (
    <div className="overflow-hidden rounded-md border border-[#dddee1] bg-white text-[#1d1c1d] font-sans text-[12px] leading-tight shadow-sm select-none">
      {/* Channel header — Slack's grey strip */}
      <div className="flex items-center gap-1.5 border-b border-[#e8e8e8] bg-[#f8f8f8] px-3 py-1.5 text-[11px] font-semibold text-[#1d1c1d]">
        <span className="text-[#616061]">#</span>
        <span>standup</span>
      </div>

      {/* Bot message row */}
      <div className="flex gap-2 px-3 py-2.5">
        <div className="flex-shrink-0 h-7 w-7 rounded bg-[#611f69] text-white grid place-items-center text-[10px] font-bold">
          T
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-1.5">
            <span className="font-bold text-[12px]">Tesslate</span>
            <span className="rounded bg-[#e8e8e8] px-1 py-px text-[9px] font-medium text-[#616061]">
              APP
            </span>
            <span className="text-[10px] text-[#616061]">9:14 AM</span>
          </div>
          <div className="mt-0.5 text-[12px] text-[#1d1c1d]">
            <span className="font-semibold">Approval requested</span>
            <span className="text-[#616061]"> · standup-summary</span>
          </div>
          <div className="mt-1 text-[11.5px] text-[#1d1c1d]">
            Run finished — diff ready for review.
          </div>

          {/* Action buttons — Slack Block Kit styling */}
          <div className="mt-2 flex flex-wrap gap-1.5">
            <button
              type="button"
              className="rounded border border-[#007a5a] bg-[#007a5a] px-2.5 py-1 text-[11px] font-bold text-white"
              disabled
            >
              Approve
            </button>
            <button
              type="button"
              className="rounded border border-[#dddee1] bg-white px-2.5 py-1 text-[11px] font-bold text-[#1d1c1d]"
              disabled
            >
              Allow for run
            </button>
            <button
              type="button"
              className="rounded border border-[#e01e5a] bg-white px-2.5 py-1 text-[11px] font-bold text-[#e01e5a]"
              disabled
            >
              Deny
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
