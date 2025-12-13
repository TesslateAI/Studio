import { useState, useEffect } from 'react';
import { X, Bug, Lightbulb, Heart, PaperPlaneRight } from '@phosphor-icons/react';
import { feedbackApi } from '../../lib/api';
import { PulsingGridSpinner } from '../PulsingGridSpinner';
import toast from 'react-hot-toast';

interface FeedbackModalProps {
  isOpen: boolean;
  feedbackId: string | null;
  onClose: () => void;
  onUpdate: () => void;
}

interface FeedbackDetail {
  id: string;
  user_id: string;
  user_name: string;
  type: string;
  title: string;
  description: string;
  status: string;
  upvote_count: number;
  has_upvoted: boolean;
  created_at: string;
  updated_at: string;
  comments: Comment[];
}

interface Comment {
  id: string;
  user_id: string;
  user_name: string;
  feedback_id: string;
  content: string;
  created_at: string;
  updated_at: string;
}

export function FeedbackModal({ isOpen, feedbackId, onClose, onUpdate }: FeedbackModalProps) {
  const [feedback, setFeedback] = useState<FeedbackDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [newComment, setNewComment] = useState('');
  const [submittingComment, setSubmittingComment] = useState(false);

  useEffect(() => {
    if (isOpen && feedbackId) {
      loadFeedback();
    }
  }, [isOpen, feedbackId]);

  const loadFeedback = async () => {
    if (!feedbackId) return;

    setLoading(true);
    try {
      const data = await feedbackApi.get(feedbackId);
      setFeedback(data);
    } catch (error) {
      toast.error('Failed to load feedback details');
      onClose();
    } finally {
      setLoading(false);
    }
  };

  const handleUpvote = async () => {
    if (!feedback) return;

    try {
      const result = await feedbackApi.toggleUpvote(feedback.id);
      setFeedback({
        ...feedback,
        has_upvoted: result.upvoted,
        upvote_count: result.upvote_count,
      });
      onUpdate();
    } catch (error) {
      toast.error('Failed to update upvote');
    }
  };

  const handleSubmitComment = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!feedback || !newComment.trim()) return;

    setSubmittingComment(true);
    try {
      const comment = await feedbackApi.addComment(feedback.id, newComment.trim());
      setFeedback({
        ...feedback,
        comments: [...feedback.comments, comment],
      });
      setNewComment('');
      toast.success('Comment added!');
      onUpdate();
    } catch (error) {
      toast.error('Failed to add comment');
    } finally {
      setSubmittingComment(false);
    }
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
    if (diffMins < 10080) return `${Math.floor(diffMins / 1440)}d ago`;

    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50"
      onClick={onClose}
    >
      <div
        className="bg-[var(--surface)] rounded-3xl w-full max-w-3xl shadow-2xl border border-white/10 max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {loading ? (
          <div className="flex items-center justify-center p-16">
            <PulsingGridSpinner size={60} />
          </div>
        ) : feedback ? (
          <>
            {/* Header */}
            <div className="p-6 border-b border-white/10">
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  <span
                    className={`
                      inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
                      ${feedback.type === 'bug'
                        ? 'bg-red-500/10 text-red-400 border border-red-500/20'
                        : 'bg-teal-500/10 text-teal-400 border border-teal-500/20'
                      }
                    `}
                  >
                    {feedback.type === 'bug' ? (
                      <><Bug size={14} weight="fill" /> Bug</>
                    ) : (
                      <><Lightbulb size={14} weight="fill" /> Suggestion</>
                    )}
                  </span>

                  {feedback.status !== 'open' && (
                    <span className="px-3 py-1 bg-white/10 text-[var(--text)]/60 text-xs rounded-lg font-medium">
                      {feedback.status}
                    </span>
                  )}
                </div>

                <button
                  onClick={onClose}
                  className="text-gray-400 hover:text-white transition-colors p-2"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <h2 className="font-heading text-2xl font-bold text-[var(--text)] mb-2">
                {feedback.title}
              </h2>

              <div className="flex items-center gap-4 text-sm text-[var(--text)]/60">
                <span>Posted by {feedback.user_name}</span>
                <span>•</span>
                <span>{formatDate(feedback.created_at)}</span>
              </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto">
              {/* Description */}
              <div className="p-6 border-b border-white/10">
                <p className="text-[var(--text)]/80 whitespace-pre-wrap leading-relaxed">
                  {feedback.description}
                </p>

                {/* Upvote Button */}
                <button
                  onClick={handleUpvote}
                  className={`
                    mt-4 inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all
                    ${feedback.has_upvoted
                      ? 'bg-[var(--primary)]/20 text-[var(--primary)]'
                      : 'bg-white/5 text-[var(--text)]/60 hover:bg-white/10 hover:text-[var(--text)]'
                    }
                  `}
                >
                  <Heart size={18} weight={feedback.has_upvoted ? 'fill' : 'regular'} />
                  {feedback.upvote_count} {feedback.upvote_count === 1 ? 'Upvote' : 'Upvotes'}
                </button>
              </div>

              {/* Comments Section */}
              <div className="p-6">
                <h3 className="font-heading text-lg font-bold text-[var(--text)] mb-4">
                  Comments ({feedback.comments.length})
                </h3>

                {/* Comments List */}
                <div className="space-y-4 mb-6">
                  {feedback.comments.map((comment) => (
                    <div
                      key={comment.id}
                      className="bg-white/5 border border-white/10 rounded-xl p-4"
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-sm font-semibold text-[var(--text)]">
                          {comment.user_name}
                        </span>
                        <span className="text-xs text-[var(--text)]/40">
                          {formatDate(comment.created_at)}
                        </span>
                      </div>
                      <p className="text-sm text-[var(--text)]/80 whitespace-pre-wrap leading-relaxed">
                        {comment.content}
                      </p>
                    </div>
                  ))}

                  {feedback.comments.length === 0 && (
                    <p className="text-center text-[var(--text)]/40 text-sm py-8">
                      No comments yet. Be the first to comment!
                    </p>
                  )}
                </div>

                {/* Add Comment Form */}
                <form onSubmit={handleSubmitComment} className="space-y-3">
                  <textarea
                    value={newComment}
                    onChange={(e) => setNewComment(e.target.value)}
                    className="w-full bg-white/5 border border-white/10 text-[var(--text)] px-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:border-transparent resize-none transition-all placeholder:text-[var(--text)]/40 text-sm"
                    rows={3}
                    placeholder="Add a comment..."
                    disabled={submittingComment}
                  />

                  <button
                    type="submit"
                    disabled={submittingComment || !newComment.trim()}
                    className="w-full flex items-center justify-center gap-2 bg-[var(--primary)] hover:bg-[var(--primary-hover)] disabled:bg-gray-600 disabled:cursor-not-allowed text-white py-2.5 rounded-xl font-semibold transition-all text-sm"
                  >
                    {submittingComment ? (
                      <>
                        <PulsingGridSpinner size={16} />
                        <span>Posting...</span>
                      </>
                    ) : (
                      <>
                        <PaperPlaneRight size={16} weight="fill" />
                        <span>Post Comment</span>
                      </>
                    )}
                  </button>
                </form>
              </div>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
