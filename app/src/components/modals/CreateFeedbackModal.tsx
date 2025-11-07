import { useState } from 'react';
import { X, Bug, Lightbulb } from '@phosphor-icons/react';
import { feedbackApi } from '../../lib/api';
import { PulsingGridSpinner } from '../PulsingGridSpinner';
import toast from 'react-hot-toast';

interface CreateFeedbackModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export function CreateFeedbackModal({ isOpen, onClose, onSuccess }: CreateFeedbackModalProps) {
  const [type, setType] = useState<'bug' | 'suggestion'>('suggestion');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!title.trim() || !description.trim()) {
      toast.error('Please fill in all fields');
      return;
    }

    setIsSubmitting(true);

    try {
      await feedbackApi.create({
        type,
        title: title.trim(),
        description: description.trim(),
      });

      toast.success(`${type === 'bug' ? 'Bug' : 'Suggestion'} submitted successfully!`);
      setTitle('');
      setDescription('');
      setType('suggestion');
      onSuccess();
      onClose();
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      const errorMessage = typeof detail === 'string' ? detail : 'Failed to submit feedback';
      toast.error(errorMessage);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    if (!isSubmitting) {
      setTitle('');
      setDescription('');
      setType('suggestion');
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50"
      onClick={handleClose}
    >
      <div
        className="bg-[var(--surface)] p-8 rounded-3xl w-full max-w-2xl shadow-2xl border border-white/10 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h2 className="font-heading text-2xl font-bold text-[var(--text)]">Submit Feedback</h2>
          {!isSubmitting && (
            <button
              onClick={handleClose}
              className="text-gray-400 hover:text-white transition-colors p-2"
            >
              <X className="w-5 h-5" />
            </button>
          )}
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Type Selection */}
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-3">Feedback Type</label>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setType('bug')}
                disabled={isSubmitting}
                className={`
                  p-4 rounded-xl border-2 transition-all
                  ${type === 'bug'
                    ? 'border-red-500 bg-red-500/10'
                    : 'border-white/10 bg-white/5 hover:border-white/20'
                  }
                  ${isSubmitting ? 'opacity-50 cursor-not-allowed' : ''}
                `}
              >
                <Bug className="w-6 h-6 text-red-400 mx-auto mb-2" weight="fill" />
                <div className="text-sm font-semibold text-[var(--text)]">Bug Report</div>
                <div className="text-xs text-[var(--text)]/60 mt-1">Something isn't working</div>
              </button>

              <button
                type="button"
                onClick={() => setType('suggestion')}
                disabled={isSubmitting}
                className={`
                  p-4 rounded-xl border-2 transition-all
                  ${type === 'suggestion'
                    ? 'border-teal-500 bg-teal-500/10'
                    : 'border-white/10 bg-white/5 hover:border-white/20'
                  }
                  ${isSubmitting ? 'opacity-50 cursor-not-allowed' : ''}
                `}
              >
                <Lightbulb className="w-6 h-6 text-teal-400 mx-auto mb-2" weight="fill" />
                <div className="text-sm font-semibold text-[var(--text)]">Suggestion</div>
                <div className="text-xs text-[var(--text)]/60 mt-1">Idea for improvement</div>
              </button>
            </div>
          </div>

          {/* Title */}
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">Title</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-white/5 border border-white/10 text-[var(--text)] px-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:border-transparent transition-all placeholder:text-[var(--text)]/40 text-sm"
              placeholder="Brief description of the issue or idea"
              maxLength={500}
              required
              disabled={isSubmitting}
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full bg-white/5 border border-white/10 text-[var(--text)] px-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:border-transparent resize-none transition-all placeholder:text-[var(--text)]/40 text-sm"
              rows={6}
              placeholder={type === 'bug' ? 'Describe what happened and how to reproduce it...' : 'Describe your idea and how it would improve the platform...'}
              required
              disabled={isSubmitting}
            />
          </div>

          {/* Actions */}
          <div className="flex gap-3 pt-4">
            <button
              type="submit"
              disabled={isSubmitting || !title.trim() || !description.trim()}
              className="flex-1 bg-[var(--primary)] hover:bg-orange-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-white py-3 rounded-xl font-semibold transition-all"
            >
              {isSubmitting ? (
                <div className="flex items-center justify-center gap-2">
                  <PulsingGridSpinner size={18} />
                  <span>Submitting...</span>
                </div>
              ) : (
                `Submit ${type === 'bug' ? 'Bug Report' : 'Suggestion'}`
              )}
            </button>
            <button
              type="button"
              onClick={handleClose}
              disabled={isSubmitting}
              className="flex-1 bg-white/5 border border-white/10 text-[var(--text)] py-3 rounded-xl font-semibold hover:bg-white/10 transition-all disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
