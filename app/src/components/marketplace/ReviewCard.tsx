import React from 'react';
import { Star, Trash, Pencil } from '@phosphor-icons/react';
import { useTheme } from '../../theme/ThemeContext';

export interface Review {
  id: string;
  rating: number;
  comment?: string;
  created_at: string;
  user_id: string;
  user_name: string;
  user_avatar_url?: string;
  is_own_review: boolean;
}

interface ReviewCardProps {
  review: Review;
  onEdit?: () => void;
  onDelete?: () => void;
}

export function ReviewCard({ review, onEdit, onDelete }: ReviewCardProps) {
  const { theme } = useTheme();

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  return (
    <div
      className={`
      p-4 rounded-xl border
      ${theme === 'light' ? 'bg-white border-black/10' : 'bg-white/5 border-white/10'}
    `}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-3">
        {/* User Info */}
        <div className="flex items-center gap-3">
          <div
            className={`
            w-10 h-10 rounded-full overflow-hidden flex-shrink-0
            ${theme === 'light' ? 'bg-black/10' : 'bg-white/10'}
          `}
          >
            {review.user_avatar_url ? (
              <img
                src={review.user_avatar_url}
                alt={review.user_name}
                className="w-full h-full object-cover"
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-sm font-medium">
                {review.user_name?.charAt(0).toUpperCase() || '?'}
              </div>
            )}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span
                className={`font-semibold text-sm truncate ${theme === 'light' ? 'text-black' : 'text-white'}`}
              >
                {review.user_name}
              </span>
              {review.is_own_review && (
                <span className="px-1.5 py-0.5 bg-[var(--primary)]/20 text-[var(--primary)] text-[10px] rounded font-medium">
                  You
                </span>
              )}
            </div>
            <div className={`text-xs ${theme === 'light' ? 'text-black/50' : 'text-white/50'}`}>
              {formatDate(review.created_at)}
            </div>
          </div>
        </div>

        {/* Actions for own review */}
        {review.is_own_review && (
          <div className="flex items-center gap-1">
            {onEdit && (
              <button
                onClick={onEdit}
                className={`p-2 rounded-lg transition-colors ${
                  theme === 'light'
                    ? 'hover:bg-black/5 text-black/50 hover:text-black'
                    : 'hover:bg-white/5 text-white/50 hover:text-white'
                }`}
                title="Edit review"
              >
                <Pencil size={16} />
              </button>
            )}
            {onDelete && (
              <button
                onClick={onDelete}
                className={`p-2 rounded-lg transition-colors ${
                  theme === 'light'
                    ? 'hover:bg-red-50 text-black/50 hover:text-red-500'
                    : 'hover:bg-red-500/10 text-white/50 hover:text-red-400'
                }`}
                title="Delete review"
              >
                <Trash size={16} />
              </button>
            )}
          </div>
        )}
      </div>

      {/* Rating */}
      <div className="flex items-center gap-1 mb-2">
        {[1, 2, 3, 4, 5].map((star) => (
          <Star
            key={star}
            size={16}
            weight={star <= review.rating ? 'fill' : 'regular'}
            className={
              star <= review.rating
                ? 'text-yellow-400'
                : theme === 'light'
                  ? 'text-black/20'
                  : 'text-white/20'
            }
          />
        ))}
      </div>

      {/* Comment */}
      {review.comment && (
        <p
          className={`text-sm leading-relaxed ${theme === 'light' ? 'text-black/70' : 'text-white/70'}`}
        >
          {review.comment}
        </p>
      )}
    </div>
  );
}

export default ReviewCard;
