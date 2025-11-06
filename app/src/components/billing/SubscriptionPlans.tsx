import React, { useEffect, useState } from 'react';
import { billingApi } from '../../lib/api';
import type {
  BillingConfig,
  SubscriptionResponse,
} from '../../types/billing';

interface PricingFeature {
  name: string;
  free: boolean | string;
  premium: boolean | string;
}

const SubscriptionPlans: React.FC = () => {
  const [config, setConfig] = useState<BillingConfig | null>(null);
  const [subscription, setSubscription] = useState<SubscriptionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [subscribing, setSubscribing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);

      const [configRes, subRes] = await Promise.all([
        billingApi.getConfig(),
        billingApi.getSubscription(),
      ]);

      setConfig(configRes);
      setSubscription(subRes);
    } catch (err: any) {
      console.error('Failed to load billing data:', err);
      setError(err.response?.data?.detail || 'Failed to load billing information');
    } finally {
      setLoading(false);
    }
  };

  const handleUpgrade = async () => {
    if (!subscription || subscription.tier === 'pro') return;

    try {
      setSubscribing(true);
      setError(null);

      const response = await billingApi.subscribe();

      // Redirect to Stripe Checkout
      if (response.url) {
        window.location.href = response.url;
      } else {
        throw new Error('No checkout URL received');
      }
    } catch (err: any) {
      console.error('Failed to start subscription:', err);
      setError(err.response?.data?.detail || 'Failed to start subscription');
      setSubscribing(false);
    }
  };

  const handleManageSubscription = async () => {
    try {
      const response = await billingApi.getCustomerPortal();

      // Redirect to Stripe Customer Portal
      if (response.url) {
        window.location.href = response.url;
      }
    } catch (err: any) {
      console.error('Failed to open customer portal:', err);
      const errorDetail = err.response?.data?.detail || 'Failed to open customer portal';

      // If portal not configured, redirect to library subscriptions tab
      if (err.response?.status === 503 || errorDetail.includes('not configured')) {
        if (confirm(errorDetail + '\n\nWould you like to go to Library > Subscriptions to manage your subscription?')) {
          window.location.href = '/library?tab=subscriptions';
        }
      } else {
        setError(errorDetail);
      }
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mx-auto"></div>
          <p className="mt-4 text-gray-600">Loading pricing information...</p>
        </div>
      </div>
    );
  }

  if (!config || !subscription) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <p className="text-red-600">Failed to load billing information</p>
          {error && <p className="text-sm text-gray-600 mt-2">{error}</p>}
          <button
            onClick={loadData}
            className="mt-4 px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const features: PricingFeature[] = [
    {
      name: 'Active Projects',
      free: `${config.free_limits.max_projects} project`,
      premium: `${config.premium_limits.max_projects} projects`,
    },
    {
      name: 'Deployed Projects',
      free: `${config.free_limits.max_deploys} deploy`,
      premium: `${config.premium_limits.max_deploys} deploys`,
    },
    {
      name: 'Deploy Mode (24/7 Running)',
      free: false,
      premium: true,
    },
    {
      name: 'Use Your Own API Keys',
      free: false,
      premium: true,
    },
    {
      name: 'Marketplace Access',
      free: true,
      premium: true,
    },
    {
      name: 'Agent Creation',
      free: true,
      premium: true,
    },
    {
      name: 'Creator Revenue (90/10 Split)',
      free: true,
      premium: true,
    },
    {
      name: 'Credit Purchases',
      free: true,
      premium: true,
    },
    {
      name: 'Additional Deploy Slots',
      free: `$${(config.deploy_price / 100).toFixed(2)} each`,
      premium: `$${(config.deploy_price / 100).toFixed(2)} each`,
    },
  ];

  const isCurrentlyPremium = subscription.tier === 'pro';

  return (
    <div className="min-h-screen bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="text-center mb-12">
          <h1 className="text-4xl font-bold text-gray-900 mb-4">
            Choose Your Plan
          </h1>
          <p className="text-xl text-gray-600">
            Start free, upgrade when you need more power
          </p>
          {isCurrentlyPremium && (
            <div className="mt-4 inline-block bg-green-100 text-green-800 px-4 py-2 rounded-full">
              You're currently on Premium
            </div>
          )}
        </div>

        {error && (
          <div className="mb-6 p-4 bg-red-100 text-red-700 rounded-lg">
            {error}
          </div>
        )}

        {/* Pricing Cards */}
        <div className="grid md:grid-cols-2 gap-8 mb-12">
          {/* Free Plan */}
          <div className="bg-white rounded-lg shadow-lg p-8 border-2 border-gray-200">
            <div className="text-center mb-6">
              <h2 className="text-2xl font-bold text-gray-900 mb-2">Free</h2>
              <div className="text-4xl font-bold text-gray-900 mb-2">$0</div>
              <div className="text-gray-600">Forever free</div>
            </div>

            <ul className="space-y-4 mb-8">
              {features.map((feature, idx) => (
                <li key={idx} className="flex items-start">
                  <span className="flex-shrink-0 mr-3">
                    {feature.free === true ? (
                      <svg className="h-5 w-5 text-green-500" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                    ) : feature.free === false ? (
                      <svg className="h-5 w-5 text-gray-300" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                      </svg>
                    ) : (
                      <svg className="h-5 w-5 text-blue-500" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                    )}
                  </span>
                  <div>
                    <span className="text-gray-900">{feature.name}</span>
                    {typeof feature.free === 'string' && (
                      <span className="block text-sm text-gray-500">{feature.free}</span>
                    )}
                  </div>
                </li>
              ))}
            </ul>

            {!isCurrentlyPremium ? (
              <button
                disabled
                className="w-full py-3 px-6 rounded-lg bg-gray-100 text-gray-500 font-semibold cursor-not-allowed"
              >
                Current Plan
              </button>
            ) : (
              <button
                disabled
                className="w-full py-3 px-6 rounded-lg bg-gray-200 text-gray-600 font-semibold cursor-not-allowed opacity-50"
              >
                Downgrade (Contact Support)
              </button>
            )}
          </div>

          {/* Premium Plan */}
          <div className="bg-white rounded-lg shadow-lg p-8 border-2 border-blue-500 relative">
            <div className="absolute top-0 right-0 bg-blue-500 text-white px-4 py-1 rounded-bl-lg rounded-tr-lg text-sm font-semibold">
              POPULAR
            </div>

            <div className="text-center mb-6">
              <h2 className="text-2xl font-bold text-gray-900 mb-2">Premium</h2>
              <div className="text-4xl font-bold text-gray-900 mb-2">
                ${(config.premium_price / 100).toFixed(0)}
              </div>
              <div className="text-gray-600">Per month</div>
            </div>

            <ul className="space-y-4 mb-8">
              {features.map((feature, idx) => (
                <li key={idx} className="flex items-start">
                  <span className="flex-shrink-0 mr-3">
                    {feature.premium === true || typeof feature.premium === 'string' ? (
                      <svg className="h-5 w-5 text-green-500" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                    ) : (
                      <svg className="h-5 w-5 text-gray-300" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                      </svg>
                    )}
                  </span>
                  <div>
                    <span className="text-gray-900 font-medium">{feature.name}</span>
                    {typeof feature.premium === 'string' && (
                      <span className="block text-sm text-gray-500">{feature.premium}</span>
                    )}
                  </div>
                </li>
              ))}
            </ul>

            {isCurrentlyPremium ? (
              <button
                onClick={handleManageSubscription}
                className="w-full py-3 px-6 rounded-lg bg-gray-100 text-gray-700 font-semibold hover:bg-gray-200 transition"
              >
                Manage Subscription
              </button>
            ) : (
              <button
                onClick={handleUpgrade}
                disabled={subscribing}
                className="w-full py-3 px-6 rounded-lg bg-blue-500 text-white font-semibold hover:bg-blue-600 transition disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {subscribing ? 'Processing...' : 'Upgrade to Premium'}
              </button>
            )}
          </div>
        </div>

        {/* Additional Information */}
        <div className="bg-white rounded-lg shadow p-8">
          <h3 className="text-xl font-bold text-gray-900 mb-4">Frequently Asked Questions</h3>

          <div className="space-y-6">
            <div>
              <h4 className="font-semibold text-gray-900 mb-2">Can I cancel anytime?</h4>
              <p className="text-gray-600">
                Yes! You can cancel your premium subscription at any time. Your access will continue until the end of your billing period.
              </p>
            </div>

            <div>
              <h4 className="font-semibold text-gray-900 mb-2">What are credits?</h4>
              <p className="text-gray-600">
                Credits are prepaid funds you can use for AI usage costs. You can purchase credits in $5, $10, or $50 packages. Credits are deducted before charging your card for monthly usage.
              </p>
            </div>

            <div>
              <h4 className="font-semibold text-gray-900 mb-2">How does Deploy Mode work?</h4>
              <p className="text-gray-600">
                Deploy Mode keeps your containerized applications running 24/7. Premium users get {config.premium_limits.max_deploys} deploy slots. Additional slots are ${(config.deploy_price / 100).toFixed(2)} each.
              </p>
            </div>

            <div>
              <h4 className="font-semibold text-gray-900 mb-2">How do creator earnings work?</h4>
              <p className="text-gray-600">
                When you publish agents to the marketplace, you earn 90% of the revenue from purchases and usage. The platform takes 10%. You can connect your Stripe account to receive payouts.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SubscriptionPlans;
