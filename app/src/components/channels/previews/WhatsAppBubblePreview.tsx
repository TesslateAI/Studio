/**
 * Static WhatsApp-style preview — green bot bubble with reply buttons.
 * WhatsApp Cloud API "interactive" messages render a bubble + button list.
 */
export function WhatsAppBubblePreview() {
  return (
    <div
      className="overflow-hidden rounded-lg p-3 font-sans text-[12px] leading-tight select-none"
      style={{
        backgroundImage:
          'linear-gradient(180deg, #ECE5DD 0%, #E5DDD3 100%)',
      }}
    >
      {/* Bot bubble */}
      <div className="ml-1 max-w-[88%] rounded-lg rounded-bl-sm bg-white px-2.5 py-2 shadow-sm">
        <div className="text-[10.5px] font-semibold text-[#075E54]">Tesslate</div>
        <div className="mt-0.5 text-[12px] text-[#111b21]">
          Approval requested — <span className="font-semibold">standup-summary</span>
        </div>
        <div className="mt-0.5 text-[11.5px] text-[#3b4a54]">
          Run finished — diff ready for review.
        </div>
        <div className="mt-1 text-right text-[10px] text-[#667781]">
          9:14 AM <span className="ml-0.5 text-[#53bdeb]">✓✓</span>
        </div>
      </div>

      {/* Quick-reply pill buttons — WhatsApp interactive */}
      <div className="mt-2 ml-1 flex max-w-[88%] flex-col gap-1">
        <button
          type="button"
          className="rounded-md bg-white px-3 py-1.5 text-[11.5px] font-medium text-[#00a884] shadow-sm"
          disabled
        >
          ↻ Approve
        </button>
        <button
          type="button"
          className="rounded-md bg-white px-3 py-1.5 text-[11.5px] font-medium text-[#00a884] shadow-sm"
          disabled
        >
          ↻ Allow for run
        </button>
        <button
          type="button"
          className="rounded-md bg-white px-3 py-1.5 text-[11.5px] font-medium text-[#e54c4c] shadow-sm"
          disabled
        >
          ↻ Deny
        </button>
      </div>
    </div>
  );
}
