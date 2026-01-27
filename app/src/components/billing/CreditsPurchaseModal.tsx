import React, { useEffect, useState } from 'react';
import { X, Coins, Info } from 'lucide-react';
import { billingApi } from '../../lib/api';
import toast from 'react-hot-toast';
import type { CreditBalanceResponse, CreditPackage } from '../../types/billing';

interface CreditsPurchaseModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

interface CreditPackageOption {
  id: CreditPackage;
  name: string;
  credits: number;
  price: number;
  popular?: boolean;
}

const CREDIT_PACKAGES: CreditPackageOption[] = [
  {
    id: 'small',
    name: 'Starter',
    credits: 500,
    price: 5,
  },
  {
    id: 'medium',
    name: 'Popular',
    credits: 1000,
    price: 10,
    popular: true,
  },
];

const CreditsPurchaseModal: React.FC<CreditsPurchaseModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
}) => {
  const [balance, setBalance] = useState<CreditBalanceResponse | null>(null);
  const [selectedPackage, setSelectedPackage] = useState<CreditPackage>('medium');
  const [loading, setLoading] = useState(true);
  const [purchasing, setPurchasing] = useState(false);

  useEffect(() => {
    if (isOpen) {
      loadBalance();
    }
  }, [isOpen]);

  const loadBalance = async () => {
    try {
      setLoading(true);
      const balanceRes = await billingApi.getCreditsBalance();
      setBalance(balanceRes);
    } catch (err) {
      console.error('Failed to load credits balance:', err);
    } finally {
      setLoading(false);
    }
  };

  const handlePurchase = async () => {
    if (!selectedPackage) return;

    try {
      setPurchasing(true);
      const response = await billingApi.purchaseCredits(selectedPackage);

      if (response.url) {
        window.location.href = response.url;
        if (onSuccess) {
          onSuccess();
        }
      } else {
        throw new Error('No checkout URL received');
      }
    } catch (err) {
      console.error('Failed to purchase credits:', err);
      toast.error('Failed to start credit purchase');
      setPurchasing(false);
    }
  };

  if (!isOpen) return null;

  const selectedPkg = CREDIT_PACKAGES.find((p) => p.id === selectedPackage);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className="bg-[var(--surface)] border border-white/10 rounded-2xl max-w-md w-full overflow-hidden">
        {/* Header */}
        <div className="p-6 border-b border-white/10">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-[var(--primary)]/20 rounded-xl flex items-center justify-center">
                <Coins className="w-5 h-5 text-[var(--primary)]" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-[var(--text)]">Purchase Credits</h2>
                <p className="text-sm text-[var(--text)]/50">Add credits that never expire</p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-2 text-[var(--text)]/40 hover:text-[var(--text)]/60 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Current Balance */}
          {!loading && balance && (
            <div className="mt-4 p-3 bg-white/5 rounded-xl">
              <div className="flex items-center justify-between">
                <span className="text-sm text-[var(--text)]/60">Current Balance</span>
                <span className="text-lg font-bold text-[var(--text)]">
                  {balance.total_credits.toLocaleString()} credits
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Body */}
        <div className="p-6">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[var(--primary)]"></div>
            </div>
          ) : (
            <>
              {/* Package Options */}
              <div className="space-y-3 mb-6">
                {CREDIT_PACKAGES.map((pkg) => (
                  <button
                    key={pkg.id}
                    onClick={() => setSelectedPackage(pkg.id)}
                    className={`relative w-full p-4 rounded-xl border-2 transition-all text-left ${
                      selectedPackage === pkg.id
                        ? 'border-[var(--primary)] bg-[var(--primary)]/10'
                        : 'border-white/10 bg-white/5 hover:border-white/20'
                    }`}
                  >
                    {pkg.popular && (
                      <div className="absolute -top-2 right-4 bg-[var(--primary)] text-white text-xs font-bold px-2 py-0.5 rounded">
                        POPULAR
                      </div>
                    )}

                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div
                          className={`w-5 h-5 rounded-full border-2 flex items-center justify-center ${
                            selectedPackage === pkg.id
                              ? 'border-[var(--primary)] bg-[var(--primary)]'
                              : 'border-white/30'
                          }`}
                        >
                          {selectedPackage === pkg.id && (
                            <div className="w-2 h-2 bg-white rounded-full" />
                          )}
                        </div>
                        <div>
                          <div className="font-semibold text-[var(--text)]">
                            +{pkg.credits.toLocaleString()} credits
                          </div>
                          <div className="text-sm text-[var(--text)]/50">{pkg.name}</div>
                        </div>
                      </div>
                      <div className="text-xl font-bold text-[var(--text)]">${pkg.price}</div>
                    </div>
                  </button>
                ))}
              </div>

              {/* Info Box */}
              <div className="bg-white/5 rounded-xl p-4 mb-6">
                <div className="flex items-start gap-3">
                  <Info className="w-5 h-5 text-[var(--primary)] flex-shrink-0 mt-0.5" />
                  <div>
                    <h4 className="font-medium text-[var(--text)] mb-1">How Credits Work</h4>
                    <ul className="text-sm text-[var(--text)]/60 space-y-1">
                      <li>• Purchased credits never expire</li>
                      <li>• Bundled credits are used first each month</li>
                      <li>• 1 credit = $0.01 of AI usage</li>
                    </ul>
                  </div>
                </div>
              </div>

              {/* Purchase Button */}
              <button
                onClick={handlePurchase}
                disabled={purchasing || !selectedPackage}
                className="w-full py-3 px-6 bg-[var(--primary)] text-white font-semibold rounded-xl hover:bg-[var(--primary-hover)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {purchasing ? (
                  <span className="flex items-center justify-center gap-2">
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                    Processing...
                  </span>
                ) : (
                  `Purchase ${selectedPkg?.credits.toLocaleString()} Credits for $${selectedPkg?.price}`
                )}
              </button>

              <p className="text-xs text-[var(--text)]/40 text-center mt-4">
                Secure checkout powered by Stripe
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default CreditsPurchaseModal;
