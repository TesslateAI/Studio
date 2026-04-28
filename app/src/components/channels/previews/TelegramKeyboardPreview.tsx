/**
 * Static Telegram-style preview — bot bubble + inline keyboard.
 * Visually echoes the inline_keyboard payload built by approval_cards.py.
 */
export function TelegramKeyboardPreview() {
  return (
    <div className="overflow-hidden rounded-lg bg-[#e7ebf0] p-3 font-sans text-[12px] leading-tight select-none">
      {/* Bot bubble */}
      <div className="flex items-end gap-1.5">
        <div className="flex-shrink-0 h-7 w-7 rounded-full bg-[#229ED9] text-white grid place-items-center text-[10px] font-bold">
          T
        </div>
        <div className="max-w-[85%] rounded-lg rounded-bl-sm bg-white px-3 py-2 shadow-sm">
          <div className="text-[11px] font-semibold text-[#229ED9]">Tesslate Bot</div>
          <div className="mt-0.5 text-[12px] text-[#0f1419]">
            Approval requested — <span className="font-semibold">standup-summary</span>
          </div>
          <div className="mt-0.5 text-[11.5px] text-[#5b6b78]">
            Run finished — diff ready for review.
          </div>
          <div className="mt-1 text-right text-[10px] text-[#5b6b78]">9:14 AM</div>
        </div>
      </div>

      {/* Inline keyboard — full-width white buttons stacked */}
      <div className="mt-2 ml-9 max-w-[85%] space-y-1">
        <div className="grid grid-cols-2 gap-1">
          <button
            type="button"
            className="rounded-md bg-white px-2 py-1.5 text-[11px] font-medium text-[#229ED9] shadow-sm"
            disabled
          >
            ✓ Approve
          </button>
          <button
            type="button"
            className="rounded-md bg-white px-2 py-1.5 text-[11px] font-medium text-[#229ED9] shadow-sm"
            disabled
          >
            ↻ Allow for run
          </button>
        </div>
        <button
          type="button"
          className="block w-full rounded-md bg-white px-2 py-1.5 text-[11px] font-medium text-[#e54c4c] shadow-sm"
          disabled
        >
          ✕ Deny
        </button>
      </div>
    </div>
  );
}
