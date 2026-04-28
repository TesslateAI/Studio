/**
 * Static Discord-style preview — embed with side accent + button row.
 * Mirrors the components/embeds shape Discord renders for bot messages.
 */
export function DiscordEmbedPreview() {
  return (
    <div className="overflow-hidden rounded-md bg-[#313338] p-3 font-sans text-[12px] leading-tight text-[#dbdee1] select-none">
      {/* Bot message header */}
      <div className="flex items-center gap-1.5">
        <div className="h-6 w-6 rounded-full bg-[#5865F2] text-white grid place-items-center text-[9px] font-bold">
          T
        </div>
        <span className="text-[12px] font-semibold text-white">Tesslate</span>
        <span className="rounded bg-[#5865F2] px-1 py-px text-[8px] font-bold uppercase text-white">
          App
        </span>
        <span className="text-[10px] text-[#949ba4]">Today at 9:14 AM</span>
      </div>

      {/* Embed — left accent bar */}
      <div className="mt-1.5 ml-7 overflow-hidden rounded-l-sm rounded-r bg-[#2b2d31]">
        <div className="flex">
          <div className="w-1 bg-[#5865F2]" aria-hidden="true" />
          <div className="flex-1 px-2.5 py-2">
            <div className="text-[11.5px] font-semibold text-white">Approval requested</div>
            <div className="mt-0.5 text-[11px] text-[#dbdee1]">
              <span className="font-semibold">standup-summary</span> finished — diff ready for review.
            </div>
            <div className="mt-1 text-[10px] text-[#949ba4]">Run #4892 · 1.4s</div>
          </div>
        </div>

        {/* Component row — Discord buttons */}
        <div className="flex flex-wrap gap-1 border-t border-[#1f2024] bg-[#2b2d31] px-2.5 py-1.5">
          <button
            type="button"
            className="rounded bg-[#23a559] px-2.5 py-1 text-[11px] font-medium text-white"
            disabled
          >
            Approve
          </button>
          <button
            type="button"
            className="rounded bg-[#4e5058] px-2.5 py-1 text-[11px] font-medium text-white"
            disabled
          >
            Allow for run
          </button>
          <button
            type="button"
            className="rounded bg-[#da373c] px-2.5 py-1 text-[11px] font-medium text-white"
            disabled
          >
            Deny
          </button>
        </div>
      </div>
    </div>
  );
}
