interface UsageRibbonProps {
  creditsLeft: number;
  onGetMore: () => void;
}

export function UsageRibbon({ creditsLeft, onGetMore }: UsageRibbonProps) {
  return (
    <div className="
      usage-ribbon
      px-4 py-2
      bg-gradient-to-r from-[rgba(0,217,255,0.1)] to-[rgba(0,217,255,0.05)]
      border-b border-[rgba(0,217,255,0.2)]
      flex items-center justify-between
      text-xs text-[var(--accent)]
      rounded-t-3xl
      flex-shrink-0
    ">
      <div className="flex items-center gap-2">
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
          <path d="M215.79,118.17a8,8,0,0,0-5-5.66L153.18,90.9l14.66-73.33a8,8,0,0,0-13.69-7l-112,120a8,8,0,0,0,3,13l57.63,21.61L88.16,238.43a8,8,0,0,0,13.69,7l112-120A8,8,0,0,0,215.79,118.17ZM109.37,214l10.47-52.38a8,8,0,0,0-5-9.06L62,132.71l84.62-90.66L136.16,94.43a8,8,0,0,0,5,9.06l52.8,19.8Z" />
        </svg>
        <span className="font-semibold">{creditsLeft} credits left</span>
      </div>
      <button
        onClick={onGetMore}
        className="
          text-xs bg-[var(--accent)]/20 hover:bg-[var(--accent)]/30
          px-3 py-1 rounded-full
          transition-colors font-semibold
        "
      >
        Get More
      </button>
    </div>
  );
}
