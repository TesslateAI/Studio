import React, { useEffect, useState } from 'react';
import { billingApi } from '../../lib/api';
import UpgradeModal from './UpgradeModal';
import type { DeploymentLimitsResponse, BillingConfig } from '../../types/billing';

interface DeployButtonProps {
  projectSlug: string;
  isDeployed: boolean;
  onDeploySuccess?: () => void;
  onUndeploySuccess?: () => void;
  className?: string;
}

const DeployButton: React.FC<DeployButtonProps> = ({
  projectSlug,
  isDeployed,
  onDeploySuccess,
  onUndeploySuccess,
  className = '',
}) => {
  const [limits, setLimits] = useState<DeploymentLimitsResponse | null>(null);
  const [config, setConfig] = useState<BillingConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [deploying, setDeploying] = useState(false);
  const [showUpgradeModal, setShowUpgradeModal] = useState(false);
  const [showPurchaseSlotModal, setShowPurchaseSlotModal] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadLimits();
  }, []);

  const loadLimits = async () => {
    try {
      setLoading(true);

      const [limitsRes, configRes] = await Promise.all([
        billingApi.getDeploymentLimits(),
        billingApi.getConfig(),
      ]);

      setLimits(limitsRes.data);
      setConfig(configRes.data);
    } catch (err: any) {
      console.error('Failed to load deployment limits:', err);
      setError(err.response?.data?.detail || 'Failed to load deployment limits');
    } finally {
      setLoading(false);
    }
  };

  const handleDeploy = async () => {
    if (!limits || !config) return;

    // Check if can deploy
    if (!limits.can_deploy) {
      // Check if user is on free tier
      if (limits.subscription_tier === 'free') {
        setShowUpgradeModal(true);
        return;
      }

      // Premium user but hit limit - offer additional slot
      setShowPurchaseSlotModal(true);
      return;
    }

    try {
      setDeploying(true);
      setError(null);

      await billingApi.deployProject(projectSlug);

      if (onDeploySuccess) {
        onDeploySuccess();
      }

      await loadLimits();
    } catch (err: any) {
      console.error('Failed to deploy project:', err);
      setError(err.response?.data?.detail || 'Failed to deploy project');
    } finally {
      setDeploying(false);
    }
  };

  const handleUndeploy = async () => {
    const confirmed = window.confirm(
      'Are you sure you want to undeploy this project? The container will be stopped.'
    );

    if (!confirmed) return;

    try {
      setDeploying(true);
      setError(null);

      await billingApi.undeployProject(projectSlug);

      if (onUndeploySuccess) {
        onUndeploySuccess();
      }

      await loadLimits();
    } catch (err: any) {
      console.error('Failed to undeploy project:', err);
      setError(err.response?.data?.detail || 'Failed to undeploy project');
    } finally {
      setDeploying(false);
    }
  };

  const handlePurchaseSlot = async () => {
    if (!config) return;

    try {
      setError(null);

      const response = await billingApi.purchaseDeploySlot();

      // Redirect to Stripe Checkout
      if (response.data.url) {
        window.location.href = response.data.url;
      } else {
        throw new Error('No checkout URL received');
      }
    } catch (err: any) {
      console.error('Failed to purchase deploy slot:', err);
      setError(err.response?.data?.detail || 'Failed to purchase deploy slot');
    }
  };

  if (loading) {
    return (
      <button disabled className={`px-4 py-2 bg-gray-300 text-gray-600 rounded cursor-not-allowed ${className}`}>
        Loading...
      </button>
    );
  }

  if (!limits || !config) {
    return null;
  }

  return (
    <>
      <div className={className}>
        {error && (
          <div className="mb-2 p-2 bg-red-100 text-red-700 rounded text-sm">
            {error}
          </div>
        )}

        {/* Deploy Status Info */}
        {!isDeployed && (
          <div className="mb-3 text-sm text-gray-600">
            <div className="flex items-center space-x-2">
              <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
              </svg>
              <span>
                Deploys used: {limits.current_deploys} / {limits.max_deploys}
              </span>
            </div>
          </div>
        )}

        {/* Deploy/Undeploy Button */}
        {isDeployed ? (
          <button
            onClick={handleUndeploy}
            disabled={deploying}
            className="w-full px-4 py-2 bg-red-500 text-white rounded hover:bg-red-600 transition disabled:opacity-50 disabled:cursor-not-allowed font-medium"
          >
            {deploying ? 'Undeploying...' : 'Undeploy (Stop 24/7)'}
          </button>
        ) : (
          <button
            onClick={handleDeploy}
            disabled={deploying}
            className="w-full px-4 py-2 bg-green-500 text-white rounded hover:bg-green-600 transition disabled:opacity-50 disabled:cursor-not-allowed font-medium"
          >
            {deploying ? 'Deploying...' : 'Deploy (Run 24/7)'}
          </button>
        )}

        {/* Additional Slot Info */}
        {!limits.can_deploy && limits.subscription_tier === 'pro' && (
          <p className="mt-2 text-xs text-gray-600 text-center">
            You've reached your deploy limit. Purchase additional slots for ${(config.deploy_price / 100).toFixed(2)} each.
          </p>
        )}
      </div>

      {/* Upgrade Modal */}
      <UpgradeModal
        isOpen={showUpgradeModal}
        onClose={() => setShowUpgradeModal(false)}
        reason="deploys"
      />

      {/* Purchase Additional Slot Modal */}
      {showPurchaseSlotModal && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex items-center justify-center min-h-screen px-4 pt-4 pb-20 text-center sm:block sm:p-0">
            {/* Background overlay */}
            <div
              className="fixed inset-0 transition-opacity bg-gray-500 bg-opacity-75"
              onClick={() => setShowPurchaseSlotModal(false)}
            ></div>

            {/* Modal panel */}
            <div className="inline-block align-bottom bg-white rounded-lg text-left overflow-hidden shadow-xl transform transition-all sm:my-8 sm:align-middle sm:max-w-md sm:w-full">
              <div className="bg-white px-6 py-6">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-xl font-bold text-gray-900">
                    Deploy Limit Reached
                  </h3>
                  <button
                    onClick={() => setShowPurchaseSlotModal(false)}
                    className="text-gray-400 hover:text-gray-500"
                  >
                    <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>

                <p className="text-gray-700 mb-4">
                  You've deployed {limits.max_deploys} projects (your current limit). Purchase an additional deploy slot to keep this project running 24/7.
                </p>

                <div className="bg-blue-50 rounded-lg p-4 mb-6">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="font-semibold text-gray-900">Additional Deploy Slot</div>
                      <div className="text-sm text-gray-600">Keep one more project running 24/7</div>
                    </div>
                    <div className="text-2xl font-bold text-gray-900">
                      ${(config.deploy_price / 100).toFixed(2)}
                    </div>
                  </div>
                </div>

                <div className="flex space-x-3">
                  <button
                    onClick={handlePurchaseSlot}
                    className="flex-1 py-2 px-4 bg-blue-500 text-white rounded hover:bg-blue-600 transition font-medium"
                  >
                    Purchase Slot
                  </button>
                  <button
                    onClick={() => setShowPurchaseSlotModal(false)}
                    className="py-2 px-4 bg-gray-100 text-gray-700 rounded hover:bg-gray-200 transition font-medium"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default DeployButton;
