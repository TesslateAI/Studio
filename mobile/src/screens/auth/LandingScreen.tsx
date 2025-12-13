import React from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  SafeAreaView,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { useTheme } from '../../theme/ThemeContext';

const LandingScreen: React.FC = () => {
  const navigation = useNavigation();
  const { theme } = useTheme();

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: theme.background }]}>
      <ScrollView contentContainerStyle={styles.scrollContent}>
        <View style={styles.content}>
          {/* Logo */}
          <View style={styles.logoContainer}>
            <Text style={[styles.logo, { color: theme.primary }]}>Tesslate Studio</Text>
            <Text style={[styles.tagline, { color: theme.textSecondary }]}>
              Your AI-Powered Development Platform
            </Text>
          </View>

          {/* Features */}
          <View style={styles.featuresContainer}>
            <FeatureItem
              icon="🚀"
              title="Rapid Development"
              description="Build projects faster with AI agents"
              theme={theme}
            />
            <FeatureItem
              icon="🤖"
              title="AI Agents"
              description="Powered by advanced language models"
              theme={theme}
            />
            <FeatureItem
              icon="📱"
              title="Mobile & Web"
              description="Work from anywhere, anytime"
              theme={theme}
            />
          </View>

          {/* CTA Buttons */}
          <View style={styles.buttonContainer}>
            <TouchableOpacity
              style={[styles.primaryButton, { backgroundColor: theme.primary }]}
              onPress={() => navigation.navigate('Register' as never)}
            >
              <Text style={styles.primaryButtonText}>Get Started</Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[styles.secondaryButton, { borderColor: theme.border }]}
              onPress={() => navigation.navigate('Login' as never)}
            >
              <Text style={[styles.secondaryButtonText, { color: theme.text }]}>
                Sign In
              </Text>
            </TouchableOpacity>
          </View>

          {/* Links */}
          <View style={styles.linksContainer}>
            <Text style={[styles.linkText, { color: theme.textTertiary }]}>
              By continuing, you agree to our Terms & Privacy Policy
            </Text>
          </View>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
};

const FeatureItem: React.FC<{
  icon: string;
  title: string;
  description: string;
  theme: any;
}> = ({ icon, title, description, theme }) => (
  <View style={styles.featureItem}>
    <Text style={styles.featureIcon}>{icon}</Text>
    <View style={styles.featureText}>
      <Text style={[styles.featureTitle, { color: theme.text }]}>{title}</Text>
      <Text style={[styles.featureDescription, { color: theme.textSecondary }]}>
        {description}
      </Text>
    </View>
  </View>
);

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  scrollContent: {
    flexGrow: 1,
  },
  content: {
    flex: 1,
    paddingHorizontal: 24,
    justifyContent: 'center',
  },
  logoContainer: {
    alignItems: 'center',
    marginBottom: 48,
  },
  logo: {
    fontSize: 32,
    fontWeight: 'bold',
    marginBottom: 8,
  },
  tagline: {
    fontSize: 16,
    textAlign: 'center',
  },
  featuresContainer: {
    marginBottom: 48,
  },
  featureItem: {
    flexDirection: 'row',
    marginBottom: 24,
    alignItems: 'center',
  },
  featureIcon: {
    fontSize: 32,
    marginRight: 16,
  },
  featureText: {
    flex: 1,
  },
  featureTitle: {
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 4,
  },
  featureDescription: {
    fontSize: 14,
  },
  buttonContainer: {
    gap: 12,
  },
  primaryButton: {
    paddingVertical: 16,
    borderRadius: 8,
    alignItems: 'center',
  },
  primaryButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
  secondaryButton: {
    paddingVertical: 16,
    borderRadius: 8,
    alignItems: 'center',
    borderWidth: 1,
  },
  secondaryButtonText: {
    fontSize: 16,
    fontWeight: '600',
  },
  linksContainer: {
    marginTop: 24,
    alignItems: 'center',
  },
  linkText: {
    fontSize: 12,
    textAlign: 'center',
  },
});

export default LandingScreen;
