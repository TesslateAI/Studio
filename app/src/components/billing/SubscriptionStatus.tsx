import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { billingApi } from '../../lib/api';
import type {
  SubscriptionResponse,
  CreditBalanceResponse,
} from '../../types/billing';

interface SubscriptionStatusProps {
  compact?: boolean;
  showCredits?: boolean;
}

const SubscriptionStatus: React.FC<SubscriptionStatusProps> = ({
  compact = false,
  showCredits = true,
}) => {
  const [subscription, setSubscription] = useState<SubscriptionResponse | null>(null);
  const [credits, setCredits] = useState<CreditBalanceResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);

      const [subRes, creditsRes] = await Promise.all([
        billingApi.getSubscription(),
        showCredits ? billingApi.getCreditsBalance() : Promise.resolve({ data: null }),
      ]);

      setSubscription(subRes.data);
      if (showCredits && creditsRes.data) {
        setCredits(creditsRes.data);
      }
    } catch (err) {
      console.error('Failed to load subscription status:', err);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center space-x-2">
        <div className="animate-pulse bg-gray-200 h-6 w-20 rounded"></div>
      </div>
    );
  }

  if (!subscription) {
    return null;
  }

  const isPremium = subscription.tier === 'pro';

  if (compact) {
    return (
      <Link
        to="/billing"
        className="flex items-center space-x-2 px-3 py-1.5 rounded-lg hover:bg-gray-100 transition"
      >
        <div className={`flex items-center space-x-1.5 ${isPremium ? 'text-yellow-600' : 'text-gray-600'}`}>
          {isPremium ? (
            <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
              <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
            </svg>
          ) : (
            <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-11a1 1 0 10-2 0v2H7a1 1 0 100 2h2v2a1 1 0 102 0v-2h2a1 1 0 100-2h-2V7z" clipRule="evenodd" />
            </svg>
          )}
          <span className="text-sm font-medium">
            {isPremium ? 'Premium' : 'Free'}
          </span>
        </div>

        {showCredits && credits && (
          <div className="text-sm text-gray-600 border-l border-gray-300 pl-2">
            ${credits.balance_usd.toFixed(2)}
          </div>
        )}
      </Link>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-semibold text-gray-900">Subscription</h3>
        <Link
          to="/billing"
          className="text-sm text-blue-500 hover:text-blue-600 font-medium"
        >
          Manage
        </Link>
      </div>

      <div className="space-y-3">
        {/* Tier Badge */}
        <div className="flex items-center space-x-2">
          <div
            className={`flex items-center space-x-2 px-3 py-1.5 rounded-full ${
              isPremium
                ? 'bg-yellow-100 text-yellow-800'
                : 'bg-gray-100 text-gray-700'
            }`}
          >
            {isPremium ? (
              <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 20 20">
                <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
              </svg>
            ) : (
              <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-11a1 1 0 10-2 0v2H7a1 1 0 100 2h2v2a1 1 0 102 0v-2h2a1 1 0 100-2h-2V7z" clipRule="evenodd" />
              </svg>
            )}
            <span className="font-semibold">
              {isPremium ? 'Premium' : 'Free Plan'}
            </span>
          </div>
        </div>

        {/* Limits */}
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div className="bg-gray-50 rounded p-2">
            <div className="text-gray-600 text-xs">Projects</div>
            <div className="font-semibold text-gray-900">
              {subscription.max_projects}
            </div>
          </div>
          <div className="bg-gray-50 rounded p-2">
            <div className="text-gray-600 text-xs">Deploys</div>
            <div className="font-semibold text-gray-900">
              {subscription.max_deploys}
            </div>
          </div>
        </div>

        {/* Credits */}
        {showCredits && credits && (
          <div className="border-t pt-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-600">Credits Balance</span>
              <span className="text-lg font-semibold text-gray-900">
                ${credits.balance_usd.toFixed(2)}
              </span>
            </div>
            <Link
              to="/billing/credits"
              className="mt-2 block text-center text-sm text-blue-500 hover:text-blue-600 font-medium"
            >
              Add Credits
            </Link>
          </div>
        )}

        {/* Upgrade CTA */}
        {!isPremium && (
          <Link
            to="/billing/plans"
            className="block w-full py-2 px-4 bg-blue-500 text-white text-center rounded-lg hover:bg-blue-600 transition font-medium text-sm"
          >
            Upgrade to Premium
          </Link>
        )}
      </div>
    </div>
  );
};

export default SubscriptionStatus;
