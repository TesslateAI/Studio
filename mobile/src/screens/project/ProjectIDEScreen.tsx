import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  SafeAreaView,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { useRoute, useNavigation } from '@react-navigation/native';
import { createMaterialTopTabNavigator } from '@react-navigation/material-top-tabs';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../theme/ThemeContext';
import { projectsApi } from '../../lib/api';
import Toast from 'react-native-toast-message';

// Tab components
import ChatTab from './tabs/ChatTab';
import PreviewTab from './tabs/PreviewTab';
import FilesTab from './tabs/FilesTab';
import TasksTab from './tabs/TasksTab';
import NotesTab from './tabs/NotesTab';

const Tab = createMaterialTopTabNavigator();

interface Project {
  id: string;
  name: string;
  slug: string;
  description?: string;
  container_status?: string;
  tier: string;
}

const ProjectIDEScreen: React.FC = () => {
  const route = useRoute();
  const navigation = useNavigation();
  const { theme } = useTheme();
  const { slug } = route.params as { slug: string };

  const [project, setProject] = useState<Project | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [containerStatus, setContainerStatus] = useState<string>('');

  useEffect(() => {
    fetchProject();
    const interval = setInterval(checkContainerStatus, 5000); // Check status every 5 seconds
    return () => clearInterval(interval);
  }, [slug]);

  const fetchProject = async () => {
    try {
      const data = await projectsApi.get(slug);
      setProject(data);
      setContainerStatus(data.container_status || 'stopped');
    } catch (error) {
      console.error('Failed to fetch project:', error);
      Toast.show({
        type: 'error',
        text1: 'Error',
        text2: 'Failed to load project',
      });
      navigation.goBack();
    } finally {
      setIsLoading(false);
    }
  };

  const checkContainerStatus = async () => {
    try {
      const status = await projectsApi.getContainerStatus(slug);
      setContainerStatus(status.status);
    } catch (error) {
      console.error('Failed to check container status:', error);
    }
  };

  const handleRestartContainer = async () => {
    try {
      await projectsApi.restartDevServer(slug);
      Toast.show({
        type: 'success',
        text1: 'Container Restarted',
        text2: 'Development server is starting...',
      });
      setTimeout(checkContainerStatus, 2000);
    } catch (error) {
      Toast.show({
        type: 'error',
        text1: 'Error',
        text2: 'Failed to restart container',
      });
    }
  };

  const handleStopContainer = async () => {
    try {
      await projectsApi.stopDevServer(slug);
      Toast.show({
        type: 'success',
        text1: 'Container Stopped',
        text2: 'Development server has been stopped',
      });
      setContainerStatus('stopped');
    } catch (error) {
      Toast.show({
        type: 'error',
        text1: 'Error',
        text2: 'Failed to stop container',
      });
    }
  };

  const getStatusColor = () => {
    switch (containerStatus) {
      case 'running':
        return theme.success;
      case 'starting':
        return theme.warning;
      case 'error':
        return theme.error;
      default:
        return theme.textTertiary;
    }
  };

  if (isLoading || !project) {
    return (
      <View style={[styles.loadingContainer, { backgroundColor: theme.background }]}>
        <ActivityIndicator size="large" color={theme.primary} />
      </View>
    );
  }

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: theme.background }]}>
      {/* Header */}
      <View style={[styles.header, { borderBottomColor: theme.border }]}>
        <TouchableOpacity
          onPress={() => navigation.goBack()}
          style={styles.backButton}
        >
          <Ionicons name="arrow-back" size={24} color={theme.text} />
        </TouchableOpacity>

        <View style={styles.headerCenter}>
          <Text style={[styles.projectName, { color: theme.text }]} numberOfLines={1}>
            {project.name}
          </Text>
          <View style={styles.statusRow}>
            <View style={[styles.statusDot, { backgroundColor: getStatusColor() }]} />
            <Text style={[styles.statusText, { color: theme.textSecondary }]}>
              {containerStatus}
            </Text>
          </View>
        </View>

        <View style={styles.headerActions}>
          {containerStatus === 'running' ? (
            <TouchableOpacity onPress={handleStopContainer}>
              <Ionicons name="stop-circle-outline" size={24} color={theme.error} />
            </TouchableOpacity>
          ) : (
            <TouchableOpacity onPress={handleRestartContainer}>
              <Ionicons name="play-circle-outline" size={24} color={theme.primary} />
            </TouchableOpacity>
          )}
        </View>
      </View>

      {/* Tabs */}
      <Tab.Navigator
        screenOptions={{
          tabBarStyle: { backgroundColor: theme.card },
          tabBarLabelStyle: { fontSize: 12, fontWeight: '600', textTransform: 'none' },
          tabBarActiveTintColor: theme.primary,
          tabBarInactiveTintColor: theme.textTertiary,
          tabBarIndicatorStyle: { backgroundColor: theme.primary },
          tabBarScrollEnabled: true,
        }}
      >
        <Tab.Screen
          name="Chat"
          component={ChatTab}
          initialParams={{ projectSlug: slug }}
          options={{
            tabBarIcon: ({ color }) => <Ionicons name="chatbubbles" size={18} color={color} />,
          }}
        />
        <Tab.Screen
          name="Preview"
          component={PreviewTab}
          initialParams={{ projectSlug: slug }}
          options={{
            tabBarIcon: ({ color }) => <Ionicons name="phone-portrait" size={18} color={color} />,
          }}
        />
        <Tab.Screen
          name="Files"
          component={FilesTab}
          initialParams={{ projectSlug: slug }}
          options={{
            tabBarIcon: ({ color }) => <Ionicons name="folder" size={18} color={color} />,
          }}
        />
        <Tab.Screen
          name="Tasks"
          component={TasksTab}
          initialParams={{ projectSlug: slug }}
          options={{
            tabBarIcon: ({ color }) => <Ionicons name="list" size={18} color={color} />,
          }}
        />
        <Tab.Screen
          name="Notes"
          component={NotesTab}
          initialParams={{ projectSlug: slug }}
          options={{
            tabBarIcon: ({ color }) => <Ionicons name="document-text" size={18} color={color} />,
          }}
        />
      </Tab.Navigator>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
  },
  backButton: {
    marginRight: 12,
  },
  headerCenter: {
    flex: 1,
  },
  projectName: {
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 4,
  },
  statusRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 6,
  },
  statusText: {
    fontSize: 12,
    textTransform: 'capitalize',
  },
  headerActions: {
    flexDirection: 'row',
    gap: 12,
  },
});

export default ProjectIDEScreen;
