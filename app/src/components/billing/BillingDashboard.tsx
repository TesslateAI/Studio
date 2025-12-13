import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { billingApi } from '../../lib/api';
import type {
  SubscriptionResponse,
  CreditBalanceResponse,
  Transaction,
  CreditPurchase,
} from '../../types/billing';

const BillingDashboard: React.FC = () => {
  const navigate = useNavigate();
  const [subscription, setSubscription] = useState<SubscriptionResponse | null>(null);
  const [credits, setCredits] = useState<CreditBalanceResponse | null>(null);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [creditHistory, setCreditHistory] = useState<CreditPurchase[]>([]);
  const [loading, setLoading] = useState(true);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);

      const [subRes, creditsRes, transRes, historyRes] = await Promise.all([
        billingApi.getSubscription(),
        billingApi.getCreditsBalance(),
        billingApi.getTransactions(10, 0),
        billingApi.getCreditsHistory(10, 0),
      ]);

      setSubscription(subRes);
      setCredits(creditsRes);
      setTransactions(transRes.transactions);
      setCreditHistory(historyRes.purchases);
    } catch (err: any) {
      console.error('Failed to load billing data:', err);
      setError(err.response?.data?.detail || 'Failed to load billing information');
    } finally {
      setLoading(false);
    }
  };

  const handleCancelSubscription = async () => {
    if (!subscription || subscription.tier === 'free') return;

    const confirmed = window.confirm(
      'Are you sure you want to cancel your subscription? You will continue to have access until the end of your billing period.'
    );

    if (!confirmed) return;

    try {
      setCancelling(true);
      setError(null);

      await billingApi.cancelSubscription(true);

      alert('Subscription cancelled. You will have access until the end of your billing period.');
      await loadData();
    } catch (err: any) {
      console.error('Failed to cancel subscription:', err);
      setError(err.response?.data?.detail || 'Failed to cancel subscription');
    } finally {
      setCancelling(false);
    }
  };

  const handleManageSubscription = async () => {
    try {
      const response = await billingApi.getCustomerPortal();
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

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  };

  const getTransactionTypeLabel = (type: string) => {
    const labels: Record<string, string> = {
      credit_purchase: 'Credit Purchase',
      agent_purchase_onetime: 'Agent Purchase',
      agent_purchase_monthly: 'Agent Subscription',
      usage_invoice: 'Usage Invoice',
      deploy_slot_purchase: 'Deploy Slot',
    };
    return labels[type] || type;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mx-auto"></div>
          <p className="mt-4 text-gray-600">Loading billing information...</p>
        </div>
      </div>
    );
  }

  const isPremium = subscription?.tier === 'pro';

  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4 sm:px-6 lg:px-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <button
            onClick={() => navigate('/dashboard')}
            className="flex items-center gap-2 text-gray-600 hover:text-gray-900 mb-4 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
            <span className="text-sm font-medium">Back to Dashboard</span>
          </button>
          <h1 className="text-3xl font-bold text-gray-900">Billing & Subscription</h1>
          <p className="text-gray-600 mt-2">Manage your subscription, credits, and billing</p>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-red-100 text-red-700 rounded-lg">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
          {/* Subscription Card */}
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-gray-900">Subscription</h2>
              {isPremium ? (
                <span className="flex items-center space-x-1 bg-yellow-100 text-yellow-800 px-3 py-1 rounded-full text-sm font-semibold">
                  <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
                  </svg>
                  <span>Premium</span>
                </span>
              ) : (
                <span className="bg-gray-100 text-gray-700 px-3 py-1 rounded-full text-sm font-semibold">
                  Free
                </span>
              )}
            </div>

            <div className="space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-gray-600">Projects</span>
                <span className="font-semibold">{subscription?.max_projects}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-600">Deploys</span>
                <span className="font-semibold">{subscription?.max_deploys}</span>
              </div>

              {isPremium ? (
                <div className="pt-3 border-t space-y-2">
                  <button
                    onClick={handleManageSubscription}
                    className="w-full py-2 px-4 bg-gray-100 text-gray-700 rounded hover:bg-gray-200 transition text-sm font-medium"
                  >
                    Manage Subscription
                  </button>
                  <button
                    onClick={handleCancelSubscription}
                    disabled={cancelling}
                    className="w-full py-2 px-4 bg-red-50 text-red-600 rounded hover:bg-red-100 transition text-sm font-medium disabled:opacity-50"
                  >
                    {cancelling ? 'Cancelling...' : 'Cancel Subscription'}
                  </button>
                </div>
              ) : (
                <div className="pt-3 border-t">
                  <Link
                    to="/billing/plans"
                    className="block w-full py-2 px-4 bg-blue-500 text-white text-center rounded hover:bg-blue-600 transition text-sm font-medium"
                  >
                    Upgrade to Premium
                  </Link>
                </div>
              )}
            </div>
          </div>

          {/* Credits Card */}
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Credits</h2>

            <div className="mb-4">
              <div className="text-3xl font-bold text-gray-900">
                ${credits?.balance_usd.toFixed(2) || '0.00'}
              </div>
              <div className="text-sm text-gray-600">Available Balance</div>
            </div>

            <Link
              to="/library?tab=credits"
              className="block w-full py-2 px-4 bg-blue-500 text-white text-center rounded hover:bg-blue-600 transition text-sm font-medium"
            >
              Purchase Credits
            </Link>

            <div className="mt-4 pt-4 border-t">
              <Link
                to="/billing/usage"
                className="text-sm text-blue-500 hover:text-blue-600 font-medium"
              >
                View Usage Details →
              </Link>
            </div>
          </div>

          {/* Quick Stats Card */}
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Quick Stats</h2>

            <div className="space-y-3">
              <div>
                <div className="text-sm text-gray-600">Recent Transactions</div>
                <div className="text-2xl font-bold text-gray-900">
                  {transactions.length}
                </div>
              </div>

              <div>
                <div className="text-sm text-gray-600">Credit Purchases</div>
                <div className="text-2xl font-bold text-gray-900">
                  {creditHistory.length}
                </div>
              </div>

              <Link
                to="/billing/transactions"
                className="block mt-4 text-sm text-blue-500 hover:text-blue-600 font-medium"
              >
                View All Transactions →
              </Link>
            </div>
          </div>
        </div>

        {/* Recent Transactions */}
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-semibold text-gray-900">Recent Transactions</h2>
          </div>

          <div className="overflow-x-auto">
            {transactions.length === 0 ? (
              <div className="text-center py-12">
                <svg
                  className="mx-auto h-12 w-12 text-gray-400"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"
                  />
                </svg>
                <p className="mt-4 text-gray-600">No transactions yet</p>
              </div>
            ) : (
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Date
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Type
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Status
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Amount
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {transactions.slice(0, 10).map((transaction) => (
                    <tr key={transaction.id} className="hover:bg-gray-50">
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                        {formatDate(transaction.created_at)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                        {getTransactionTypeLabel(transaction.type)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span
                          className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                            transaction.status === 'completed'
                              ? 'bg-green-100 text-green-800'
                              : transaction.status === 'pending'
                              ? 'bg-yellow-100 text-yellow-800'
                              : 'bg-red-100 text-red-800'
                          }`}
                        >
                          {transaction.status}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-right font-semibold text-gray-900">
                        ${transaction.amount_usd.toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {transactions.length > 10 && (
            <div className="px-6 py-4 border-t border-gray-200 text-center">
              <Link
                to="/billing/transactions"
                className="text-sm text-blue-500 hover:text-blue-600 font-medium"
              >
                View All Transactions →
              </Link>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default BillingDashboard;
