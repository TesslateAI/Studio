import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Check if an error is a canceled/aborted request.
 * Handles both native fetch AbortError and Axios CanceledError.
 */
export function isCanceledError(error: unknown): boolean {
  // Native fetch AbortError
  if (error instanceof Error && error.name === 'AbortError') {
    return true;
  }
  // Axios cancel error
  if (error && typeof error === 'object' && 'code' in error && error.code === 'ERR_CANCELED') {
    return true;
  }
  return false;
}
