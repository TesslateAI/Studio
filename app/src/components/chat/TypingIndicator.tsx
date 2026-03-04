interface TypingIndicatorProps {
  visible: boolean;
}

export function TypingIndicator({ visible }: TypingIndicatorProps) {
  if (!visible) return null;

  return (
    <div className="typing-indicator flex items-center gap-2 px-5 py-3 flex-shrink-0">
      <div className="message-avatar w-8 h-8 rounded-full bg-gradient-to-br from-[hsl(var(--hue2)_60%_50%)] to-[hsl(var(--hue2)_60%_70%)] flex items-center justify-center">
        <svg className="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 256 256">
          <path d="M197.58,129.06,146,110l-19.06-51.58a15.92,15.92,0,0,0-29.88,0L78,110,26.42,129.06a15.92,15.92,0,0,0,0,29.88L78,178l19.06,51.58a15.92,15.92,0,0,0,29.88,0L146,178l51.58-19.06a15.92,15.92,0,0,0,0-29.88ZM137.75,142.25a16,16,0,0,0-9.5,9.5L112,193.58,95.75,151.75a16,16,0,0,0-9.5-9.5L44.42,128l41.83-14.25a16,16,0,0,0,9.5-9.5L112,62.42l16.25,41.83a16,16,0,0,0,9.5,9.5L179.58,128ZM248,80a8,8,0,0,1-8,8h-8v8a8,8,0,0,1-16,0V88h-8a8,8,0,0,1,0-16h8V64a8,8,0,0,1,16,0v8h8A8,8,0,0,1,248,80ZM152,40a8,8,0,0,1,8-8h8V24a8,8,0,0,1,16,0v8h8a8,8,0,0,1,0,16h-8v8a8,8,0,0,1-16,0V48h-8A8,8,0,0,1,152,40Z" />
        </svg>
      </div>
      <div className="flex gap-1 px-4 py-3 bg-white/5 rounded-2xl">
        <div className="typing-dot w-2 h-2 rounded-full bg-gray-500 animate-typing"></div>
        <div className="typing-dot w-2 h-2 rounded-full bg-gray-500 animate-typing animation-delay-200"></div>
        <div className="typing-dot w-2 h-2 rounded-full bg-gray-500 animate-typing animation-delay-400"></div>
      </div>
    </div>
  );
}
