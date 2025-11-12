import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  SafeAreaView,
  Switch,
  Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useNavigation } from '@react-navigation/native';
import { useTheme } from '../theme/ThemeContext';
import { useAuth } from '../context/AuthContext';
import Toast from 'react-native-toast-message';

const SettingsScreen: React.FC = () => {
  const navigation = useNavigation();
  const { theme, themeMode, setThemeMode, isDark } = useTheme();
  const { user, logout } = useAuth();

  const handleLogout = () => {
    Alert.alert('Logout', 'Are you sure you want to logout?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Logout',
        style: 'destructive',
        onPress: async () => {
          await logout();
          Toast.show({
            type: 'success',
            text1: 'Logged Out',
            text2: 'See you soon!',
          });
        },
      },
    ]);
  };

  const toggleTheme = () => {
    if (themeMode === 'light') {
      setThemeMode('dark');
    } else if (themeMode === 'dark') {
      setThemeMode('auto');
    } else {
      setThemeMode('light');
    }
  };

  const getThemeLabel = () => {
    switch (themeMode) {
      case 'light':
        return 'Light';
      case 'dark':
        return 'Dark';
      case 'auto':
        return 'Auto';
      default:
        return 'Auto';
    }
  };

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: theme.background }]}>
      <ScrollView contentContainerStyle={styles.scrollContent}>
        {/* Header */}
        <View style={styles.header}>
          <Text style={[styles.headerTitle, { color: theme.text }]}>Settings</Text>
        </View>

        {/* Profile Section */}
        <View style={styles.section}>
          <Text style={[styles.sectionTitle, { color: theme.textSecondary }]}>PROFILE</Text>

          <View style={[styles.card, { backgroundColor: theme.card }]}>
            <View style={styles.profileInfo}>
              <View style={[styles.avatar, { backgroundColor: theme.primary }]}>
                <Text style={styles.avatarText}>
                  {user?.name?.charAt(0).toUpperCase() || 'U'}
                </Text>
              </View>
              <View style={styles.profileDetails}>
                <Text style={[styles.profileName, { color: theme.text }]}>
                  {user?.name || 'User'}
                </Text>
                <Text style={[styles.profileEmail, { color: theme.textSecondary }]}>
                  {user?.email || 'email@example.com'}
                </Text>
              </View>
            </View>

            {user?.subscription_tier && (
              <View style={[styles.tierBadge, { backgroundColor: theme.primaryLight }]}>
                <Text style={[styles.tierText, { color: theme.primary }]}>
                  {user.subscription_tier.toUpperCase()}
                </Text>
              </View>
            )}

            <View style={[styles.creditsRow, { borderTopColor: theme.border }]}>
              <View style={styles.creditsInfo}>
                <Ionicons name="wallet-outline" size={20} color={theme.primary} />
                <Text style={[styles.creditsLabel, { color: theme.textSecondary }]}>
                  Credits Balance
                </Text>
              </View>
              <Text style={[styles.creditsValue, { color: theme.text }]}>
                {user?.credits_balance || 0}
              </Text>
            </View>
          </View>
        </View>

        {/* Appearance Section */}
        <View style={styles.section}>
          <Text style={[styles.sectionTitle, { color: theme.textSecondary }]}>APPEARANCE</Text>

          <View style={[styles.card, { backgroundColor: theme.card }]}>
            <TouchableOpacity
              style={[styles.settingRow, { borderBottomColor: theme.border }]}
              onPress={toggleTheme}
            >
              <View style={styles.settingLeft}>
                <Ionicons
                  name={isDark ? 'moon' : 'sunny'}
                  size={20}
                  color={theme.primary}
                />
                <Text style={[styles.settingLabel, { color: theme.text }]}>Theme</Text>
              </View>
              <View style={styles.settingRight}>
                <Text style={[styles.settingValue, { color: theme.textSecondary }]}>
                  {getThemeLabel()}
                </Text>
                <Ionicons name="chevron-forward" size={20} color={theme.textTertiary} />
              </View>
            </TouchableOpacity>
          </View>
        </View>

        {/* Account Section */}
        <View style={styles.section}>
          <Text style={[styles.sectionTitle, { color: theme.textSecondary }]}>ACCOUNT</Text>

          <View style={[styles.card, { backgroundColor: theme.card }]}>
            <TouchableOpacity
              style={[styles.settingRow, { borderBottomColor: theme.border }]}
              onPress={() => {
                Toast.show({
                  type: 'info',
                  text1: 'Coming Soon',
                  text2: 'Billing management coming soon',
                });
              }}
            >
              <View style={styles.settingLeft}>
                <Ionicons name="card-outline" size={20} color={theme.primary} />
                <Text style={[styles.settingLabel, { color: theme.text }]}>Billing</Text>
              </View>
              <Ionicons name="chevron-forward" size={20} color={theme.textTertiary} />
            </TouchableOpacity>

            <TouchableOpacity
              style={[styles.settingRow, { borderBottomColor: theme.border }]}
              onPress={() => {
                Toast.show({
                  type: 'info',
                  text1: 'Coming Soon',
                  text2: 'API key management coming soon',
                });
              }}
            >
              <View style={styles.settingLeft}>
                <Ionicons name="key-outline" size={20} color={theme.primary} />
                <Text style={[styles.settingLabel, { color: theme.text }]}>API Keys</Text>
              </View>
              <Ionicons name="chevron-forward" size={20} color={theme.textTertiary} />
            </TouchableOpacity>

            <TouchableOpacity
              style={[styles.settingRow, { borderBottomColor: theme.border }]}
              onPress={() => {
                Toast.show({
                  type: 'info',
                  text1: 'Coming Soon',
                  text2: 'Usage statistics coming soon',
                });
              }}
            >
              <View style={styles.settingLeft}>
                <Ionicons name="stats-chart-outline" size={20} color={theme.primary} />
                <Text style={[styles.settingLabel, { color: theme.text }]}>Usage</Text>
              </View>
              <Ionicons name="chevron-forward" size={20} color={theme.textTertiary} />
            </TouchableOpacity>

            <TouchableOpacity
              style={styles.settingRow}
              onPress={() => {
                Toast.show({
                  type: 'info',
                  text1: 'Coming Soon',
                  text2: 'Referral program coming soon',
                });
              }}
            >
              <View style={styles.settingLeft}>
                <Ionicons name="gift-outline" size={20} color={theme.primary} />
                <Text style={[styles.settingLabel, { color: theme.text }]}>Referrals</Text>
              </View>
              <Ionicons name="chevron-forward" size={20} color={theme.textTertiary} />
            </TouchableOpacity>
          </View>
        </View>

        {/* Support Section */}
        <View style={styles.section}>
          <Text style={[styles.sectionTitle, { color: theme.textSecondary }]}>SUPPORT</Text>

          <View style={[styles.card, { backgroundColor: theme.card }]}>
            <TouchableOpacity
              style={[styles.settingRow, { borderBottomColor: theme.border }]}
              onPress={() => {
                Toast.show({
                  type: 'info',
                  text1: 'Documentation',
                  text2: 'Visit docs.tesslate.com',
                });
              }}
            >
              <View style={styles.settingLeft}>
                <Ionicons name="book-outline" size={20} color={theme.primary} />
                <Text style={[styles.settingLabel, { color: theme.text }]}>Documentation</Text>
              </View>
              <Ionicons name="chevron-forward" size={20} color={theme.textTertiary} />
            </TouchableOpacity>

            <TouchableOpacity
              style={[styles.settingRow, { borderBottomColor: theme.border }]}
              onPress={() => {
                Toast.show({
                  type: 'info',
                  text1: 'Feedback',
                  text2: 'Send us your feedback',
                });
              }}
            >
              <View style={styles.settingLeft}>
                <Ionicons name="chatbubble-outline" size={20} color={theme.primary} />
                <Text style={[styles.settingLabel, { color: theme.text }]}>Feedback</Text>
              </View>
              <Ionicons name="chevron-forward" size={20} color={theme.textTertiary} />
            </TouchableOpacity>

            <TouchableOpacity
              style={styles.settingRow}
              onPress={() => {
                Toast.show({
                  type: 'info',
                  text1: 'Help Center',
                  text2: 'Visit support.tesslate.com',
                });
              }}
            >
              <View style={styles.settingLeft}>
                <Ionicons name="help-circle-outline" size={20} color={theme.primary} />
                <Text style={[styles.settingLabel, { color: theme.text }]}>Help Center</Text>
              </View>
              <Ionicons name="chevron-forward" size={20} color={theme.textTertiary} />
            </TouchableOpacity>
          </View>
        </View>

        {/* Logout Button */}
        <TouchableOpacity
          style={[styles.logoutButton, { backgroundColor: theme.errorLight }]}
          onPress={handleLogout}
        >
          <Ionicons name="log-out-outline" size={20} color={theme.error} />
          <Text style={[styles.logoutText, { color: theme.error }]}>Logout</Text>
        </TouchableOpacity>

        {/* App Version */}
        <View style={styles.versionContainer}>
          <Text style={[styles.versionText, { color: theme.textTertiary }]}>
            Tesslate Studio Mobile v1.0.0
          </Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  scrollContent: {
    paddingBottom: 40,
  },
  header: {
    padding: 20,
  },
  headerTitle: {
    fontSize: 28,
    fontWeight: 'bold',
  },
  section: {
    marginBottom: 24,
  },
  sectionTitle: {
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1,
    paddingHorizontal: 20,
    marginBottom: 8,
  },
  card: {
    marginHorizontal: 20,
    borderRadius: 12,
    padding: 16,
  },
  profileInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  avatar: {
    width: 60,
    height: 60,
    borderRadius: 30,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 16,
  },
  avatarText: {
    color: '#FFFFFF',
    fontSize: 24,
    fontWeight: 'bold',
  },
  profileDetails: {
    flex: 1,
  },
  profileName: {
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 4,
  },
  profileEmail: {
    fontSize: 14,
  },
  tierBadge: {
    alignSelf: 'flex-start',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    marginBottom: 12,
  },
  tierText: {
    fontSize: 12,
    fontWeight: '700',
  },
  creditsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderTopWidth: 1,
    paddingTop: 12,
  },
  creditsInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  creditsLabel: {
    fontSize: 14,
  },
  creditsValue: {
    fontSize: 18,
    fontWeight: '600',
  },
  settingRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 12,
    borderBottomWidth: 1,
  },
  settingLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  settingLabel: {
    fontSize: 16,
  },
  settingRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  settingValue: {
    fontSize: 14,
  },
  logoutButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    marginHorizontal: 20,
    paddingVertical: 14,
    borderRadius: 12,
    marginTop: 8,
  },
  logoutText: {
    fontSize: 16,
    fontWeight: '600',
  },
  versionContainer: {
    alignItems: 'center',
    marginTop: 24,
  },
  versionText: {
    fontSize: 12,
  },
});

export default SettingsScreen;
