import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { User, CaretDown, Coins, CreditCard, Gear, SignOut } from '@phosphor-icons/react';
import { billingApi } from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';

export function UserDropdown() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [showDropdown, setShowDropdown] = useState(false);
  const [credits, setCredits] = useState<number>(0);
  const [imgError, setImgError] = useState(false);

  const userName = user?.name || 'User';

  // Determine avatar source: user-set avatar → DiceBear identicon → fallback icon
  const avatarSrc = user?.avatar_url
    ? user.avatar_url
    : user?.id
      ? `https://api.dicebear.com/9.x/identicon/svg?seed=${user.id}`
      : null;

  // Reset img error state when avatar source changes
  useEffect(() => {
    setImgError(false);
  }, [avatarSrc]);

  // Fetch credits on mount
  useEffect(() => {
    billingApi
      .getCreditsBalance()
      .then((res) => setCredits(res.total_credits ?? 0))
      .catch(() => {});
  }, []);

  // Refresh credits when dropdown opens
  useEffect(() => {
    if (showDropdown) {
      billingApi
        .getCreditsBalance()
        .then((res) => setCredits(res.total_credits ?? 0))
        .catch(() => {});
    }
  }, [showDropdown]);

  // Listen for real-time credit updates from SSE events
  const handleCreditsUpdated = useCallback((e: Event) => {
    const detail = (e as CustomEvent).detail;
    if (typeof detail?.newBalance === 'number') {
      setCredits(detail.newBalance);
    }
  }, []);

  useEffect(() => {
    window.addEventListener('credits-updated', handleCreditsUpdated);
    return () => window.removeEventListener('credits-updated', handleCreditsUpdated);
  }, [handleCreditsUpdated]);

  return (
    <div className="relative">
      <button
        onClick={() => setShowDropdown(!showDropdown)}
        className="hidden md:flex items-center gap-2 px-3 py-1.5 hover:bg-white/5 rounded-lg transition-colors"
      >
        {avatarSrc && !imgError ? (
          <img
            src={avatarSrc}
            alt=""
            className="w-6 h-6 rounded-full object-cover"
            referrerPolicy="no-referrer"
            onError={() => setImgError(true)}
          />
        ) : (
          <User size={18} className="text-[var(--text)]" weight="fill" />
        )}
        <span className="text-sm font-medium text-[var(--text)]">{userName}</span>
        <CaretDown
          size={14}
          className={`text-[var(--text)]/60 transition-transform ${showDropdown ? 'rotate-180' : ''}`}
        />
      </button>

      {/* Dropdown Menu */}
      {showDropdown && (
        <>
          {/* Backdrop */}
          <div className="fixed inset-0 z-40" onClick={() => setShowDropdown(false)} />

          {/* Menu */}
          <div className="absolute right-0 mt-2 w-56 bg-[var(--surface)] border border-white/10 rounded-xl shadow-2xl z-50 overflow-hidden">
            <div className="py-2">
              {/* Credits Item */}
              <button
                onClick={() => {
                  setShowDropdown(false);
                  navigate('/settings/billing');
                }}
                className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-white/5 transition-colors text-left"
              >
                <Coins size={18} className="text-[var(--primary)]" weight="fill" />
                <div className="flex-1">
                  <div className="text-sm font-medium text-[var(--text)]">Credits</div>
                  <div className="text-xs text-[var(--text)]/60">
                    {credits.toLocaleString()} available
                  </div>
                </div>
              </button>

              <div className="h-px bg-white/10 my-2" />

              {/* Subscriptions */}
              <button
                onClick={() => {
                  setShowDropdown(false);
                  navigate('/settings/billing');
                }}
                className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-white/5 transition-colors text-left"
              >
                <CreditCard size={18} className="text-[var(--text)]/80" />
                <span className="text-sm font-medium text-[var(--text)]">Subscriptions</span>
              </button>

              {/* Settings */}
              <button
                onClick={() => {
                  setShowDropdown(false);
                  navigate('/settings');
                }}
                className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-white/5 transition-colors text-left"
              >
                <Gear size={18} className="text-[var(--text)]/80" />
                <span className="text-sm font-medium text-[var(--text)]">Settings</span>
              </button>

              <div className="h-px bg-white/10 my-2" />

              {/* Logout */}
              <button
                onClick={() => {
                  setShowDropdown(false);
                  navigate('/logout');
                }}
                className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-red-500/10 transition-colors text-left group"
              >
                <SignOut size={18} className="text-red-400 group-hover:text-red-400" />
                <span className="text-sm font-medium text-red-400">Logout</span>
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default UserDropdown;
