import { Warning, X, CheckCircle, Info, Trash } from '@phosphor-icons/react';

interface ConfirmDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  variant?: 'danger' | 'warning' | 'info';
  isLoading?: boolean;
}

export function ConfirmDialog({
  isOpen,
  onClose,
  onConfirm,
  title,
  message,
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  variant = 'info',
  isLoading = false
}: ConfirmDialogProps) {
  if (!isOpen) return null;

  const handleConfirm = () => {
    if (!isLoading) {
      onConfirm();
    }
  };

  const handleClose = () => {
    if (!isLoading) {
      onClose();
    }
  };

  const getVariantStyles = () => {
    switch (variant) {
      case 'danger':
        return {
          iconBg: 'bg-red-500/20',
          iconColor: 'text-red-400',
          icon: Trash,
          confirmButton: 'bg-red-500 hover:bg-red-600 disabled:bg-gray-600'
        };
      case 'warning':
        return {
          iconBg: 'bg-yellow-500/20',
          iconColor: 'text-yellow-400',
          icon: Warning,
          confirmButton: 'bg-yellow-500 hover:bg-yellow-600 disabled:bg-gray-600'
        };
      case 'info':
      default:
        return {
          iconBg: 'bg-blue-500/20',
          iconColor: 'text-blue-400',
          icon: CheckCircle,
          confirmButton: 'bg-blue-500 hover:bg-blue-600 disabled:bg-gray-600'
        };
    }
  };

  const styles = getVariantStyles();
  const Icon = styles.icon;

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50"
      onClick={handleClose}
    >
      <div
        className="bg-[var(--surface)] p-8 rounded-3xl w-full max-w-md shadow-2xl border border-white/10 animate-in fade-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between mb-6">
          <div className="flex items-start gap-4 flex-1">
            <div className={`w-12 h-12 ${styles.iconBg} rounded-xl flex items-center justify-center flex-shrink-0`}>
              <Icon className={`w-6 h-6 ${styles.iconColor}`} weight="fill" />
            </div>
            <div className="flex-1">
              <h2 className="font-heading text-xl font-bold text-[var(--text)] mb-2">
                {title}
              </h2>
              <p className="text-sm text-gray-400 leading-relaxed">
                {message}
              </p>
            </div>
          </div>
          {!isLoading && (
            <button
              onClick={handleClose}
              className="text-gray-400 hover:text-white transition-colors p-1 ml-2"
            >
              <X className="w-5 h-5" />
            </button>
          )}
        </div>

        {/* Actions */}
        <div className="flex gap-3">
          <button
            onClick={handleClose}
            disabled={isLoading}
            className="flex-1 bg-white/5 border border-white/10 text-[var(--text)] py-3 rounded-xl font-semibold hover:bg-white/10 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {cancelText}
          </button>
          <button
            onClick={handleConfirm}
            disabled={isLoading}
            className={`flex-1 ${styles.confirmButton} disabled:cursor-not-allowed text-white py-3 rounded-xl font-semibold transition-all`}
          >
            {isLoading ? (
              <span className="flex items-center justify-center gap-2">
                <svg
                  className="w-4 h-4 animate-spin"
                  viewBox="0 0 24 24"
                  fill="none"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                Loading...
              </span>
            ) : (
              confirmText
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
