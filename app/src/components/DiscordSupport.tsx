import { DiscordLogo } from '@phosphor-icons/react';

export function DiscordSupport() {
  return (
    <div className="fixed bottom-4 right-4 md:bottom-8 md:right-8 z-40 group" data-tour="discord-support">
      <a
        href="https://discord.gg/WgXabcN2r2"
        target="_blank"
        rel="noopener noreferrer"
        className="flex flex-col items-center gap-2"
      >
        <div className="
          w-12 h-12 md:w-16 md:h-16 bg-[#5865F2] rounded-full
          flex items-center justify-center
          shadow-lg hover:shadow-xl
          transition-all duration-300
          hover:scale-110
          relative
        ">
          <DiscordLogo className="w-6 h-6 md:w-8 md:h-8 text-white" weight="fill" />

          {/* Hover tooltip */}
          <div className="
            absolute bottom-full mb-2 right-0
            bg-gray-900 text-white text-sm
            px-3 py-2 rounded-lg
            whitespace-nowrap
            opacity-0 group-hover:opacity-100
            transition-opacity duration-200
            pointer-events-none
          ">
            Join our Discord for support
          </div>
        </div>
        <span className="text-xs md:text-sm font-medium text-[var(--text)] hidden sm:block">Support</span>
      </a>
    </div>
  );
}
