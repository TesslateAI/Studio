import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { billingApi } from '../../lib/api';
import type { BillingConfig } from '../../types/billing';

interface UpgradeModalProps {
  isOpen: boolean;
  onClose: () => void;
  reason?: 'projects' | 'deploys' | 'features' | 'general';
  title?: string;
  message?: string;
}

const UpgradeModal: React.FC<UpgradeModalProps> = ({
  isOpen,
  onClose,
  reason = 'general',
  title,
  message,
}) => {
  const [config, setConfig] = useState<BillingConfig | null>(null);
  const [upgrading, setUpgrading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      loadConfig();
    }
  }, [isOpen]);

  const loadConfig = async () => {
    try {
      const response = await billingApi.getConfig();
      setConfig(response.data);
    } catch (err) {
      console.error('Failed to load billing config:', err);
    }
  };

  const handleUpgrade = async () => {
    try {
      setUpgrading(true);
      setError(null);

      const response = await billingApi.subscribe();

      // Redirect to Stripe Checkout
      if (response.data.url) {
        window.location.href = response.data.url;
      } else {
        throw new Error('No checkout URL received');
      }
    } catch (err: any) {
      console.error('Failed to start subscription:', err);
      setError(err.response?.data?.detail || 'Failed to start subscription');
      setUpgrading(false);
    }
  };

  if (!isOpen) return null;

  // Reason-specific content
  const getContent = () => {
    switch (reason) {
      case 'projects':
        return {
          defaultTitle: 'Project Limit Reached',
          defaultMessage: `You've reached the maximum number of projects for the free tier (${config?.free_limits.max_projects || 1} project). Upgrade to Premium to create up to ${config?.premium_limits.max_projects || 5} projects.`,
          benefits: [
            `Create up to ${config?.premium_limits.max_projects || 5} projects`,
            'Deploy Mode (24/7 running containers)',
            'Use your own API keys',
            'Priority support',
          ],
        };
      case 'deploys':
        return {
          defaultTitle: 'Deploy Limit Reached',
          defaultMessage: `You've reached the maximum number of deployments for the free tier (${config?.free_limits.max_deploys || 1} deploy). Upgrade to Premium to deploy up to ${config?.premium_limits.max_deploys || 5} projects.`,
          benefits: [
            `Deploy up to ${config?.premium_limits.max_deploys || 5} projects`,
            'Keep containers running 24/7',
            'Purchase additional deploy slots',
            'Advanced monitoring',
          ],
        };
      case 'features':
        return {
          defaultTitle: 'Premium Feature',
          defaultMessage: 'This feature is only available for Premium subscribers. Upgrade to unlock all premium features.',
          benefits: [
            'Deploy Mode enabled',
            'Use your own API keys',
            'More projects and deploys',
            'Priority support',
          ],
        };
      default:
        return {
          defaultTitle: 'Upgrade to Premium',
          defaultMessage: 'Unlock more projects, deploys, and premium features.',
          benefits: [
            `${config?.premium_limits.max_projects || 5} projects`,
            `${config?.premium_limits.max_deploys || 5} deploys`,
            'Deploy Mode (24/7 running)',
            'Use your own API keys',
          ],
        };
    }
  };

  const content = getContent();
  const displayTitle = title || content.defaultTitle;
  const displayMessage = message || content.defaultMessage;

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex items-center justify-center min-h-screen px-4 pt-4 pb-20 text-center sm:block sm:p-0">
        {/* Background overlay */}
        <div
          className="fixed inset-0 transition-opacity bg-gray-500 bg-opacity-75"
          onClick={onClose}
        ></div>

        {/* Modal panel */}
        <div className="inline-block align-bottom bg-white rounded-lg text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-lg sm:w-full">
          {/* Icon */}
          <div className="bg-gradient-to-r from-blue-500 to-purple-600 px-6 pt-6 pb-4">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center space-x-3">
                <div className="flex-shrink-0 h-12 w-12 rounded-full bg-white bg-opacity-20 flex items-center justify-center">
                  <svg
                    className="h-6 w-6 text-white"
                    fill="currentColor"
                    viewBox="0 0 20 20"
                  >
                    <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
                  </svg>
                </div>
                <h3 className="text-2xl font-bold text-white">{displayTitle}</h3>
              </div>
              <button
                onClick={onClose}
                className="text-white hover:text-gray-200 transition"
              >
                <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>

          {/* Body */}
          <div className="px-6 py-6">
            <p className="text-gray-700 mb-6">{displayMessage}</p>

            {error && (
              <div className="mb-4 p-3 bg-red-100 text-red-700 rounded-lg text-sm">
                {error}
              </div>
            )}

            {/* Benefits */}
            <div className="mb-6">
              <h4 className="font-semibold text-gray-900 mb-3">Premium includes:</h4>
              <ul className="space-y-2">
                {content.benefits.map((benefit, idx) => (
                  <li key={idx} className="flex items-start">
                    <svg
                      className="h-5 w-5 text-green-500 mr-2 flex-shrink-0 mt-0.5"
                      fill="currentColor"
                      viewBox="0 0 20 20"
                    >
                      <path
                        fillRule="evenodd"
                        d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                        clipRule="evenodd"
                      />
                    </svg>
                    <span className="text-gray-700">{benefit}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* Pricing */}
            {config && (
              <div className="bg-gradient-to-r from-blue-50 to-purple-50 rounded-lg p-4 mb-6">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm text-gray-600">Premium</div>
                    <div className="text-3xl font-bold text-gray-900">
                      ${(config.premium_price / 100).toFixed(0)}
                      <span className="text-base font-normal text-gray-600">/month</span>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-xs text-gray-600">Cancel anytime</div>
                    <div className="text-xs text-gray-600">No hidden fees</div>
                  </div>
                </div>
              </div>
            )}

            {/* Actions */}
            <div className="flex space-x-3">
              <button
                onClick={handleUpgrade}
                disabled={upgrading}
                className="flex-1 py-3 px-6 bg-gradient-to-r from-blue-500 to-purple-600 text-white font-semibold rounded-lg hover:from-blue-600 hover:to-purple-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {upgrading ? (
                  <span className="flex items-center justify-center">
                    <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    Processing...
                  </span>
                ) : (
                  'Upgrade to Premium'
                )}
              </button>

              <Link
                to="/billing/plans"
                onClick={onClose}
                className="py-3 px-6 bg-gray-100 text-gray-700 font-semibold rounded-lg hover:bg-gray-200 transition text-center"
              >
                View Plans
              </Link>
            </div>

            <p className="text-xs text-center text-gray-500 mt-4">
              You'll be redirected to Stripe to complete your subscription securely
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default UpgradeModal;
