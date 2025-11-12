import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { useRoute } from '@react-navigation/native';
import { WebView } from 'react-native-webview';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../../theme/ThemeContext';
import { projectsApi } from '../../../lib/api';
import Toast from 'react-native-toast-message';

const PreviewTab: React.FC = () => {
  const route = useRoute();
  const { theme } = useTheme();
  const { projectSlug } = route.params as { projectSlug: string };

  const [previewUrl, setPreviewUrl] = useState<string>('');
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [webViewKey, setWebViewKey] = useState(0);

  useEffect(() => {
    fetchPreviewUrl();
  }, []);

  const fetchPreviewUrl = async () => {
    try {
      const response = await projectsApi.getDevServerUrl(projectSlug);
      setPreviewUrl(response.url);
    } catch (error) {
      console.error('Failed to fetch preview URL:', error);
      Toast.show({
        type: 'error',
        text1: 'Error',
        text2: 'Failed to load preview',
      });
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  const handleRefresh = () => {
    setIsRefreshing(true);
    // Force WebView reload by changing key
    setWebViewKey((prev) => prev + 1);
    fetchPreviewUrl();
  };

  if (isLoading) {
    return (
      <View style={[styles.container, { backgroundColor: theme.background }]}>
        <ActivityIndicator size="large" color={theme.primary} />
      </View>
    );
  }

  if (!previewUrl) {
    return (
      <View style={[styles.container, { backgroundColor: theme.background }]}>
        <Ionicons name="warning-outline" size={64} color={theme.textTertiary} />
        <Text style={[styles.errorText, { color: theme.textSecondary }]}>
          Preview not available. Make sure the dev server is running.
        </Text>
        <TouchableOpacity
          style={[styles.retryButton, { backgroundColor: theme.primary }]}
          onPress={fetchPreviewUrl}
        >
          <Text style={styles.retryButtonText}>Retry</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={[styles.container, { backgroundColor: theme.background }]}>
      {/* Toolbar */}
      <View style={[styles.toolbar, { backgroundColor: theme.card, borderBottomColor: theme.border }]}>
        <TouchableOpacity
          style={styles.toolbarButton}
          onPress={() => setWebViewKey((prev) => prev - 1)}
          disabled={webViewKey === 0}
        >
          <Ionicons
            name="arrow-back"
            size={24}
            color={webViewKey === 0 ? theme.textTertiary : theme.text}
          />
        </TouchableOpacity>

        <TouchableOpacity style={styles.toolbarButton} onPress={handleRefresh}>
          <Ionicons
            name={isRefreshing ? 'hourglass-outline' : 'refresh'}
            size={24}
            color={theme.text}
          />
        </TouchableOpacity>

        <View style={[styles.urlBar, { backgroundColor: theme.backgroundSecondary }]}>
          <Text style={[styles.urlText, { color: theme.textSecondary }]} numberOfLines={1}>
            {previewUrl}
          </Text>
        </View>
      </View>

      {/* WebView */}
      <WebView
        key={webViewKey}
        source={{ uri: previewUrl }}
        style={styles.webview}
        onLoadStart={() => setIsRefreshing(true)}
        onLoadEnd={() => setIsRefreshing(false)}
        onError={(syntheticEvent) => {
          const { nativeEvent } = syntheticEvent;
          console.error('WebView error:', nativeEvent);
          Toast.show({
            type: 'error',
            text1: 'Load Error',
            text2: 'Failed to load preview',
          });
        }}
        startInLoadingState
        renderLoading={() => (
          <View style={styles.loadingOverlay}>
            <ActivityIndicator size="large" color={theme.primary} />
          </View>
        )}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  toolbar: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderBottomWidth: 1,
  },
  toolbarButton: {
    padding: 8,
    marginRight: 8,
  },
  urlBar: {
    flex: 1,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 8,
  },
  urlText: {
    fontSize: 13,
  },
  webview: {
    flex: 1,
    width: '100%',
  },
  loadingOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: 'rgba(255, 255, 255, 0.9)',
  },
  errorText: {
    fontSize: 16,
    textAlign: 'center',
    marginTop: 16,
    marginHorizontal: 40,
  },
  retryButton: {
    marginTop: 24,
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 8,
  },
  retryButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
});

export default PreviewTab;
