import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  User,
  CaretDown,
  Coins,
  CreditCard,
  Gear,
  SignOut
} from '@phosphor-icons/react';

interface UserDropdownProps {
  userName: string;
  userCredits: number;
  userTier: string;
}

export function UserDropdown({ userName, userCredits, userTier }: UserDropdownProps) {
  const navigate = useNavigate();
  const [showDropdown, setShowDropdown] = useState(false);

  return (
    <div className="relative">
      <button
        onClick={() => setShowDropdown(!showDropdown)}
        className="hidden md:flex items-center gap-2 px-3 py-1.5 hover:bg-white/5 rounded-lg transition-colors"
      >
        <User size={18} className="text-[var(--text)]" weight="fill" />
        <span className="text-sm font-medium text-[var(--text)]">{userName}</span>
        {userTier === 'pro' && (
          <span className="px-2 py-0.5 bg-gradient-to-r from-[var(--primary)] to-[var(--primary-hover)] text-white text-xs font-bold rounded-md">
            PRO
          </span>
        )}
        <CaretDown
          size={14}
          className={`text-[var(--text)]/60 transition-transform ${showDropdown ? 'rotate-180' : ''}`}
        />
      </button>

      {/* Dropdown Menu */}
      {showDropdown && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setShowDropdown(false)}
          />

          {/* Menu */}
          <div className="absolute right-0 mt-2 w-56 bg-[var(--surface)] border border-white/10 rounded-xl shadow-2xl z-50 overflow-hidden">
            <div className="py-2">
              {/* Credits Item */}
              <button
                onClick={() => {
                  setShowDropdown(false);
                  navigate('/billing');
                }}
                className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-white/5 transition-colors text-left"
              >
                <Coins size={18} className="text-[var(--primary)]" weight="fill" />
                <div className="flex-1">
                  <div className="text-sm font-medium text-[var(--text)]">Credits</div>
                  <div className="text-xs text-[var(--text)]/60">{userCredits.toLocaleString()} available</div>
                </div>
              </button>

              <div className="h-px bg-white/10 my-2" />

              {/* Subscriptions */}
              <button
                onClick={() => {
                  setShowDropdown(false);
                  navigate('/billing/plans');
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
