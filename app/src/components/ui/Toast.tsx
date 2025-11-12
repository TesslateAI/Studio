/**
 * Toast Notification Component
 */
import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { taskService } from '../../services/taskService';

interface ToastMessage {
  id: string;
  title: string;
  message: string;
  type: 'info' | 'success' | 'warning' | 'error';
  duration?: number;
}

interface ToastContextValue {
  showToast: (toast: Omit<ToastMessage, 'id'>) => void;
  hideToast: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within ToastProvider');
  }
  return context;
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const showToast = useCallback((toast: Omit<ToastMessage, 'id'>) => {
    const id = Math.random().toString(36).substr(2, 9);
    const newToast: ToastMessage = { ...toast, id };

    setToasts((prev) => [...prev, newToast]);

    // Auto-hide after duration (default 5 seconds)
    const duration = toast.duration ?? 5000;
    if (duration > 0) {
      setTimeout(() => {
        hideToast(id);
      }, duration);
    }
  }, []);

  const hideToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  }, []);

  // Subscribe to backend notifications
  useEffect(() => {
    const unsubscribe = taskService.subscribeToNotifications((notification) => {
      showToast({
        title: notification.title,
        message: notification.message,
        type: notification.type,
      });
    });

    return unsubscribe;
  }, [showToast]);

  return (
    <ToastContext.Provider value={{ showToast, hideToast }}>
      {children}
      <ToastContainer toasts={toasts} onClose={hideToast} />
    </ToastContext.Provider>
  );
}

function ToastContainer({
  toasts,
  onClose,
}: {
  toasts: ToastMessage[];
  onClose: (id: string) => void;
}) {
  if (toasts.length === 0) return null;

  return (
    <div className="fixed top-4 right-4 z-50 space-y-2" style={{ maxWidth: '400px' }}>
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} onClose={() => onClose(toast.id)} />
      ))}
    </div>
  );
}

function ToastItem({
  toast,
  onClose,
}: {
  toast: ToastMessage;
  onClose: () => void;
}) {
  const bgColors = {
    info: 'bg-blue-500',
    success: 'bg-green-500',
    warning: 'bg-yellow-500',
    error: 'bg-red-500',
  };

  const icons = {
    info: 'ℹ️',
    success: '✓',
    warning: '⚠️',
    error: '✕',
  };

  return (
    <div
      className={`${bgColors[toast.type]} text-white rounded-lg shadow-lg p-4 flex items-start gap-3 animate-slide-in`}
      style={{
        animation: 'slideIn 0.3s ease-out',
      }}
    >
      <div className="text-2xl">{icons[toast.type]}</div>
      <div className="flex-1">
        <div className="font-semibold">{toast.title}</div>
        <div className="text-sm opacity-90">{toast.message}</div>
      </div>
      <button
        onClick={onClose}
        className="text-white hover:text-gray-200 transition-colors"
        aria-label="Close"
      >
        ✕
      </button>
    </div>
  );
}

// Add slide-in animation via inline styles
const style = document.createElement('style');
style.textContent = `
  @keyframes slideIn {
    from {
      transform: translateX(100%);
      opacity: 0;
    }
    to {
      transform: translateX(0);
      opacity: 1;
    }
  }
`;
if (typeof document !== 'undefined') {
  document.head.appendChild(style);
}
