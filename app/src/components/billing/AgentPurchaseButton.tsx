import React, { useState } from 'react';
import { api } from '../../lib/api';

interface Agent {
  id: string;
  name: string;
  pricing_type: 'free' | 'monthly' | 'onetime' | 'api';
  price?: number; // in cents
  api_pricing_input?: number; // $ per million tokens
  api_pricing_output?: number; // $ per million tokens
}

interface AgentPurchaseButtonProps {
  agent: Agent;
  isPurchased?: boolean;
  onPurchaseSuccess?: () => void;
  className?: string;
}

const AgentPurchaseButton: React.FC<AgentPurchaseButtonProps> = ({
  agent,
  isPurchased = false,
  onPurchaseSuccess,
  className = '',
}) => {
  const [purchasing, setPurchasing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handlePurchase = async () => {
    if (agent.pricing_type === 'free' || isPurchased) {
      return;
    }

    try {
      setPurchasing(true);
      setError(null);

      // Call the marketplace agent purchase endpoint
      const response = await api.post(`/api/marketplace/agents/${agent.id}/purchase`);

      // Redirect to Stripe Checkout
      if (response.data.checkout_url) {
        window.location.href = response.data.checkout_url;

        if (onPurchaseSuccess) {
          onPurchaseSuccess();
        }
      } else {
        throw new Error('No checkout URL received');
      }
    } catch (err: any) {
      console.error('Failed to purchase agent:', err);
      setError(err.response?.data?.detail || 'Failed to start purchase');
      setPurchasing(false);
    }
  };

  const getPriceDisplay = () => {
    switch (agent.pricing_type) {
      case 'free':
        return 'Free';
      case 'monthly':
        return agent.price ? `$${(agent.price / 100).toFixed(2)}/month` : 'Subscribe';
      case 'onetime':
        return agent.price ? `$${(agent.price / 100).toFixed(2)}` : 'Purchase';
      case 'api':
        if (agent.api_pricing_input && agent.api_pricing_output) {
          return `$${agent.api_pricing_input}/M in + $${agent.api_pricing_output}/M out`;
        }
        return 'Pay per use';
      default:
        return 'Get Agent';
    }
  };

  const getButtonText = () => {
    if (isPurchased) {
      return 'Purchased';
    }

    if (purchasing) {
      return 'Processing...';
    }

    switch (agent.pricing_type) {
      case 'free':
        return 'Add to Library';
      case 'monthly':
        return 'Subscribe';
      case 'onetime':
        return 'Purchase';
      case 'api':
        return 'Enable Agent';
      default:
        return 'Get Agent';
    }
  };

  const getButtonStyle = () => {
    if (isPurchased) {
      return 'bg-gray-300 text-gray-600 cursor-not-allowed';
    }

    if (agent.pricing_type === 'free') {
      return 'bg-green-500 hover:bg-green-600 text-white';
    }

    return 'bg-blue-500 hover:bg-blue-600 text-white';
  };

  return (
    <div className={className}>
      {error && (
        <div className="mb-2 p-2 bg-red-100 text-red-700 rounded text-sm">
          {error}
        </div>
      )}

      {/* Pricing Display */}
      <div className="mb-3">
        <div className="text-2xl font-bold text-gray-900">
          {getPriceDisplay()}
        </div>
        {agent.pricing_type === 'api' && (
          <div className="text-xs text-gray-500 mt-1">
            Charged based on actual usage
          </div>
        )}
        {agent.pricing_type === 'monthly' && !isPurchased && (
          <div className="text-xs text-gray-500 mt-1">
            Recurring monthly subscription
          </div>
        )}
      </div>

      {/* Purchase Button */}
      <button
        onClick={handlePurchase}
        disabled={purchasing || isPurchased || agent.pricing_type === 'free'}
        className={`w-full py-3 px-6 rounded-lg font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed ${getButtonStyle()}`}
      >
        {getButtonText()}
      </button>

      {/* Additional Info */}
      {agent.pricing_type === 'api' && !isPurchased && (
        <div className="mt-3 p-3 bg-blue-50 rounded-lg text-sm">
          <div className="flex items-start space-x-2">
            <svg className="h-5 w-5 text-blue-500 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
            </svg>
            <div className="text-blue-700">
              <strong>Pay per use:</strong> You'll only be charged for the tokens you use. Credits are deducted first, then your card is charged monthly.
            </div>
          </div>
        </div>
      )}

      {agent.pricing_type === 'monthly' && !isPurchased && (
        <div className="mt-3 p-3 bg-yellow-50 rounded-lg text-sm">
          <div className="flex items-start space-x-2">
            <svg className="h-5 w-5 text-yellow-500 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
            </svg>
            <div className="text-yellow-700">
              <strong>Subscription:</strong> Cancel anytime. You'll continue to have access until the end of your billing period.
            </div>
          </div>
        </div>
      )}

      {isPurchased && (
        <div className="mt-3 flex items-center justify-center space-x-2 text-sm text-green-600">
          <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
          </svg>
          <span className="font-medium">Added to your library</span>
        </div>
      )}

      {/* Creator Revenue Info */}
      {!isPurchased && agent.pricing_type !== 'free' && (
        <div className="mt-4 pt-3 border-t border-gray-200 text-xs text-gray-500 text-center">
          90% goes to the creator, 10% supports the platform
        </div>
      )}
    </div>
  );
};

export default AgentPurchaseButton;
