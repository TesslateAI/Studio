/**
 * Static Signal-style preview — blue gradient bubble + button row.
 * Signal renders a plain bubble; interactivity is via signal-cli reactions
 * and quoted replies, which we represent as inline buttons here.
 */
export function SignalBubblePreview() {
  return (
    <div className="overflow-hidden rounded-lg bg-[#0f0f10] p-3 font-sans text-[12px] leading-tight select-none">
      {/* Bot bubble */}
      <div className="flex items-end gap-1.5">
        <div className="flex-shrink-0 h-7 w-7 rounded-full bg-[#3a76f0] text-white grid place-items-center text-[10px] font-bold">
          T
        </div>
        <div
          className="max-w-[85%] rounded-2xl rounded-bl-md px-3 py-1.5 text-white shadow-sm"
          style={{ backgroundImage: 'linear-gradient(180deg, #2c6bed 0%, #2058d8 100%)' }}
        >
          <div className="text-[11.5px]">
            <span className="font-semibold">Approval requested</span> — standup-summary finished, diff ready for review.
          </div>
          <div className="mt-0.5 text-right text-[10px] text-white/70">9:14 AM</div>
        </div>
      </div>

      {/* Reply buttons — emulated via quoted-reply flow in the signal-cli adapter */}
      <div className="mt-2 ml-9 flex max-w-[85%] flex-wrap gap-1">
        <button
          type="button"
          className="rounded-full bg-[#1f1f21] px-2.5 py-1 text-[11px] font-medium text-[#7ea8ff] ring-1 ring-[#2a2a2c]"
          disabled
        >
          Approve
        </button>
        <button
          type="button"
          className="rounded-full bg-[#1f1f21] px-2.5 py-1 text-[11px] font-medium text-[#cbd5e1] ring-1 ring-[#2a2a2c]"
          disabled
        >
          Allow for run
        </button>
        <button
          type="button"
          className="rounded-full bg-[#1f1f21] px-2.5 py-1 text-[11px] font-medium text-[#fb7185] ring-1 ring-[#2a2a2c]"
          disabled
        >
          Deny
        </button>
      </div>
    </div>
  );
}
