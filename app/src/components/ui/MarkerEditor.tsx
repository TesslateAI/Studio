import { useState, useRef, useCallback, useMemo, KeyboardEvent, forwardRef, useImperativeHandle } from 'react';
import { MarkerPill } from './MarkerPill';
import { AVAILABLE_MARKERS } from './MarkerPalette';
import type { Marker } from './MarkerPalette';

interface MarkerEditorProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
  className?: string;
  disabled?: boolean;
}

export interface MarkerEditorHandle {
  insertMarker: (markerKey: string) => void;
  focus: () => void;
}

// Regex to match {marker} patterns - only alphanumeric and underscore allowed
const MARKER_REGEX = /\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g;

// Build a map of valid markers for quick lookup
const MARKER_MAP: Record<string, Marker> = AVAILABLE_MARKERS.reduce((acc, m) => {
  acc[m.key] = m;
  return acc;
}, {} as Record<string, Marker>);

interface TextSegment {
  type: 'text' | 'marker';
  content: string;
  marker?: Marker;
}

/**
 * Safely parse text into segments of plain text and markers.
 * This function is XSS-safe because:
 * 1. We use a strict regex that only matches valid marker patterns
 * 2. We never interpret user input as HTML or code
 * 3. All output is rendered as React elements, not innerHTML
 */
function parseTextToSegments(text: string): TextSegment[] {
  const segments: TextSegment[] = [];
  let lastIndex = 0;
  let match;

  // Reset regex state
  MARKER_REGEX.lastIndex = 0;

  while ((match = MARKER_REGEX.exec(text)) !== null) {
    const markerKey = match[1];
    const marker = MARKER_MAP[markerKey];

    // Add text before marker
    if (match.index > lastIndex) {
      segments.push({
        type: 'text',
        content: text.slice(lastIndex, match.index),
      });
    }

    // Add marker (if valid) or treat as plain text
    if (marker) {
      segments.push({
        type: 'marker',
        content: match[0],
        marker,
      });
    } else {
      // Unknown marker - treat as plain text
      segments.push({
        type: 'text',
        content: match[0],
      });
    }

    lastIndex = match.index + match[0].length;
  }

  // Add remaining text
  if (lastIndex < text.length) {
    segments.push({
      type: 'text',
      content: text.slice(lastIndex),
    });
  }

  return segments;
}

export const MarkerEditor = forwardRef<MarkerEditorHandle, MarkerEditorProps>(function MarkerEditor({
  value,
  onChange,
  placeholder = 'Enter text...',
  rows = 12,
  className = '',
  disabled = false,
}, ref) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const [isFocused, setIsFocused] = useState(false);

  // Expose imperative methods
  useImperativeHandle(ref, () => ({
    insertMarker: (markerKey: string) => {
      const textarea = textareaRef.current;
      if (!textarea) return;

      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;

      const newValue =
        value.slice(0, start) +
        `{${markerKey}}` +
        value.slice(end);

      onChange(newValue);

      // Move cursor after inserted marker
      setTimeout(() => {
        textarea.focus();
        const newPos = start + markerKey.length + 2;
        textarea.setSelectionRange(newPos, newPos);
      }, 0);
    },
    focus: () => {
      textareaRef.current?.focus();
    },
  }), [value, onChange]);

  // Parse the value into segments
  const segments = useMemo(() => parseTextToSegments(value), [value]);

  // Sync scroll between textarea and overlay
  const handleScroll = useCallback(() => {
    if (textareaRef.current && overlayRef.current) {
      overlayRef.current.scrollTop = textareaRef.current.scrollTop;
      overlayRef.current.scrollLeft = textareaRef.current.scrollLeft;
    }
  }, []);

  // Handle text input
  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      onChange(e.target.value);
    },
    [onChange]
  );

  // Remove a marker at cursor position (backspace behavior)
  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      const textarea = textareaRef.current;
      if (!textarea) return;

      const { selectionStart, selectionEnd } = textarea;

      // Handle backspace on marker
      if (e.key === 'Backspace' && selectionStart === selectionEnd) {
        // Check if cursor is right after a marker
        const beforeCursor = value.slice(0, selectionStart);
        const markerMatch = beforeCursor.match(/\{([a-zA-Z_][a-zA-Z0-9_]*)\}$/);

        if (markerMatch && MARKER_MAP[markerMatch[1]]) {
          e.preventDefault();
          const newValue =
            value.slice(0, selectionStart - markerMatch[0].length) +
            value.slice(selectionEnd);
          onChange(newValue);

          // Update cursor position
          setTimeout(() => {
            const newPos = selectionStart - markerMatch[0].length;
            textarea.setSelectionRange(newPos, newPos);
          }, 0);
        }
      }

      // Handle delete on marker
      if (e.key === 'Delete' && selectionStart === selectionEnd) {
        const afterCursor = value.slice(selectionStart);
        const markerMatch = afterCursor.match(/^\{([a-zA-Z_][a-zA-Z0-9_]*)\}/);

        if (markerMatch && MARKER_MAP[markerMatch[1]]) {
          e.preventDefault();
          const newValue =
            value.slice(0, selectionStart) +
            value.slice(selectionStart + markerMatch[0].length);
          onChange(newValue);
        }
      }
    },
    [value, onChange]
  );

  // Render segments with proper styling
  const renderSegments = useMemo(() => {
    if (segments.length === 0 && !value) {
      return (
        <span className="text-[var(--text)]/40">{placeholder}</span>
      );
    }

    return segments.map((segment, index) => {
      if (segment.type === 'marker' && segment.marker) {
        return (
          <MarkerPill
            key={`${segment.marker.key}-${index}`}
            marker={segment.marker.key}
            label={segment.marker.label}
            category={segment.marker.category}
            description={segment.marker.description}
            inline
          />
        );
      }
      // For text segments, preserve whitespace and newlines
      // Use a span with pre-wrap to maintain formatting
      return (
        <span key={index} className="whitespace-pre-wrap">
          {segment.content}
        </span>
      );
    });
  }, [segments, value, placeholder]);

  // Calculate min-height based on rows
  const minHeight = `${rows * 1.5}rem`;

  return (
    <div className={`relative ${className}`}>
      {/* Hidden textarea for input - handles all text editing */}
      <textarea
        ref={textareaRef}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onScroll={handleScroll}
        onFocus={() => setIsFocused(true)}
        onBlur={() => setIsFocused(false)}
        disabled={disabled}
        rows={rows}
        className={`
          w-full px-4 py-3 rounded-lg border resize-y
          font-mono text-sm leading-relaxed
          bg-white/5 text-transparent caret-[var(--text)]
          focus:outline-none transition-colors
          ${isFocused ? 'border-orange-500/50' : 'border-[var(--text)]/15'}
          ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
        `}
        style={{ minHeight }}
        aria-label="System prompt editor with marker support"
      />

      {/* Visual overlay - shows the rendered text with pills */}
      <div
        ref={overlayRef}
        className={`
          absolute inset-0 px-4 py-3 rounded-lg
          font-mono text-sm leading-relaxed
          text-[var(--text)] pointer-events-none
          overflow-hidden whitespace-pre-wrap break-words
        `}
        style={{ minHeight }}
        aria-hidden="true"
      >
        {renderSegments}
      </div>
    </div>
  );
});

// Export a function to insert a marker at cursor position
export function insertMarkerAtCursor(
  textareaRef: React.RefObject<HTMLTextAreaElement>,
  currentValue: string,
  markerKey: string,
  onChange: (value: string) => void
): void {
  const textarea = textareaRef.current;
  if (!textarea) return;

  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;

  const newValue =
    currentValue.slice(0, start) +
    `{${markerKey}}` +
    currentValue.slice(end);

  onChange(newValue);

  // Move cursor after inserted marker
  setTimeout(() => {
    textarea.focus();
    const newPos = start + markerKey.length + 2;
    textarea.setSelectionRange(newPos, newPos);
  }, 0);
}
