/**
 * Shared helpers for connector UI error handling.
 */

interface AxiosLikeError {
  response?: { data?: { detail?: string } };
  message?: string;
}

export function apiErrorMessage(err: unknown, fallback: string): string {
  if (err && typeof err === 'object') {
    const e = err as AxiosLikeError;
    const detail = e.response?.data?.detail;
    if (typeof detail === 'string' && detail.length > 0) return detail;
    if (typeof e.message === 'string' && e.message.length > 0) return e.message;
  }
  if (err instanceof Error) return err.message;
  return fallback;
}
