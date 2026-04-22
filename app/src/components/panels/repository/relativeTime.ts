/**
 * Human-readable "time ago" formatter.
 *
 * date-fns isn't a dependency and the feature-spec bans pulling in extra
 * libraries for something this small. The output matches the conventions of
 * GitHub's own UI:
 *   "just now" | "2 minutes ago" | "4 hours ago" | "yesterday" |
 *   "3 days ago" | "2 weeks ago" | "Apr 12, 2024"
 *
 * Past-only. We don't model future timestamps because commits/events always
 * live in the past, and mixing tenses in the UI adds noise.
 */
export function formatRelativeTime(
  isoOrNull: string | null | undefined,
  now: Date = new Date()
): string {
  if (!isoOrNull) return '';
  const then = new Date(isoOrNull);
  if (Number.isNaN(then.getTime())) return '';

  const diffMs = now.getTime() - then.getTime();
  // Clamp tiny negative drifts (clock skew between server/client) to "just now".
  if (diffMs < 0 && diffMs > -60_000) return 'just now';
  if (diffMs < 0) {
    // Real future timestamp — fall back to an absolute format.
    return formatAbsoluteDate(then);
  }

  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 45) return 'just now';

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return `${minutes} ${minutes === 1 ? 'minute' : 'minutes'} ago`;
  }

  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `${hours} ${hours === 1 ? 'hour' : 'hours'} ago`;
  }

  const days = Math.floor(hours / 24);
  if (days === 1) return 'yesterday';
  if (days < 7) return `${days} days ago`;

  const weeks = Math.floor(days / 7);
  if (weeks < 5) return `${weeks} ${weeks === 1 ? 'week' : 'weeks'} ago`;

  const months = Math.floor(days / 30);
  if (months < 12) return `${months} ${months === 1 ? 'month' : 'months'} ago`;

  // Anything older than ~a year shows the absolute date — "14 months ago"
  // loses meaning and people want to see the year.
  return formatAbsoluteDate(then);
}

/** Absolute format used as fallback and for tooltip content. */
export function formatAbsoluteDate(date: Date | string | null | undefined): string {
  if (!date) return '';
  const d = typeof date === 'string' ? new Date(date) : date;
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}
