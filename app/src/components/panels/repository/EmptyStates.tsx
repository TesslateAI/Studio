import type { ReactNode } from 'react';
import { ArrowClockwise, GithubLogo, Info, Warning } from '@phosphor-icons/react';

interface ContainerProps {
  icon: ReactNode;
  title: string;
  body?: string;
  action?: ReactNode;
}

function EmptyContainer({ icon, title, body, action }: ContainerProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 px-4 text-center">
      <span className="text-[var(--text-subtle)]">{icon}</span>
      <p className="text-[12px] text-[var(--text)]">{title}</p>
      {body && (
        <p className="text-[10.5px] text-[var(--text-muted)] max-w-[280px] leading-snug">{body}</p>
      )}
      {action}
    </div>
  );
}

export function NoRemoteState({ feature }: { feature: string }) {
  return (
    <EmptyContainer
      icon={<GithubLogo size={26} weight="duotone" />}
      title={`Connect a GitHub remote to see ${feature}.`}
      body="Your code still lives on your machine — connecting a GitHub remote just lets everyone see the same history."
    />
  );
}

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-10 gap-2">
      <ArrowClockwise size={18} weight="bold" className="animate-spin text-[var(--text-muted)]" />
      <p className="text-[11px] text-[var(--text-muted)]">{label}</p>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <EmptyContainer
      icon={<Warning size={22} weight="bold" />}
      title="We couldn't load this from GitHub."
      body={message}
      action={
        onRetry ? (
          <button type="button" onClick={onRetry} className="btn btn-sm mt-1">
            Try again
          </button>
        ) : undefined
      }
    />
  );
}

export function InfoState({ title, body }: { title: string; body?: string }) {
  return <EmptyContainer icon={<Info size={22} weight="duotone" />} title={title} body={body} />;
}
