import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  SafeAreaView,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
  Alert,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import * as WebBrowser from 'expo-web-browser';
import { useAuth } from '../../context/AuthContext';
import { useTheme } from '../../theme/ThemeContext';
import { authApi } from '../../lib/api';
import Toast from 'react-native-toast-message';

WebBrowser.maybeCompleteAuthSession();

const LoginScreen: React.FC = () => {
  const navigation = useNavigation();
  const { login } = useAuth();
  const { theme } = useTheme();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({});

  const validateForm = (): boolean => {
    const newErrors: { email?: string; password?: string } = {};

    if (!email.trim()) {
      newErrors.email = 'Email is required';
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      newErrors.email = 'Invalid email format';
    }

    if (!password) {
      newErrors.password = 'Password is required';
    } else if (password.length < 6) {
      newErrors.password = 'Password must be at least 6 characters';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleLogin = async () => {
    if (!validateForm()) return;

    setIsLoading(true);
    try {
      await login(email.trim(), password);
      Toast.show({
        type: 'success',
        text1: 'Welcome back!',
        text2: 'You have successfully logged in.',
      });
    } catch (error: any) {
      console.error('Login error:', error);
      const errorMessage =
        error.response?.data?.detail || 'Invalid email or password';
      Toast.show({
        type: 'error',
        text1: 'Login Failed',
        text2: errorMessage,
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleGithubLogin = async () => {
    try {
      const authUrl = await authApi.getGithubAuthUrl();
      const result = await WebBrowser.openAuthSessionAsync(
        authUrl,
        'tesslate://oauth/callback'
      );

      if (result.type === 'success') {
        // The backend sets a cookie, so we just need to check authentication
        Toast.show({
          type: 'success',
          text1: 'Welcome!',
          text2: 'Logged in with GitHub.',
        });
      }
    } catch (error) {
      console.error('GitHub login error:', error);
      Toast.show({
        type: 'error',
        text1: 'OAuth Failed',
        text2: 'Failed to authenticate with GitHub.',
      });
    }
  };

  const handleGoogleLogin = async () => {
    try {
      const authUrl = await authApi.getGoogleAuthUrl();
      const result = await WebBrowser.openAuthSessionAsync(
        authUrl,
        'tesslate://oauth/callback'
      );

      if (result.type === 'success') {
        Toast.show({
          type: 'success',
          text1: 'Welcome!',
          text2: 'Logged in with Google.',
        });
      }
    } catch (error) {
      console.error('Google login error:', error);
      Toast.show({
        type: 'error',
        text1: 'OAuth Failed',
        text2: 'Failed to authenticate with Google.',
      });
    }
  };

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: theme.background }]}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.keyboardAvoid}
      >
        <ScrollView
          contentContainerStyle={styles.scrollContent}
          keyboardShouldPersistTaps="handled"
        >
          <View style={styles.content}>
            {/* Header */}
            <View style={styles.header}>
              <TouchableOpacity onPress={() => navigation.goBack()}>
                <Text style={[styles.backButton, { color: theme.primary }]}>← Back</Text>
              </TouchableOpacity>
              <Text style={[styles.title, { color: theme.text }]}>Welcome Back</Text>
              <Text style={[styles.subtitle, { color: theme.textSecondary }]}>
                Sign in to continue
              </Text>
            </View>

            {/* Form */}
            <View style={styles.form}>
              <View style={styles.inputGroup}>
                <Text style={[styles.label, { color: theme.text }]}>Email</Text>
                <TextInput
                  style={[
                    styles.input,
                    {
                      backgroundColor: theme.backgroundSecondary,
                      borderColor: errors.email ? theme.error : theme.border,
                      color: theme.text,
                    },
                  ]}
                  placeholder="you@example.com"
                  placeholderTextColor={theme.textTertiary}
                  value={email}
                  onChangeText={(text) => {
                    setEmail(text);
                    if (errors.email) setErrors({ ...errors, email: undefined });
                  }}
                  keyboardType="email-address"
                  autoCapitalize="none"
                  autoCorrect={false}
                  editable={!isLoading}
                />
                {errors.email && (
                  <Text style={[styles.errorText, { color: theme.error }]}>
                    {errors.email}
                  </Text>
                )}
              </View>

              <View style={styles.inputGroup}>
                <Text style={[styles.label, { color: theme.text }]}>Password</Text>
                <TextInput
                  style={[
                    styles.input,
                    {
                      backgroundColor: theme.backgroundSecondary,
                      borderColor: errors.password ? theme.error : theme.border,
                      color: theme.text,
                    },
                  ]}
                  placeholder="Enter your password"
                  placeholderTextColor={theme.textTertiary}
                  value={password}
                  onChangeText={(text) => {
                    setPassword(text);
                    if (errors.password)
                      setErrors({ ...errors, password: undefined });
                  }}
                  secureTextEntry
                  autoCapitalize="none"
                  editable={!isLoading}
                />
                {errors.password && (
                  <Text style={[styles.errorText, { color: theme.error }]}>
                    {errors.password}
                  </Text>
                )}
              </View>

              {/* Login Button */}
              <TouchableOpacity
                style={[
                  styles.loginButton,
                  { backgroundColor: theme.primary },
                  isLoading && styles.disabledButton,
                ]}
                onPress={handleLogin}
                disabled={isLoading}
              >
                {isLoading ? (
                  <ActivityIndicator color="#FFFFFF" />
                ) : (
                  <Text style={styles.loginButtonText}>Sign In</Text>
                )}
              </TouchableOpacity>

              {/* Divider */}
              <View style={styles.divider}>
                <View style={[styles.dividerLine, { backgroundColor: theme.border }]} />
                <Text style={[styles.dividerText, { color: theme.textTertiary }]}>
                  OR
                </Text>
                <View style={[styles.dividerLine, { backgroundColor: theme.border }]} />
              </View>

              {/* OAuth Buttons */}
              <TouchableOpacity
                style={[
                  styles.oauthButton,
                  {
                    backgroundColor: theme.backgroundSecondary,
                    borderColor: theme.border,
                  },
                ]}
                onPress={handleGithubLogin}
                disabled={isLoading}
              >
                <Text style={[styles.oauthButtonText, { color: theme.text }]}>
                  🔗 Continue with GitHub
                </Text>
              </TouchableOpacity>

              <TouchableOpacity
                style={[
                  styles.oauthButton,
                  {
                    backgroundColor: theme.backgroundSecondary,
                    borderColor: theme.border,
                  },
                ]}
                onPress={handleGoogleLogin}
                disabled={isLoading}
              >
                <Text style={[styles.oauthButtonText, { color: theme.text }]}>
                  🔗 Continue with Google
                </Text>
              </TouchableOpacity>
            </View>

            {/* Footer */}
            <View style={styles.footer}>
              <Text style={[styles.footerText, { color: theme.textSecondary }]}>
                Don't have an account?{' '}
                <Text
                  style={[styles.link, { color: theme.primary }]}
                  onPress={() => navigation.navigate('Register' as never)}
                >
                  Sign Up
                </Text>
              </Text>
            </View>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  keyboardAvoid: {
    flex: 1,
  },
  scrollContent: {
    flexGrow: 1,
  },
  content: {
    flex: 1,
    paddingHorizontal: 24,
    paddingTop: 20,
  },
  header: {
    marginBottom: 32,
  },
  backButton: {
    fontSize: 16,
    marginBottom: 16,
  },
  title: {
    fontSize: 28,
    fontWeight: 'bold',
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 16,
  },
  form: {
    flex: 1,
  },
  inputGroup: {
    marginBottom: 20,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    marginBottom: 8,
  },
  input: {
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 16,
    paddingVertical: 12,
    fontSize: 16,
  },
  errorText: {
    fontSize: 12,
    marginTop: 4,
  },
  loginButton: {
    paddingVertical: 16,
    borderRadius: 8,
    alignItems: 'center',
    marginTop: 8,
  },
  disabledButton: {
    opacity: 0.6,
  },
  loginButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
  divider: {
    flexDirection: 'row',
    alignItems: 'center',
    marginVertical: 24,
  },
  dividerLine: {
    flex: 1,
    height: 1,
  },
  dividerText: {
    marginHorizontal: 16,
    fontSize: 14,
  },
  oauthButton: {
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center',
    borderWidth: 1,
    marginBottom: 12,
  },
  oauthButtonText: {
    fontSize: 15,
    fontWeight: '500',
  },
  footer: {
    alignItems: 'center',
    paddingVertical: 24,
  },
  footerText: {
    fontSize: 14,
  },
  link: {
    fontWeight: '600',
  },
});

export default LoginScreen;
