import { useState } from 'react';
import { X, Eye, EyeSlash, Link, ArrowSquareOut } from '@phosphor-icons/react';
import { motion, AnimatePresence } from 'framer-motion';

interface CredentialField {
  key: string;
  label: string;
  type: string;
  required: boolean;
  placeholder: string;
  help_text: string;
}

interface ExternalServiceItem {
  id: string;
  name: string;
  slug: string;
  icon: string;
  service_type: 'external' | 'hybrid';
  credential_fields: CredentialField[];
  auth_type?: string;
  docs_url?: string;
  connection_template?: Record<string, string>;
}

interface ExternalServiceCredentialModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (credentials: Record<string, string>, externalEndpoint?: string) => void;
  item: ExternalServiceItem;
}

export const ExternalServiceCredentialModal = ({
  isOpen,
  onClose,
  onSubmit,
  item,
}: ExternalServiceCredentialModalProps) => {
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [externalEndpoint, setExternalEndpoint] = useState('');
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    // Validate required fields
    const newErrors: Record<string, string> = {};
    item.credential_fields?.forEach(field => {
      if (field.required && !credentials[field.key]?.trim()) {
        newErrors[field.key] = `${field.label} is required`;
      }
    });

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }

    setIsSubmitting(true);
    onSubmit(credentials, externalEndpoint || undefined);
  };

  const toggleShowSecret = (key: string) => {
    setShowSecrets(prev => ({ ...prev, [key]: !prev[key] }));
  };

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="absolute inset-0 bg-black/60 backdrop-blur-sm"
          onClick={onClose}
        />

        {/* Modal */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 20 }}
          className="relative w-full max-w-md bg-[var(--surface)] rounded-xl shadow-2xl border border-[var(--border-color)] overflow-hidden"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-color)]">
            <div className="flex items-center gap-3">
              <span className="text-2xl">{item.icon}</span>
              <div>
                <h2 className="text-lg font-semibold text-[var(--text)]">
                  Connect {item.name}
                </h2>
                <p className="text-xs text-[var(--text)]/60">
                  {item.service_type === 'hybrid' ? 'External service (no container)' : 'Cloud integration'}
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-2 rounded-lg hover:bg-[var(--sidebar-hover)] text-[var(--text)]/60 hover:text-[var(--text)] transition-colors"
            >
              <X size={20} />
            </button>
          </div>

          {/* Content */}
          <form onSubmit={handleSubmit} className="p-6 space-y-4">
            {/* Docs link */}
            {item.docs_url && (
              <a
                href={item.docs_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 text-sm text-[var(--primary)] hover:underline"
              >
                <ArrowSquareOut size={16} />
                View {item.name} documentation
              </a>
            )}

            {/* External Endpoint (optional) */}
            <div className="space-y-1.5">
              <label className="flex items-center gap-2 text-sm font-medium text-[var(--text)]">
                <Link size={16} />
                Service URL
                <span className="text-[var(--text)]/40 font-normal">(optional)</span>
              </label>
              <input
                type="url"
                value={externalEndpoint}
                onChange={(e) => setExternalEndpoint(e.target.value)}
                placeholder={`https://your-project.${item.slug}.co`}
                className="w-full px-3 py-2 bg-[var(--bg)] border border-[var(--border-color)] rounded-lg text-[var(--text)] text-sm placeholder:text-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:border-transparent"
              />
              <p className="text-xs text-[var(--text)]/50">
                The base URL for your {item.name} instance
              </p>
            </div>

            {/* Credential Fields */}
            {item.credential_fields?.map((field) => (
              <div key={field.key} className="space-y-1.5">
                <label className="flex items-center justify-between text-sm font-medium text-[var(--text)]">
                  <span>
                    {field.label}
                    {field.required && <span className="text-red-400 ml-1">*</span>}
                  </span>
                </label>
                <div className="relative">
                  <input
                    type={field.type === 'password' && !showSecrets[field.key] ? 'password' : 'text'}
                    value={credentials[field.key] || ''}
                    onChange={(e) => {
                      setCredentials(prev => ({ ...prev, [field.key]: e.target.value }));
                      setErrors(prev => ({ ...prev, [field.key]: '' }));
                    }}
                    placeholder={field.placeholder}
                    className={`w-full px-3 py-2 bg-[var(--bg)] border rounded-lg text-[var(--text)] text-sm placeholder:text-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:border-transparent pr-10 ${
                      errors[field.key] ? 'border-red-400' : 'border-[var(--border-color)]'
                    }`}
                  />
                  {field.type === 'password' && (
                    <button
                      type="button"
                      onClick={() => toggleShowSecret(field.key)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text)]/40 hover:text-[var(--text)] transition-colors"
                    >
                      {showSecrets[field.key] ? <EyeSlash size={18} /> : <Eye size={18} />}
                    </button>
                  )}
                </div>
                {field.help_text && (
                  <p className="text-xs text-[var(--text)]/50">{field.help_text}</p>
                )}
                {errors[field.key] && (
                  <p className="text-xs text-red-400">{errors[field.key]}</p>
                )}
              </div>
            ))}

            {/* Info box */}
            <div className="p-3 bg-[var(--primary)]/10 rounded-lg border border-[var(--primary)]/20">
              <p className="text-xs text-[var(--text)]/80">
                Your credentials are encrypted and stored securely. They will be used to inject environment variables into connected containers.
              </p>
            </div>

            {/* Actions */}
            <div className="flex gap-3 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="flex-1 px-4 py-2.5 border border-[var(--border-color)] rounded-lg text-[var(--text)] text-sm font-medium hover:bg-[var(--sidebar-hover)] transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isSubmitting}
                className="flex-1 px-4 py-2.5 bg-[var(--primary)] text-white rounded-lg text-sm font-medium hover:bg-[var(--primary-hover)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isSubmitting ? 'Connecting...' : 'Connect Service'}
              </button>
            </div>
          </form>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};
