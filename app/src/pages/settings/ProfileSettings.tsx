import { useState, useEffect, useCallback } from 'react';
import toast from 'react-hot-toast';
import {
  Check,
  Info,
} from '@phosphor-icons/react';
import { TwitterLogo, GithubLogo, Globe } from '@phosphor-icons/react';
import { usersApi } from '../../lib/api';
import type { UserProfile, UserProfileUpdate } from '../../lib/api';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { ImageUpload } from '../../components/ImageUpload';
import { SettingsSection, SettingsGroup, SettingsItem } from '../../components/settings';
import { useCancellableRequest } from '../../hooks/useCancellableRequest';

export default function ProfileSettings() {
  const [loading, setLoading] = useState(true);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [profileForm, setProfileForm] = useState<UserProfileUpdate>({});
  const [savingProfile, setSavingProfile] = useState(false);

  // Use cancellable request to prevent memory leaks on unmount
  // The hook ensures callbacks only fire if component is still mounted
  const { execute: executeLoad } = useCancellableRequest<UserProfile>();

  const loadProfile = useCallback(() => {
    executeLoad(
      // Note: usersApi.getProfile doesn't support AbortSignal yet,
      // but the hook still prevents state updates on unmounted components
      () => usersApi.getProfile(),
      {
        onSuccess: (profileData) => {
          setProfile(profileData);
          setProfileForm({
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
      }
    );
  }, [executeLoad]);

  useEffect(() => {
    loadProfile();
  }, [loadProfile]);

  const handleSaveProfile = async () => {
    setSavingProfile(true);
    try {
      const updatedProfile = await usersApi.updateProfile(profileForm);
      setProfile(updatedProfile);
      toast.success('Profile updated successfully');
    } catch (error: unknown) {
      console.error('Failed to update profile:', error);
      const err = error as { response?: { data?: { detail?: string } } };
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
              <span className="px-3 py-2 bg-white/5 border border-r-0 border-white/10 rounded-l-lg text-[var(--text)]/60 text-base">
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
              <span className="px-3 py-2 bg-white/5 border border-r-0 border-white/10 rounded-l-lg text-[var(--text)]/60 text-base">
                <GithubLogo size={16} />
              </span>
              <input
                type="text"
                value={profileForm.github_username || ''}
                onChange={(e) => setProfileForm({ ...profileForm, github_username: e.target.value })}
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
              <span className="px-3 py-2 bg-white/5 border border-r-0 border-white/10 rounded-l-lg text-[var(--text)]/60 text-base">
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
          disabled={savingProfile}
          className="px-6 py-3 bg-[var(--primary)] hover:bg-[var(--primary-hover)] disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg font-semibold transition-all flex items-center gap-2 min-h-[48px]"
        >
          {savingProfile ? (
            <>
              <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
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
