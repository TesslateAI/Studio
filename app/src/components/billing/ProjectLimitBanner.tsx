import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { billingApi } from '../../lib/api';
import type { SubscriptionResponse } from '../../types/billing';

interface ProjectLimitBannerProps {
  currentProjectCount: number;
  onRefresh?: () => void;
  compact?: boolean;
}

const ProjectLimitBanner: React.FC<ProjectLimitBannerProps> = ({
  currentProjectCount,
  onRefresh,
  compact = false,
}) => {
  const [subscription, setSubscription] = useState<SubscriptionResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadSubscription();
  }, []);

  const loadSubscription = async () => {
    try {
      setLoading(true);
      const response = await billingApi.getSubscription();
      setSubscription(response.data);
    } catch (err) {
      console.error('Failed to load subscription:', err);
    } finally {
      setLoading(false);
    }
  };

  if (loading || !subscription) {
    return null;
  }

  const maxProjects = subscription.max_projects;
  const usagePercentage = (currentProjectCount / maxProjects) * 100;
  const isNearLimit = usagePercentage >= 80;
  const isAtLimit = currentProjectCount >= maxProjects;
  const isPremium = subscription.tier === 'pro';

  // Don't show banner if well under limit
  if (!isNearLimit && !compact) {
    return null;
  }

  if (compact) {
    return (
      <div className="flex items-center justify-between text-sm">
        <div className="flex items-center space-x-2">
          <span className={`font-medium ${isAtLimit ? 'text-red-600' : isNearLimit ? 'text-yellow-600' : 'text-gray-600'}`}>
            Projects: {currentProjectCount} / {maxProjects}
          </span>
          {isAtLimit && (
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-800">
              Limit Reached
            </span>
          )}
        </div>
        {!isPremium && isNearLimit && (
          <Link
            to="/billing/plans"
            className="text-blue-500 hover:text-blue-600 font-medium text-xs"
          >
            Upgrade
          </Link>
        )}
      </div>
    );
  }

  return (
    <div
      className={`rounded-lg p-4 mb-6 ${
        isAtLimit
          ? 'bg-red-50 border border-red-200'
          : isNearLimit
          ? 'bg-yellow-50 border border-yellow-200'
          : 'bg-blue-50 border border-blue-200'
      }`}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-start space-x-3">
          <div className="flex-shrink-0">
            {isAtLimit ? (
              <svg className="h-6 w-6 text-red-600" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
              </svg>
            ) : isNearLimit ? (
              <svg className="h-6 w-6 text-yellow-600" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
              </svg>
            ) : (
              <svg className="h-6 w-6 text-blue-600" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
              </svg>
            )}
          </div>

          <div className="flex-1">
            <h3
              className={`font-semibold ${
                isAtLimit ? 'text-red-800' : isNearLimit ? 'text-yellow-800' : 'text-blue-800'
              }`}
            >
              {isAtLimit
                ? 'Project Limit Reached'
                : isNearLimit
                ? 'Approaching Project Limit'
                : 'Project Usage'}
            </h3>

            <p
              className={`text-sm mt-1 ${
                isAtLimit ? 'text-red-700' : isNearLimit ? 'text-yellow-700' : 'text-blue-700'
              }`}
            >
              You're using {currentProjectCount} of {maxProjects} projects
              {isAtLimit && ' - delete a project or upgrade to create more'}
              {isNearLimit && !isAtLimit && ' - consider upgrading for more capacity'}
            </p>

            {/* Progress Bar */}
            <div className="mt-3 w-full bg-gray-200 rounded-full h-2">
              <div
                className={`h-2 rounded-full transition-all ${
                  isAtLimit
                    ? 'bg-red-600'
                    : isNearLimit
                    ? 'bg-yellow-500'
                    : 'bg-blue-500'
                }`}
                style={{ width: `${Math.min(usagePercentage, 100)}%` }}
              ></div>
            </div>
          </div>
        </div>

        {!isPremium && (
          <Link
            to="/billing/plans"
            className={`flex-shrink-0 ml-4 px-4 py-2 rounded-lg font-medium text-sm transition ${
              isAtLimit
                ? 'bg-red-600 text-white hover:bg-red-700'
                : 'bg-blue-600 text-white hover:bg-blue-700'
            }`}
          >
            Upgrade
          </Link>
        )}
      </div>

      {/* Additional Info for Premium Users */}
      {isPremium && isAtLimit && (
        <div className="mt-3 pt-3 border-t border-red-200">
          <p className="text-sm text-red-700">
            You've reached the maximum projects for Premium ({maxProjects} projects). Delete a project to create a new one.
          </p>
        </div>
      )}

      {/* Additional Info for Free Users */}
      {!isPremium && (
        <div
          className={`mt-3 pt-3 ${
            isAtLimit ? 'border-t border-red-200' : 'border-t border-yellow-200'
          }`}
        >
          <div className="flex items-center justify-between text-sm">
            <span className={isAtLimit ? 'text-red-700' : 'text-yellow-700'}>
              Premium allows up to 5 projects
            </span>
            <Link
              to="/billing/plans"
              className={`font-medium ${
                isAtLimit ? 'text-red-800 hover:text-red-900' : 'text-yellow-800 hover:text-yellow-900'
              }`}
            >
              Learn More →
            </Link>
          </div>
        </div>
      )}
    </div>
  );
};

export default ProjectLimitBanner;
