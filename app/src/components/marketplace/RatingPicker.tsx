import React, { useState } from 'react';
import { Star } from '@phosphor-icons/react';
import { useTheme } from '../../theme/ThemeContext';

interface RatingPickerProps {
  value: number;
  onChange: (rating: number) => void;
  size?: 'sm' | 'md' | 'lg';
  disabled?: boolean;
}

export function RatingPicker({
  value,
  onChange,
  size = 'md',
  disabled = false
}: RatingPickerProps) {
  const { theme } = useTheme();
  const [hoverValue, setHoverValue] = useState(0);

  const sizes = {
    sm: 16,
    md: 24,
    lg: 32
  };

  const iconSize = sizes[size];
  const displayValue = hoverValue || value;

  return (
    <div
      className={`flex items-center gap-1 ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
      onMouseLeave={() => setHoverValue(0)}
    >
      {[1, 2, 3, 4, 5].map((star) => (
        <button
          key={star}
          type="button"
          disabled={disabled}
          onClick={() => !disabled && onChange(star)}
          onMouseEnter={() => !disabled && setHoverValue(star)}
          className={`
            p-1 rounded transition-all
            ${!disabled ? 'hover:scale-110' : ''}
            ${star <= displayValue
              ? 'text-yellow-400'
              : theme === 'light'
                ? 'text-black/20 hover:text-black/40'
                : 'text-white/20 hover:text-white/40'
            }
          `}
        >
          <Star
            size={iconSize}
            weight={star <= displayValue ? 'fill' : 'regular'}
          />
        </button>
      ))}
    </div>
  );
}

export default RatingPicker;
