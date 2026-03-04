import { useEffect, useRef } from 'react';
import { GithubLogo, LinkSimple, CircleNotch } from '@phosphor-icons/react';
import type { GitProvider } from '../../../types/git-providers';
import { PROVIDER_CONFIG } from '../../../types/git-providers';
import type { ResolverStatus } from './useRepoResolver';

interface RepoUrlInputProps {
  value: string;
  onChange: (url: string) => void;
  provider: GitProvider | null;
  status: ResolverStatus;
  disabled?: boolean;
  autoFocus?: boolean;
}

const ProviderBadge = ({ provider }: { provider: GitProvider }) => {
  const config = PROVIDER_CONFIG[provider];

  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-white/10 text-[var(--text)]">
      {provider === 'github' ? (
        <GithubLogo size={14} weight="fill" />
      ) : provider === 'gitlab' ? (
        <span className="font-bold text-[#FC6D26]" style={{ fontSize: 10 }}>GL</span>
      ) : (
        <span className="font-bold text-[#0052CC]" style={{ fontSize: 10 }}>BB</span>
      )}
      {config.displayName}
    </span>
  );
};

export function RepoUrlInput({
  value,
  onChange,
  provider,
  status,
  disabled = false,
  autoFocus = false,
}: RepoUrlInputProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (autoFocus && inputRef.current) {
      inputRef.current.focus();
    }
  }, [autoFocus]);

  const isLoading =
    status === 'detecting' ||
    status === 'fetching-repo' ||
    status === 'fetching-branches';

  return (
    <div className="relative">
      <div className="absolute left-4 top-1/2 -translate-y-1/2 flex items-center gap-2">
        {provider ? (
          <ProviderBadge provider={provider} />
        ) : (
          <LinkSimple className="w-5 h-5 text-gray-500" />
        )}
      </div>
      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`w-full bg-white/5 border border-white/10 text-[var(--text)] py-3.5 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--primary)]/30 focus:border-[var(--primary)]/50 placeholder-gray-500 transition-all min-h-[44px] ${
          provider ? 'pl-[6.5rem]' : 'pl-12'
        } ${isLoading ? 'pr-12' : 'pr-4'}`}
        placeholder="https://github.com/owner/repository"
        disabled={disabled}
      />
      {isLoading && (
        <div className="absolute right-4 top-1/2 -translate-y-1/2">
          <CircleNotch className="w-5 h-5 text-[var(--primary)] animate-spin" />
        </div>
      )}
    </div>
  );
}
