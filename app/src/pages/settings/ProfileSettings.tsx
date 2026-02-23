import { useState, useEffect, useCallback, useRef } from 'react';
import toast from 'react-hot-toast';
import { Check, CheckCircle, XCircle, Info, SpinnerGap, At } from '@phosphor-icons/react';
import { TwitterLogo, GithubLogo, Globe } from '@phosphor-icons/react';
import { usersApi, creatorsApi } from '../../lib/api';
import type { UserProfile, UserProfileUpdate } from '../../lib/api';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { ImageUpload } from '../../components/ImageUpload';
import { SettingsSection, SettingsGroup, SettingsItem } from '../../components/settings';
import { useCancellableRequest } from '../../hooks/useCancellableRequest';

type UsernameStatus = 'idle' | 'checking' | 'available' | 'unavailable' | 'invalid';

export default function ProfileSettings() {
  const [loading, setLoading] = useState(true);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [profileForm, setProfileForm] = useState<UserProfileUpdate>({});
  const [savingProfile, setSavingProfile] = useState(false);

  // Username availability state
  const [usernameStatus, setUsernameStatus] = useState<UsernameStatus>('idle');
  const [usernameError, setUsernameError] = useState<string | null>(null);
  const checkTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Use cancellable request to prevent memory leaks on unmount
  const { execute: executeLoad } = useCancellableRequest<UserProfile>();

  const loadProfile = useCallback(() => {
    executeLoad(() => usersApi.getProfile(), {
      onSuccess: (profileData) => {
        setProfile(profileData);
        setProfileForm({
          username: profileData.username || '',
          name: profileData.name || '',
          avatar_url: profileData.avatar_url || '',
          bio: profileData.bio || '',
          twitter_handle: profileData.twitter_handle || '',
          github_username: profileData.github_username || '',
          website_url: profileData.website_url || '',
        });
      },
      onError: (error) => {
        console.error('Failed to load profile:', error);
        const err = error as { response?: { data?: { detail?: string } } };
        toast.error(err.response?.data?.detail || 'Failed to load profile');
      },
      onFinally: () => setLoading(false),
    });
  }, [executeLoad]);

  useEffect(() => {
    loadProfile();
  }, [loadProfile]);

  // Cleanup debounce timer on unmount
  useEffect(() => {
    return () => {
      if (checkTimerRef.current) clearTimeout(checkTimerRef.current);
    };
  }, []);

  const handleUsernameChange = (raw: string) => {
    // Client-side pre-filter: only allow valid chars, force lowercase
    const cleaned = raw.toLowerCase().replace(/[^a-z0-9_-]/g, '');
    setProfileForm((prev) => ({ ...prev, username: cleaned }));
    setUsernameError(null);

    // Clear pending check
    if (checkTimerRef.current) clearTimeout(checkTimerRef.current);

    // Skip check if empty or same as current username
    if (!cleaned || cleaned === profile?.username) {
      setUsernameStatus('idle');
      return;
    }

    // Quick client-side length check
    if (cleaned.length < 3) {
      setUsernameStatus('invalid');
      setUsernameError('Username must be at least 3 characters');
      return;
    }

    // Debounced server-side availability check
    setUsernameStatus('checking');
    checkTimerRef.current = setTimeout(async () => {
      try {
        const result = await creatorsApi.checkUsername(cleaned);
        if (result.available) {
          setUsernameStatus('available');
          setUsernameError(null);
        } else {
          setUsernameStatus('unavailable');
          setUsernameError(result.reason || 'Username is not available');
        }
      } catch {
        setUsernameStatus('idle');
      }
    }, 500);
  };

  const isSaveDisabled =
    savingProfile ||
    usernameStatus === 'checking' ||
    usernameStatus === 'unavailable' ||
    usernameStatus === 'invalid';

  const handleSaveProfile = async () => {
    setSavingProfile(true);
    try {
      const updatedProfile = await usersApi.updateProfile(profileForm);
      setProfile(updatedProfile);
      setUsernameStatus('idle');
      toast.success('Profile updated successfully');
    } catch (error: unknown) {
      console.error('Failed to update profile:', error);
      const err = error as { response?: { status?: number; data?: { detail?: string } } };
      if (err.response?.status === 409) {
        setUsernameStatus('unavailable');
        setUsernameError('Username is already taken');
      }
      toast.error(err.response?.data?.detail || 'Failed to update profile');
    } finally {
      setSavingProfile(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading profile..." size={60} />
      </div>
    );
  }

  return (
    <SettingsSection
      title="Profile"
      description="Manage your profile information and how you appear to others"
    >
      {/* Profile Picture */}
      <SettingsGroup title="Profile Picture">
        <div className="px-4 md:px-6 py-4 md:py-6">
          <ImageUpload
            value={profileForm.avatar_url || null}
            onChange={(dataUrl) => setProfileForm({ ...profileForm, avatar_url: dataUrl || '' })}
            maxSizeKB={200}
          />
        </div>
      </SettingsGroup>

      {/* Basic Info */}
      <SettingsGroup title="Basic Information">
        {/* Username field */}
        <SettingsItem
          label="Username"
          description="Your unique @handle for your public profile"
          control={
            <div className="w-full sm:w-64">
              <div className="flex items-center">
                <span className="px-3 self-stretch flex items-center bg-white/5 border border-r-0 border-white/10 rounded-l-lg text-[var(--text)]/60">
                  <At size={16} />
                </span>
                <div className="relative flex-1">
                  <input
                    type="text"
                    value={profileForm.username || ''}
                    onChange={(e) => handleUsernameChange(e.target.value)}
                    placeholder="johndoe"
                    maxLength={50}
                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-r-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)] pr-9"
                  />
                  {/* Status indicator inside input */}
                  <span className="absolute right-2.5 top-1/2 -translate-y-1/2">
                    {usernameStatus === 'checking' && (
                      <SpinnerGap size={16} className="text-[var(--text)]/40 animate-spin" />
                    )}
                    {usernameStatus === 'available' && (
                      <CheckCircle size={16} weight="fill" className="text-green-400" />
                    )}
                    {(usernameStatus === 'unavailable' || usernameStatus === 'invalid') && (
                      <XCircle size={16} weight="fill" className="text-red-400" />
                    )}
                  </span>
                </div>
              </div>
              {/* Error message */}
              {usernameError &&
                (usernameStatus === 'unavailable' || usernameStatus === 'invalid') && (
                  <p className="mt-1.5 text-xs text-red-400">{usernameError}</p>
                )}
              {/* Profile link preview */}
              {profileForm.username &&
                usernameStatus !== 'invalid' &&
                usernameStatus !== 'unavailable' && (
                  <p className="mt-1.5 text-xs text-[var(--text)]/40">
                    Your profile:{' '}
                    <a
                      href={`${window.location.origin}/@${profileForm.username}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[var(--primary)] hover:underline"
                    >
                      {window.location.origin}/@{profileForm.username}
                    </a>
                  </p>
                )}
            </div>
          }
        />
        <SettingsItem
          label="Display Name"
          description="Your name as shown to other users"
          control={
            <input
              type="text"
              value={profileForm.name || ''}
              onChange={(e) => setProfileForm({ ...profileForm, name: e.target.value })}
              placeholder="Enter your display name"
              className="w-full sm:w-64 px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
            />
          }
        />
        <SettingsItem
          label="Bio"
          description="A short description about yourself"
          control={
            <textarea
              value={profileForm.bio || ''}
              onChange={(e) => setProfileForm({ ...profileForm, bio: e.target.value })}
              placeholder="Tell us about yourself"
              rows={2}
              className="w-full sm:w-64 px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)] resize-none"
            />
          }
        />
      </SettingsGroup>

      {/* Social Links */}
      <SettingsGroup title="Social Links">
        <SettingsItem
          label="Twitter"
          description="Your Twitter/X username"
          control={
            <div className="flex items-center w-full sm:w-64">
              <span className="px-3 self-stretch flex items-center bg-white/5 border border-r-0 border-white/10 rounded-l-lg text-[var(--text)]/60">
                <TwitterLogo size={16} />
              </span>
              <input
                type="text"
                value={profileForm.twitter_handle || ''}
                onChange={(e) => setProfileForm({ ...profileForm, twitter_handle: e.target.value })}
                placeholder="username"
                className="flex-1 px-3 py-2 bg-white/5 border border-white/10 rounded-r-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
              />
            </div>
          }
        />
        <SettingsItem
          label="GitHub"
          description="Your GitHub username"
          control={
            <div className="flex items-center w-full sm:w-64">
              <span className="px-3 self-stretch flex items-center bg-white/5 border border-r-0 border-white/10 rounded-l-lg text-[var(--text)]/60">
                <GithubLogo size={16} />
              </span>
              <input
                type="text"
                value={profileForm.github_username || ''}
                onChange={(e) =>
                  setProfileForm({ ...profileForm, github_username: e.target.value })
                }
                placeholder="username"
                className="flex-1 px-3 py-2 bg-white/5 border border-white/10 rounded-r-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
              />
            </div>
          }
        />
        <SettingsItem
          label="Website"
          description="Your personal website"
          control={
            <div className="flex items-center w-full sm:w-64">
              <span className="px-3 self-stretch flex items-center bg-white/5 border border-r-0 border-white/10 rounded-l-lg text-[var(--text)]/60">
                <Globe size={16} />
              </span>
              <input
                type="url"
                value={profileForm.website_url || ''}
                onChange={(e) => setProfileForm({ ...profileForm, website_url: e.target.value })}
                placeholder="https://yoursite.com"
                className="flex-1 px-3 py-2 bg-white/5 border border-white/10 rounded-r-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
              />
            </div>
          }
        />
      </SettingsGroup>

      {/* Email Info */}
      <div className="p-4 bg-blue-500/10 border border-blue-500/20 rounded-xl">
        <div className="flex items-start gap-3">
          <Info size={20} className="text-blue-400 mt-0.5 flex-shrink-0" />
          <div className="text-sm text-blue-400">
            <p className="font-semibold mb-1">Email: {profile?.email}</p>
            <p className="text-xs">
              Your email cannot be changed. Contact support if you need to update it.
            </p>
          </div>
        </div>
      </div>

      {/* Save Button */}
      <div className="flex justify-end">
        <button
          onClick={handleSaveProfile}
          disabled={isSaveDisabled}
          className="px-6 py-3 bg-[var(--primary)] hover:bg-[var(--primary-hover)] disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg font-semibold transition-all flex items-center gap-2 min-h-[48px]"
        >
          {savingProfile ? (
            <>
              <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
              Saving...
            </>
          ) : (
            <>
              <Check size={18} weight="bold" />
              Save Changes
            </>
          )}
        </button>
      </div>
    </SettingsSection>
  );
}
