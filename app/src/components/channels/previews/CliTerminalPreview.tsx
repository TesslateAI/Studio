/**
 * Static CLI/terminal-style preview — interactive shell prompt for approvals.
 * The CLI adapter exposes `ts approve <id>` style commands; this preview
 * renders that interaction in a terminal-frame visual language.
 */
export function CliTerminalPreview() {
  return (
    <div className="overflow-hidden rounded-md bg-[#0a0a0b] font-mono text-[11.5px] leading-tight text-[#d4d4d8] shadow-sm select-none">
      {/* Window chrome */}
      <div className="flex items-center gap-1.5 border-b border-[#1f1f22] bg-[#161618] px-3 py-1.5">
        <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f57]" aria-hidden="true" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#febc2e]" aria-hidden="true" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#28c840]" aria-hidden="true" />
        <span className="ml-1 text-[10px] text-[#6e6e72]">tesslate · zsh</span>
      </div>

      {/* Output */}
      <div className="px-3 py-2.5 space-y-0.5">
        <div className="text-[#a1a1aa]">
          <span className="text-[#22c55e]">tess</span>
          <span className="text-[#71717a]">@</span>
          <span className="text-[#60a5fa]">studio</span>
          <span className="text-[#71717a]"> ~ </span>
          <span className="text-[#d4d4d8]">$ </span>
          <span>ts approvals watch</span>
        </div>
        <div className="text-[#a1a1aa]">
          <span className="text-[#facc15]">●</span> standup-summary &mdash; approval requested
        </div>
        <div className="text-[#71717a]">  Run finished — diff ready for review.</div>
        <div className="mt-1 text-[#a1a1aa]">
          <span className="text-[#22c55e]">[A]</span>llow once · <span className="text-[#22c55e]">[R]</span>un · <span className="text-[#ef4444]">[D]</span>eny
        </div>
        <div className="text-[#a1a1aa]">
          <span className="text-[#22c55e]">tess</span>
          <span className="text-[#71717a]">@</span>
          <span className="text-[#60a5fa]">studio</span>
          <span className="text-[#71717a]"> ~ </span>
          <span className="text-[#d4d4d8]">$ </span>
          <span className="inline-block h-3 w-1.5 translate-y-[2px] bg-[#d4d4d8]" aria-hidden="true" />
        </div>
      </div>
    </div>
  );
}
