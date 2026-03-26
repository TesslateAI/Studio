import { useState } from 'react';
import { Warning, GithubLogo, CircleNotch } from '@phosphor-icons/react';
import { motion } from 'framer-motion';
import { gitProvidersApi } from '../../../lib/git-providers-api';
import type { GitProvider, AllProvidersStatus } from '../../../types/git-providers';
import { PROVIDER_CONFIG } from '../../../types/git-providers';
import toast from 'react-hot-toast';

interface ConnectProviderInlineProps {
  provider: GitProvider;
  onConnected: () => void;
  onProviderStatusChange: (status: AllProvidersStatus) => void;
}

export function ConnectProviderInline({
  provider,
  onConnected,
  onProviderStatusChange,
}: ConnectProviderInlineProps) {
  const [isConnecting, setIsConnecting] = useState(false);
  const config = PROVIDER_CONFIG[provider];

  const handleConnect = async () => {
    setIsConnecting(true);
    try {
      const { authorization_url } = await gitProvidersApi.initiateOAuth(provider);

      const width = 600;
      const height = 700;
      const left = window.screenX + (window.outerWidth - width) / 2;
      const top = window.screenY + (window.outerHeight - height) / 2;

      const popup = window.open(
        authorization_url,
        `${provider}-oauth`,
        `width=${width},height=${height},left=${left},top=${top},toolbar=no,menubar=no,scrollbars=yes`
      );

      const checkPopup = setInterval(async () => {
        if (popup?.closed) {
          clearInterval(checkPopup);
          setIsConnecting(false);

          // Refresh provider status
          const newAllStatus = await gitProvidersApi.getAllStatus();
          onProviderStatusChange(newAllStatus);

          if (newAllStatus[provider].connected) {
            toast.success(`${config.displayName} connected successfully!`);
            onConnected();
          }
        }
      }, 500);

      setTimeout(
        () => {
          clearInterval(checkPopup);
          setIsConnecting(false);
        },
        5 * 60 * 1000
      );
    } catch (error: unknown) {
      setIsConnecting(false);
      const errorMessage =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Failed to initiate connection';
      toast.error(errorMessage);
    }
  };

  const ProviderLogo =
    provider === 'github'
      ? () => <GithubLogo size={16} weight="fill" />
      : provider === 'gitlab'
        ? () => (
            <span className="font-bold text-[#FC6D26]" style={{ fontSize: 11 }}>
              GL
            </span>
          )
        : () => (
            <span className="font-bold text-[#0052CC]" style={{ fontSize: 11 }}>
              BB
            </span>
          );

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="bg-yellow-500/[0.08] border border-yellow-500/20 rounded-xl p-4"
    >
      <div className="flex items-start gap-3">
        <Warning size={20} weight="fill" className="text-yellow-500 flex-shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <p className="text-sm text-yellow-300 mb-2">
            Connect your {config.displayName} account to access this repository.
          </p>
          <button
            type="button"
            onClick={handleConnect}
            disabled={isConnecting}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-yellow-500/15 text-yellow-300 hover:bg-yellow-500/25 font-medium text-sm transition-all min-h-[36px] disabled:opacity-50"
          >
            {isConnecting ? (
              <>
                <CircleNotch size={14} className="animate-spin" />
                Connecting...
              </>
            ) : (
              <>
                <ProviderLogo />
                Connect {config.displayName}
              </>
            )}
          </button>
        </div>
      </div>
    </motion.div>
  );
}
