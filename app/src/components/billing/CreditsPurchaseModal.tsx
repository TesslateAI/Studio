import React, { useEffect, useState } from 'react';
import { billingApi } from '../../lib/api';
import type {
  BillingConfig,
  CreditBalanceResponse,
  CreditPackage,
} from '../../types/billing';

interface CreditsPurchaseModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

interface CreditPackageOption {
  id: CreditPackage;
  name: string;
  amount_cents: number;
  amount_usd: string;
  popular?: boolean;
}

const CreditsPurchaseModal: React.FC<CreditsPurchaseModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
}) => {
  const [config, setConfig] = useState<BillingConfig | null>(null);
  const [balance, setBalance] = useState<CreditBalanceResponse | null>(null);
  const [selectedPackage, setSelectedPackage] = useState<CreditPackage>('medium');
  const [loading, setLoading] = useState(true);
  const [purchasing, setPurchasing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      loadData();
    }
  }, [isOpen]);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);

      const [configRes, balanceRes] = await Promise.all([
        billingApi.getConfig(),
        billingApi.getCreditsBalance(),
      ]);

      setConfig(configRes);
      setBalance(balanceRes);
    } catch (err: any) {
      console.error('Failed to load credits data:', err);
      setError(err.response?.data?.detail || 'Failed to load credits information');
    } finally {
      setLoading(false);
    }
  };

  const handlePurchase = async () => {
    if (!selectedPackage) return;

    try {
      setPurchasing(true);
      setError(null);

      const response = await billingApi.purchaseCredits(selectedPackage);

      // Redirect to Stripe Checkout
      if (response.url) {
        window.location.href = response.url;
        if (onSuccess) {
          onSuccess();
        }
      } else {
        throw new Error('No checkout URL received');
      }
    } catch (err: any) {
      console.error('Failed to purchase credits:', err);
      setError(err.response?.data?.detail || 'Failed to start credit purchase');
      setPurchasing(false);
    }
  };

  if (!isOpen) return null;

  const packages: CreditPackageOption[] = config
    ? [
        {
          id: 'small',
          name: 'Starter',
          amount_cents: config.credit_packages.small,
          amount_usd: (config.credit_packages.small / 100).toFixed(2),
        },
        {
          id: 'medium',
          name: 'Popular',
          amount_cents: config.credit_packages.medium,
          amount_usd: (config.credit_packages.medium / 100).toFixed(2),
          popular: true,
        },
        {
          id: 'large',
          name: 'Best Value',
          amount_cents: config.credit_packages.large,
          amount_usd: (config.credit_packages.large / 100).toFixed(2),
        },
      ]
    : [];

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
          {/* Header */}
          <div className="bg-white px-6 pt-6 pb-4">
            <div className="flex items-center justify-between">
              <h3 className="text-2xl font-bold text-gray-900">
                Purchase Credits
              </h3>
              <button
                onClick={onClose}
                className="text-gray-400 hover:text-gray-500 transition"
              >
                <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Current Balance */}
            {balance && (
              <div className="mt-4 bg-blue-50 rounded-lg p-4">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-blue-800">Current Balance</span>
                  <span className="text-2xl font-bold text-blue-900">
                    ${balance.balance_usd.toFixed(2)}
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* Body */}
          <div className="px-6 pb-6">
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
              </div>
            ) : error ? (
              <div className="p-4 bg-red-100 text-red-700 rounded-lg mb-4">
                {error}
              </div>
            ) : (
              <>
                <p className="text-gray-600 mb-6">
                  Credits are used to pay for AI usage costs. Purchase credits to avoid monthly invoices.
                </p>

                {/* Package Options */}
                <div className="space-y-3 mb-6">
                  {packages.map((pkg) => (
                    <div
                      key={pkg.id}
                      onClick={() => setSelectedPackage(pkg.id)}
                      className={`relative border-2 rounded-lg p-4 cursor-pointer transition ${
                        selectedPackage === pkg.id
                          ? 'border-blue-500 bg-blue-50'
                          : 'border-gray-200 hover:border-gray-300'
                      }`}
                    >
                      {pkg.popular && (
                        <div className="absolute top-0 right-0 bg-blue-500 text-white text-xs px-2 py-1 rounded-bl rounded-tr">
                          POPULAR
                        </div>
                      )}

                      <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-3">
                          <div
                            className={`w-5 h-5 rounded-full border-2 flex items-center justify-center ${
                              selectedPackage === pkg.id
                                ? 'border-blue-500 bg-blue-500'
                                : 'border-gray-300'
                            }`}
                          >
                            {selectedPackage === pkg.id && (
                              <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                                <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                              </svg>
                            )}
                          </div>
                          <div>
                            <div className="font-semibold text-gray-900">{pkg.name}</div>
                            <div className="text-sm text-gray-500">
                              ${pkg.amount_usd} in credits
                            </div>
                          </div>
                        </div>
                        <div className="text-2xl font-bold text-gray-900">
                          ${pkg.amount_usd}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Info Box */}
                <div className="bg-gray-50 rounded-lg p-4 mb-6">
                  <h4 className="font-semibold text-gray-900 mb-2 flex items-center">
                    <svg className="h-5 w-5 mr-2 text-blue-500" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
                    </svg>
                    How Credits Work
                  </h4>
                  <ul className="text-sm text-gray-600 space-y-1">
                    <li>• Credits are used for AI model usage costs</li>
                    <li>• Credits are deducted before charging your card</li>
                    <li>• Credits never expire</li>
                    <li>• Get detailed usage breakdowns in your dashboard</li>
                  </ul>
                </div>

                {/* Purchase Button */}
                <button
                  onClick={handlePurchase}
                  disabled={purchasing || !selectedPackage}
                  className="w-full py-3 px-6 bg-blue-500 text-white font-semibold rounded-lg hover:bg-blue-600 transition disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {purchasing ? (
                    <span className="flex items-center justify-center">
                      <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                      </svg>
                      Processing...
                    </span>
                  ) : (
                    `Purchase $${packages.find(p => p.id === selectedPackage)?.amount_usd} Credits`
                  )}
                </button>

                <p className="text-xs text-gray-500 text-center mt-4">
                  You'll be redirected to Stripe to complete your purchase securely
                </p>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default CreditsPurchaseModal;
