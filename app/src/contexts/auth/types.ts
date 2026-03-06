/**
 * Authentication types and error handling
 * Provides typed errors for observable, debuggable auth flows
 */

import axios from 'axios';

// =============================================================================
// Auth Error Types
// =============================================================================

export type AuthErrorCode =
  | 'NETWORK_ERROR'
  | 'INVALID_CREDENTIALS'
  | 'SESSION_EXPIRED'
  | 'TOKEN_INVALID'
  | 'UNAUTHORIZED'
  | 'FORBIDDEN'
  | 'SERVER_ERROR'
  | 'UNKNOWN';

export interface AuthError {
  code: AuthErrorCode;
  message: string;
  timestamp: number;
  recoverable: boolean;
  statusCode?: number;
}

/**
 * Custom error class for authentication errors
 * Provides consistent error classification from various sources
 */
export class AuthenticationError extends Error {
  constructor(
    public code: AuthErrorCode,
    message: string,
    public recoverable: boolean = true,
    public statusCode?: number
  ) {
    super(message);
    this.name = 'AuthenticationError';
  }

  /**
   * Convert to plain AuthError object for state storage
   */
  toAuthError(): AuthError {
    return {
      code: this.code,
      message: this.message,
      timestamp: Date.now(),
      recoverable: this.recoverable,
      statusCode: this.statusCode,
    };
  }

  /**
   * Create AuthenticationError from axios error with proper classification
   */
  static fromAxiosError(error: unknown): AuthenticationError {
    // Handle non-axios errors
    if (!axios.isAxiosError(error)) {
      return new AuthenticationError('UNKNOWN', 'An unexpected error occurred');
    }

    // Network errors (no response)
    if (!error.response) {
      return new AuthenticationError(
        'NETWORK_ERROR',
        'Network connection failed. Please check your internet connection.',
        true // recoverable
      );
    }

    const { status, data } = error.response;
    const detail = data?.detail;

    // Classify by HTTP status code
    switch (status) {
      case 400:
        if (detail === 'LOGIN_BAD_CREDENTIALS') {
          return new AuthenticationError(
            'INVALID_CREDENTIALS',
            'Invalid email or password',
            false,
            400
          );
        }
        if (detail === 'LOGIN_USER_NOT_VERIFIED') {
          return new AuthenticationError(
            'UNAUTHORIZED',
            'Please verify your email address',
            false,
            400
          );
        }
        return new AuthenticationError('UNKNOWN', detail || 'Invalid request', false, 400);

      case 401:
        // Check if token expired vs invalid
        if (detail?.includes('expired') || detail?.includes('Token')) {
          return new AuthenticationError(
            'SESSION_EXPIRED',
            'Your session has expired. Please log in again.',
            false,
            401
          );
        }
        return new AuthenticationError('UNAUTHORIZED', 'Not authenticated', false, 401);

      case 403:
        return new AuthenticationError('FORBIDDEN', 'Access denied', false, 403);

      case 500:
      case 502:
      case 503:
      case 504:
        return new AuthenticationError(
          'SERVER_ERROR',
          'Server error occurred. Please try again later.',
          true, // recoverable - server may recover
          status
        );

      default:
        return new AuthenticationError(
          'UNKNOWN',
          error.message || 'An unexpected error occurred',
          true,
          status
        );
    }
  }
}

// =============================================================================
// User Types
// =============================================================================

export interface AuthUser {
  id: string;
  email: string;
  name?: string;
  username?: string;
  avatar_url?: string;
  subscription_tier?: string;
  bundled_credits?: number;
  purchased_credits?: number;
  is_superuser?: boolean;
  slug?: string;
}

// =============================================================================
// Auth State Types
// =============================================================================

export type AuthStatus = 'initializing' | 'authenticated' | 'unauthenticated';
export type AuthMethod = 'token' | 'cookie' | null;

export interface AuthState {
  status: AuthStatus;
  user: AuthUser | null;
  authMethod: AuthMethod;
  error: AuthError | null;
  lastChecked: number | null;
}

// =============================================================================
// Auth Context Types
// =============================================================================

export interface AuthContextValue extends AuthState {
  // Computed helpers
  isAuthenticated: boolean;
  isLoading: boolean;

  // Actions
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  checkAuth: (options?: { force?: boolean }) => Promise<boolean>;
  refreshUser: () => Promise<void>;
  refreshToken: () => Promise<void>;
  clearError: () => void;

  // Role checking
  hasRole: (role: string) => boolean;
}

// =============================================================================
// Utility Functions
// =============================================================================

/**
 * Check if an error should trigger a logout
 */
export function shouldLogoutOnError(error: AuthError): boolean {
  return error.code === 'UNAUTHORIZED' || error.code === 'SESSION_EXPIRED';
}

/**
 * Check if an error should be displayed to the user
 */
export function isUserFacingError(error: AuthError): boolean {
  // Network errors are recoverable and shouldn't alarm users
  if (error.code === 'NETWORK_ERROR') {
    return !navigator.onLine;
  }
  return true;
}

/**
 * Get a user-friendly error message
 */
export function getErrorMessage(error: AuthError): string {
  switch (error.code) {
    case 'NETWORK_ERROR':
      return 'Unable to connect. Please check your internet connection.';
    case 'INVALID_CREDENTIALS':
      return 'Invalid email or password.';
    case 'SESSION_EXPIRED':
      return 'Your session has expired. Please log in again.';
    case 'UNAUTHORIZED':
      return 'Please log in to continue.';
    case 'FORBIDDEN':
      return 'You do not have permission to access this resource.';
    case 'SERVER_ERROR':
      return 'Something went wrong. Please try again later.';
    default:
      return error.message || 'An unexpected error occurred.';
  }
}
