import { ArrowRight } from '@phosphor-icons/react';
import { CHANNEL_PLATFORMS } from './platforms';

/**
 * Home-page entry tile for "Connect your channels" — mirrors ConnectorsCard's
 * shape so the two sit as visually consistent siblings in the Home action grid.
 *
 * Brand silhouettes come from the central platforms.ts so any brand whose
 * CDN slug is broken (e.g. Slack, which Salesforce pulled from simpleicons
 * in 2024) automatically falls back to the inline data URI defined there.
 * CLI is excluded from the Home thumbnail row because it has no
 * recognizable logo, but it still appears as a tile in the Channels page.
 */

const HOME_BRANDS = CHANNEL_PLATFORMS.filter((p) => p.key !== 'cli');

interface ChannelsCardProps {
  onClick: () => void;
}

export function ChannelsCard({ onClick }: ChannelsCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Connect your channels: Slack, Telegram, Discord, WhatsApp, Signal and more"
      title="Send approvals and deliver runs to Slack, Telegram, Discord, WhatsApp, Signal, or your terminal."
      className="group relative col-span-2 flex w-full min-h-[72px] items-center gap-3 rounded-[var(--radius)] bg-[var(--surface)] px-3.5 py-3 text-left motion-safe:transition-colors hover:bg-[var(--surface-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg)] sm:gap-4 sm:px-4"
    >
      {/* Logo row */}
      <div className="flex flex-shrink-0 items-center -space-x-1.5">
        {HOME_BRANDS.map((p, i) => (
          <span
            key={p.key}
            className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--bg)] motion-safe:transition-transform group-hover:scale-[1.03]"
            style={{ zIndex: HOME_BRANDS.length - i }}
            aria-hidden="true"
          >
            <span
              className="block h-3.5 w-3.5 bg-[var(--text-muted)] group-hover:bg-[var(--text)] motion-safe:transition-colors"
              style={{
                maskImage: `url("${p.iconUrl}")`,
                WebkitMaskImage: `url("${p.iconUrl}")`,
                maskRepeat: 'no-repeat',
                WebkitMaskRepeat: 'no-repeat',
                maskSize: 'contain',
                WebkitMaskSize: 'contain',
                maskPosition: 'center',
                WebkitMaskPosition: 'center',
              }}
            />
          </span>
        ))}
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <span className="text-sm font-semibold text-[var(--text)]">Connect your channels</span>
        <span className="truncate text-[11px] text-[var(--text-muted)]">
          {HOME_BRANDS.map((p) => p.name).join(' · ')}
        </span>
      </div>

      <ArrowRight
        size={16}
        className="flex-shrink-0 text-[var(--text-muted)] motion-safe:transition-transform group-hover:translate-x-0.5 group-hover:text-[var(--text)]"
      />
    </button>
  );
}
