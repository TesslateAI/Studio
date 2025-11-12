import * as SecureStore from 'expo-secure-store';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Platform } from 'react-native';

// Keys for storage
const TOKEN_KEY = 'token';
const USER_KEY = 'user';
const REFERRAL_KEY = 'referral_code';

// SecureStore is not available on web, so we use AsyncStorage as fallback
const isWeb = Platform.OS === 'web';

export const authManager = {
  // Token management (SecureStore for native, AsyncStorage for web)
  saveToken: async (token: string): Promise<void> => {
    if (isWeb) {
      await AsyncStorage.setItem(TOKEN_KEY, token);
    } else {
      await SecureStore.setItemAsync(TOKEN_KEY, token);
    }
  },

  getToken: async (): Promise<string | null> => {
    if (isWeb) {
      return await AsyncStorage.getItem(TOKEN_KEY);
    } else {
      return await SecureStore.getItemAsync(TOKEN_KEY);
    }
  },

  deleteToken: async (): Promise<void> => {
    if (isWeb) {
      await AsyncStorage.removeItem(TOKEN_KEY);
    } else {
      await SecureStore.deleteItemAsync(TOKEN_KEY);
    }
  },

  // User data management (AsyncStorage for non-sensitive data)
  saveUser: async (user: any): Promise<void> => {
    await AsyncStorage.setItem(USER_KEY, JSON.stringify(user));
  },

  getUser: async (): Promise<any | null> => {
    const userData = await AsyncStorage.getItem(USER_KEY);
    return userData ? JSON.parse(userData) : null;
  },

  deleteUser: async (): Promise<void> => {
    await AsyncStorage.removeItem(USER_KEY);
  },

  // Referral code management
  saveReferralCode: async (code: string): Promise<void> => {
    await AsyncStorage.setItem(REFERRAL_KEY, code);
  },

  getReferralCode: async (): Promise<string | null> => {
    return await AsyncStorage.getItem(REFERRAL_KEY);
  },

  deleteReferralCode: async (): Promise<void> => {
    await AsyncStorage.removeItem(REFERRAL_KEY);
  },

  // Clear all auth data (logout)
  clearAll: async (): Promise<void> => {
    await Promise.all([
      authManager.deleteToken(),
      authManager.deleteUser(),
      authManager.deleteReferralCode(),
    ]);
  },

  // Check if user is authenticated
  isAuthenticated: async (): Promise<boolean> => {
    const token = await authManager.getToken();
    return token !== null;
  },
};
