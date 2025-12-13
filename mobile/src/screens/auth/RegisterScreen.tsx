import React, { useState, useEffect } from 'react';
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
} from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import * as WebBrowser from 'expo-web-browser';
import { useAuth } from '../../context/AuthContext';
import { useTheme } from '../../theme/ThemeContext';
import { authApi } from '../../lib/api';
import { authManager } from '../../lib/auth';
import Toast from 'react-native-toast-message';

WebBrowser.maybeCompleteAuthSession();

const RegisterScreen: React.FC = () => {
  const navigation = useNavigation();
  const route = useRoute();
  const { register } = useAuth();
  const { theme } = useTheme();

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [referralCode, setReferralCode] = useState('');
  const [agreedToTerms, setAgreedToTerms] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errors, setErrors] = useState<{
    name?: string;
    email?: string;
    password?: string;
    confirmPassword?: string;
    terms?: string;
  }>({});

  // Check for referral code in route params
  useEffect(() => {
    const params = route.params as any;
    if (params?.ref) {
      setReferralCode(params.ref);
      authManager.saveReferralCode(params.ref);
    } else {
      // Load from storage
      authManager.getReferralCode().then((code) => {
        if (code) setReferralCode(code);
      });
    }
  }, [route.params]);

  const validateForm = (): boolean => {
    const newErrors: {
      name?: string;
      email?: string;
      password?: string;
      confirmPassword?: string;
      terms?: string;
    } = {};

    if (!name.trim()) {
      newErrors.name = 'Name is required';
    } else if (name.trim().length < 2) {
      newErrors.name = 'Name must be at least 2 characters';
    }

    if (!email.trim()) {
      newErrors.email = 'Email is required';
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      newErrors.email = 'Invalid email format';
    }

    if (!password) {
      newErrors.password = 'Password is required';
    } else if (password.length < 6) {
      newErrors.password = 'Password must be at least 6 characters';
    } else if (!/(?=.*[a-z])(?=.*[A-Z])(?=.*\d)/.test(password)) {
      newErrors.password =
        'Password must contain uppercase, lowercase, and a number';
    }

    if (!confirmPassword) {
      newErrors.confirmPassword = 'Please confirm your password';
    } else if (password !== confirmPassword) {
      newErrors.confirmPassword = 'Passwords do not match';
    }

    if (!agreedToTerms) {
      newErrors.terms = 'You must agree to the Terms of Service';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleRegister = async () => {
    if (!validateForm()) return;

    setIsLoading(true);
    try {
      await register(name.trim(), email.trim(), password, referralCode || undefined);
      Toast.show({
        type: 'success',
        text1: 'Welcome to Tesslate!',
        text2: 'Your account has been created successfully.',
      });
    } catch (error: any) {
      console.error('Registration error:', error);
      const errorMessage =
        error.response?.data?.detail || 'Failed to create account';
      Toast.show({
        type: 'error',
        text1: 'Registration Failed',
        text2: errorMessage,
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleGithubRegister = async () => {
    try {
      const authUrl = await authApi.getGithubAuthUrl();
      const result = await WebBrowser.openAuthSessionAsync(
        authUrl,
        'tesslate://oauth/callback'
      );

      if (result.type === 'success') {
        Toast.show({
          type: 'success',
          text1: 'Welcome!',
          text2: 'Account created with GitHub.',
        });
      }
    } catch (error) {
      console.error('GitHub registration error:', error);
      Toast.show({
        type: 'error',
        text1: 'OAuth Failed',
        text2: 'Failed to authenticate with GitHub.',
      });
    }
  };

  const handleGoogleRegister = async () => {
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
          text2: 'Account created with Google.',
        });
      }
    } catch (error) {
      console.error('Google registration error:', error);
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
              <Text style={[styles.title, { color: theme.text }]}>Create Account</Text>
              <Text style={[styles.subtitle, { color: theme.textSecondary }]}>
                Join Tesslate Studio today
              </Text>
            </View>

            {/* Form */}
            <View style={styles.form}>
              <View style={styles.inputGroup}>
                <Text style={[styles.label, { color: theme.text }]}>Full Name</Text>
                <TextInput
                  style={[
                    styles.input,
                    {
                      backgroundColor: theme.backgroundSecondary,
                      borderColor: errors.name ? theme.error : theme.border,
                      color: theme.text,
                    },
                  ]}
                  placeholder="John Doe"
                  placeholderTextColor={theme.textTertiary}
                  value={name}
                  onChangeText={(text) => {
                    setName(text);
                    if (errors.name) setErrors({ ...errors, name: undefined });
                  }}
                  autoCapitalize="words"
                  editable={!isLoading}
                />
                {errors.name && (
                  <Text style={[styles.errorText, { color: theme.error }]}>
                    {errors.name}
                  </Text>
                )}
              </View>

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
                  placeholder="At least 6 characters"
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

              <View style={styles.inputGroup}>
                <Text style={[styles.label, { color: theme.text }]}>
                  Confirm Password
                </Text>
                <TextInput
                  style={[
                    styles.input,
                    {
                      backgroundColor: theme.backgroundSecondary,
                      borderColor: errors.confirmPassword
                        ? theme.error
                        : theme.border,
                      color: theme.text,
                    },
                  ]}
                  placeholder="Re-enter password"
                  placeholderTextColor={theme.textTertiary}
                  value={confirmPassword}
                  onChangeText={(text) => {
                    setConfirmPassword(text);
                    if (errors.confirmPassword)
                      setErrors({ ...errors, confirmPassword: undefined });
                  }}
                  secureTextEntry
                  autoCapitalize="none"
                  editable={!isLoading}
                />
                {errors.confirmPassword && (
                  <Text style={[styles.errorText, { color: theme.error }]}>
                    {errors.confirmPassword}
                  </Text>
                )}
              </View>

              <View style={styles.inputGroup}>
                <Text style={[styles.label, { color: theme.text }]}>
                  Referral Code (Optional)
                </Text>
                <TextInput
                  style={[
                    styles.input,
                    {
                      backgroundColor: theme.backgroundSecondary,
                      borderColor: theme.border,
                      color: theme.text,
                    },
                  ]}
                  placeholder="Enter code if you have one"
                  placeholderTextColor={theme.textTertiary}
                  value={referralCode}
                  onChangeText={setReferralCode}
                  autoCapitalize="none"
                  editable={!isLoading}
                />
              </View>

              {/* Terms Checkbox */}
              <TouchableOpacity
                style={styles.checkboxContainer}
                onPress={() => {
                  setAgreedToTerms(!agreedToTerms);
                  if (errors.terms) setErrors({ ...errors, terms: undefined });
                }}
                disabled={isLoading}
              >
                <View
                  style={[
                    styles.checkbox,
                    {
                      borderColor: errors.terms ? theme.error : theme.border,
                      backgroundColor: agreedToTerms
                        ? theme.primary
                        : 'transparent',
                    },
                  ]}
                >
                  {agreedToTerms && (
                    <Text style={styles.checkmark}>✓</Text>
                  )}
                </View>
                <Text style={[styles.checkboxLabel, { color: theme.textSecondary }]}>
                  I agree to the{' '}
                  <Text style={[styles.link, { color: theme.primary }]}>
                    Terms of Service
                  </Text>{' '}
                  and{' '}
                  <Text style={[styles.link, { color: theme.primary }]}>
                    Privacy Policy
                  </Text>
                </Text>
              </TouchableOpacity>
              {errors.terms && (
                <Text style={[styles.errorText, { color: theme.error, marginTop: 4 }]}>
                  {errors.terms}
                </Text>
              )}

              {/* Register Button */}
              <TouchableOpacity
                style={[
                  styles.registerButton,
                  { backgroundColor: theme.primary },
                  isLoading && styles.disabledButton,
                ]}
                onPress={handleRegister}
                disabled={isLoading}
              >
                {isLoading ? (
                  <ActivityIndicator color="#FFFFFF" />
                ) : (
                  <Text style={styles.registerButtonText}>Create Account</Text>
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
                onPress={handleGithubRegister}
                disabled={isLoading}
              >
                <Text style={[styles.oauthButtonText, { color: theme.text }]}>
                  🔗 Sign up with GitHub
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
                onPress={handleGoogleRegister}
                disabled={isLoading}
              >
                <Text style={[styles.oauthButtonText, { color: theme.text }]}>
                  🔗 Sign up with Google
                </Text>
              </TouchableOpacity>
            </View>

            {/* Footer */}
            <View style={styles.footer}>
              <Text style={[styles.footerText, { color: theme.textSecondary }]}>
                Already have an account?{' '}
                <Text
                  style={[styles.link, { color: theme.primary }]}
                  onPress={() => navigation.navigate('Login' as never)}
                >
                  Sign In
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
    marginBottom: 16,
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
  checkboxContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 8,
    marginBottom: 24,
  },
  checkbox: {
    width: 20,
    height: 20,
    borderWidth: 2,
    borderRadius: 4,
    marginRight: 12,
    justifyContent: 'center',
    alignItems: 'center',
  },
  checkmark: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: 'bold',
  },
  checkboxLabel: {
    flex: 1,
    fontSize: 13,
  },
  registerButton: {
    paddingVertical: 16,
    borderRadius: 8,
    alignItems: 'center',
  },
  disabledButton: {
    opacity: 0.6,
  },
  registerButtonText: {
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

export default RegisterScreen;
