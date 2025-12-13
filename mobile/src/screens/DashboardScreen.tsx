import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TouchableOpacity,
  RefreshControl,
  ActivityIndicator,
  SafeAreaView,
  Modal,
  TextInput,
  ScrollView,
  Alert,
} from 'react-native';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../theme/ThemeContext';
import { useAuth } from '../context/AuthContext';
import { projectsApi, marketplaceApi } from '../lib/api';
import Toast from 'react-native-toast-message';

interface Project {
  id: string;
  name: string;
  slug: string;
  description?: string;
  container_status?: string;
  tier: string;
  created_at: string;
  updated_at?: string;
}

interface Base {
  id: number;
  name: string;
  description?: string;
  category?: string;
}

const DashboardScreen: React.FC = () => {
  const navigation = useNavigation();
  const { theme } = useTheme();
  const { user, refreshUser } = useAuth();

  const [projects, setProjects] = useState<Project[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [selectedTab, setSelectedTab] = useState<'all' | 'idea' | 'build' | 'launch'>('all');
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [bases, setBases] = useState<Base[]>([]);

  // Fetch projects
  const fetchProjects = async () => {
    try {
      const data = await projectsApi.getAll();
      setProjects(data);
    } catch (error) {
      console.error('Failed to fetch projects:', error);
      Toast.show({
        type: 'error',
        text1: 'Error',
        text2: 'Failed to load projects',
      });
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  // Fetch bases for create modal
  const fetchBases = async () => {
    try {
      const data = await marketplaceApi.getUserBases();
      setBases(data);
    } catch (error) {
      console.error('Failed to fetch bases:', error);
    }
  };

  useEffect(() => {
    fetchProjects();
    fetchBases();
    refreshUser();
  }, []);

  // Refresh when screen comes into focus
  useFocusEffect(
    useCallback(() => {
      fetchProjects();
      refreshUser();
    }, [])
  );

  const onRefresh = () => {
    setIsRefreshing(true);
    fetchProjects();
    refreshUser();
  };

  const handleDeleteProject = (slug: string, name: string) => {
    Alert.alert(
      'Delete Project',
      `Are you sure you want to delete "${name}"? This action cannot be undone.`,
      [
        {
          text: 'Cancel',
          style: 'cancel',
        },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            try {
              await projectsApi.delete(slug);
              Toast.show({
                type: 'success',
                text1: 'Project Deleted',
                text2: `${name} has been deleted`,
              });
              fetchProjects();
            } catch (error) {
              Toast.show({
                type: 'error',
                text1: 'Error',
                text2: 'Failed to delete project',
              });
            }
          },
        },
      ]
    );
  };

  // Filter projects by tier
  const filteredProjects = projects.filter((project) => {
    if (selectedTab === 'all') return true;
    return project.tier === selectedTab;
  });

  const renderProject = ({ item }: { item: Project }) => (
    <TouchableOpacity
      style={[styles.projectCard, { backgroundColor: theme.card, borderColor: theme.border }]}
      onPress={() => navigation.navigate('ProjectIDE' as never, { slug: item.slug } as never)}
      onLongPress={() => handleDeleteProject(item.slug, item.name)}
    >
      <View style={styles.projectHeader}>
        <View style={styles.projectTitleContainer}>
          <Text style={[styles.projectName, { color: theme.text }]} numberOfLines={1}>
            {item.name}
          </Text>
          {item.container_status && (
            <View
              style={[
                styles.statusBadge,
                {
                  backgroundColor:
                    item.container_status === 'running'
                      ? theme.successLight
                      : item.container_status === 'error'
                      ? theme.errorLight
                      : theme.backgroundTertiary,
                },
              ]}
            >
              <Text
                style={[
                  styles.statusText,
                  {
                    color:
                      item.container_status === 'running'
                        ? theme.success
                        : item.container_status === 'error'
                        ? theme.error
                        : theme.textTertiary,
                  },
                ]}
              >
                {item.container_status}
              </Text>
            </View>
          )}
        </View>
        <Ionicons name="chevron-forward" size={20} color={theme.textTertiary} />
      </View>

      {item.description && (
        <Text style={[styles.projectDescription, { color: theme.textSecondary }]} numberOfLines={2}>
          {item.description}
        </Text>
      )}

      <View style={styles.projectFooter}>
        <View style={[styles.tierBadge, { backgroundColor: getTierColor(item.tier, theme) }]}>
          <Text style={styles.tierText}>{item.tier.toUpperCase()}</Text>
        </View>
        <Text style={[styles.projectDate, { color: theme.textTertiary }]}>
          {new Date(item.created_at).toLocaleDateString()}
        </Text>
      </View>
    </TouchableOpacity>
  );

  const renderEmptyState = () => (
    <View style={styles.emptyState}>
      <Ionicons name="folder-open-outline" size={64} color={theme.textTertiary} />
      <Text style={[styles.emptyTitle, { color: theme.text }]}>No Projects Yet</Text>
      <Text style={[styles.emptyDescription, { color: theme.textSecondary }]}>
        Create your first project to get started
      </Text>
      <TouchableOpacity
        style={[styles.createButton, { backgroundColor: theme.primary }]}
        onPress={() => setCreateModalVisible(true)}
      >
        <Text style={styles.createButtonText}>Create Project</Text>
      </TouchableOpacity>
    </View>
  );

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: theme.background }]}>
      {/* Header */}
      <View style={styles.header}>
        <View>
          <Text style={[styles.headerTitle, { color: theme.text }]}>Dashboard</Text>
          <Text style={[styles.headerSubtitle, { color: theme.textSecondary }]}>
            Welcome back, {user?.name}
          </Text>
        </View>
        {user && (
          <View style={styles.creditsContainer}>
            <Ionicons name="wallet-outline" size={16} color={theme.primary} />
            <Text style={[styles.creditsText, { color: theme.text }]}>
              {user.credits_balance || 0} credits
            </Text>
          </View>
        )}
      </View>

      {/* Tabs */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.tabsContainer}
        contentContainerStyle={styles.tabsContent}
      >
        {['all', 'idea', 'build', 'launch'].map((tab) => (
          <TouchableOpacity
            key={tab}
            style={[
              styles.tab,
              selectedTab === tab && [styles.activeTab, { backgroundColor: theme.primary }],
            ]}
            onPress={() => setSelectedTab(tab as any)}
          >
            <Text
              style={[
                styles.tabText,
                { color: selectedTab === tab ? '#FFFFFF' : theme.textSecondary },
              ]}
            >
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {/* Projects List */}
      {isLoading ? (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={theme.primary} />
        </View>
      ) : (
        <FlatList
          data={filteredProjects}
          renderItem={renderProject}
          keyExtractor={(item) => item.id}
          contentContainerStyle={[
            styles.listContent,
            filteredProjects.length === 0 && styles.emptyListContent,
          ]}
          ListEmptyComponent={renderEmptyState}
          refreshControl={
            <RefreshControl
              refreshing={isRefreshing}
              onRefresh={onRefresh}
              tintColor={theme.primary}
              colors={[theme.primary]}
            />
          }
        />
      )}

      {/* Floating Action Button */}
      {filteredProjects.length > 0 && (
        <TouchableOpacity
          style={[styles.fab, { backgroundColor: theme.primary }]}
          onPress={() => setCreateModalVisible(true)}
        >
          <Ionicons name="add" size={28} color="#FFFFFF" />
        </TouchableOpacity>
      )}

      {/* Create Project Modal */}
      <CreateProjectModal
        visible={createModalVisible}
        onClose={() => setCreateModalVisible(false)}
        onSuccess={() => {
          setCreateModalVisible(false);
          fetchProjects();
        }}
        bases={bases}
        theme={theme}
      />
    </SafeAreaView>
  );
};

// Helper function to get tier color
const getTierColor = (tier: string, theme: any): string => {
  switch (tier.toLowerCase()) {
    case 'idea':
      return theme.infoLight;
    case 'build':
      return theme.warningLight;
    case 'launch':
      return theme.successLight;
    default:
      return theme.backgroundTertiary;
  }
};

// Create Project Modal Component
interface CreateProjectModalProps {
  visible: boolean;
  onClose: () => void;
  onSuccess: () => void;
  bases: Base[];
  theme: any;
}

const CreateProjectModal: React.FC<CreateProjectModalProps> = ({
  visible,
  onClose,
  onSuccess,
  bases,
  theme,
}) => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [sourceType, setSourceType] = useState<'template' | 'github' | 'base'>('template');
  const [githubRepoUrl, setGithubRepoUrl] = useState('');
  const [githubBranch, setGithubBranch] = useState('main');
  const [selectedBase, setSelectedBase] = useState<number | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  const handleCreate = async () => {
    if (!name.trim()) {
      Toast.show({
        type: 'error',
        text1: 'Error',
        text2: 'Please enter a project name',
      });
      return;
    }

    if (sourceType === 'github' && !githubRepoUrl.trim()) {
      Toast.show({
        type: 'error',
        text1: 'Error',
        text2: 'Please enter a GitHub repository URL',
      });
      return;
    }

    if (sourceType === 'base' && !selectedBase) {
      Toast.show({
        type: 'error',
        text1: 'Error',
        text2: 'Please select a base template',
      });
      return;
    }

    setIsCreating(true);
    try {
      await projectsApi.create(
        name.trim(),
        description.trim() || undefined,
        sourceType,
        sourceType === 'github' ? githubRepoUrl.trim() : undefined,
        sourceType === 'github' ? githubBranch.trim() : undefined,
        sourceType === 'base' ? selectedBase?.toString() : undefined
      );

      Toast.show({
        type: 'success',
        text1: 'Success',
        text2: `Project "${name}" created successfully`,
      });

      // Reset form
      setName('');
      setDescription('');
      setSourceType('template');
      setGithubRepoUrl('');
      setGithubBranch('main');
      setSelectedBase(null);

      onSuccess();
    } catch (error) {
      console.error('Failed to create project:', error);
      Toast.show({
        type: 'error',
        text1: 'Error',
        text2: 'Failed to create project',
      });
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" transparent={true}>
      <View style={styles.modalOverlay}>
        <View style={[styles.modalContent, { backgroundColor: theme.card }]}>
          {/* Header */}
          <View style={styles.modalHeader}>
            <Text style={[styles.modalTitle, { color: theme.text }]}>Create New Project</Text>
            <TouchableOpacity onPress={onClose}>
              <Ionicons name="close" size={24} color={theme.textSecondary} />
            </TouchableOpacity>
          </View>

          <ScrollView style={styles.modalBody} showsVerticalScrollIndicator={false}>
            {/* Name */}
            <View style={styles.inputGroup}>
              <Text style={[styles.label, { color: theme.text }]}>Project Name</Text>
              <TextInput
                style={[
                  styles.input,
                  { backgroundColor: theme.backgroundSecondary, borderColor: theme.border, color: theme.text },
                ]}
                placeholder="My Awesome Project"
                placeholderTextColor={theme.textTertiary}
                value={name}
                onChangeText={setName}
              />
            </View>

            {/* Description */}
            <View style={styles.inputGroup}>
              <Text style={[styles.label, { color: theme.text }]}>Description (Optional)</Text>
              <TextInput
                style={[
                  styles.input,
                  styles.textArea,
                  { backgroundColor: theme.backgroundSecondary, borderColor: theme.border, color: theme.text },
                ]}
                placeholder="Describe your project..."
                placeholderTextColor={theme.textTertiary}
                value={description}
                onChangeText={setDescription}
                multiline
                numberOfLines={3}
              />
            </View>

            {/* Source Type */}
            <View style={styles.inputGroup}>
              <Text style={[styles.label, { color: theme.text }]}>Source</Text>
              <View style={styles.sourceTypeButtons}>
                <TouchableOpacity
                  style={[
                    styles.sourceTypeButton,
                    { borderColor: theme.border },
                    sourceType === 'template' && { backgroundColor: theme.primary, borderColor: theme.primary },
                  ]}
                  onPress={() => setSourceType('template')}
                >
                  <Text
                    style={[
                      styles.sourceTypeText,
                      { color: sourceType === 'template' ? '#FFFFFF' : theme.text },
                    ]}
                  >
                    Template
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[
                    styles.sourceTypeButton,
                    { borderColor: theme.border },
                    sourceType === 'github' && { backgroundColor: theme.primary, borderColor: theme.primary },
                  ]}
                  onPress={() => setSourceType('github')}
                >
                  <Text
                    style={[
                      styles.sourceTypeText,
                      { color: sourceType === 'github' ? '#FFFFFF' : theme.text },
                    ]}
                  >
                    GitHub
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[
                    styles.sourceTypeButton,
                    { borderColor: theme.border },
                    sourceType === 'base' && { backgroundColor: theme.primary, borderColor: theme.primary },
                  ]}
                  onPress={() => setSourceType('base')}
                >
                  <Text
                    style={[
                      styles.sourceTypeText,
                      { color: sourceType === 'base' ? '#FFFFFF' : theme.text },
                    ]}
                  >
                    Base
                  </Text>
                </TouchableOpacity>
              </View>
            </View>

            {/* GitHub Fields */}
            {sourceType === 'github' && (
              <>
                <View style={styles.inputGroup}>
                  <Text style={[styles.label, { color: theme.text }]}>Repository URL</Text>
                  <TextInput
                    style={[
                      styles.input,
                      { backgroundColor: theme.backgroundSecondary, borderColor: theme.border, color: theme.text },
                    ]}
                    placeholder="https://github.com/username/repo"
                    placeholderTextColor={theme.textTertiary}
                    value={githubRepoUrl}
                    onChangeText={setGithubRepoUrl}
                    autoCapitalize="none"
                  />
                </View>
                <View style={styles.inputGroup}>
                  <Text style={[styles.label, { color: theme.text }]}>Branch</Text>
                  <TextInput
                    style={[
                      styles.input,
                      { backgroundColor: theme.backgroundSecondary, borderColor: theme.border, color: theme.text },
                    ]}
                    placeholder="main"
                    placeholderTextColor={theme.textTertiary}
                    value={githubBranch}
                    onChangeText={setGithubBranch}
                    autoCapitalize="none"
                  />
                </View>
              </>
            )}

            {/* Base Selection */}
            {sourceType === 'base' && (
              <View style={styles.inputGroup}>
                <Text style={[styles.label, { color: theme.text }]}>Select Base</Text>
                {bases.length === 0 ? (
                  <Text style={[styles.noBasesText, { color: theme.textTertiary }]}>
                    No bases available. Purchase from Marketplace.
                  </Text>
                ) : (
                  bases.map((base) => (
                    <TouchableOpacity
                      key={base.id}
                      style={[
                        styles.baseOption,
                        { borderColor: theme.border },
                        selectedBase === base.id && { backgroundColor: theme.primaryLight, borderColor: theme.primary },
                      ]}
                      onPress={() => setSelectedBase(base.id)}
                    >
                      <Text style={[styles.baseName, { color: theme.text }]}>{base.name}</Text>
                      {base.description && (
                        <Text style={[styles.baseDescription, { color: theme.textSecondary }]} numberOfLines={1}>
                          {base.description}
                        </Text>
                      )}
                    </TouchableOpacity>
                  ))
                )}
              </View>
            )}
          </ScrollView>

          {/* Footer */}
          <View style={[styles.modalFooter, { borderTopColor: theme.border }]}>
            <TouchableOpacity style={[styles.cancelButton, { borderColor: theme.border }]} onPress={onClose}>
              <Text style={[styles.cancelButtonText, { color: theme.text }]}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.createModalButton, { backgroundColor: theme.primary }]}
              onPress={handleCreate}
              disabled={isCreating}
            >
              {isCreating ? (
                <ActivityIndicator color="#FFFFFF" />
              ) : (
                <Text style={styles.createModalButtonText}>Create</Text>
              )}
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    padding: 20,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
  },
  headerTitle: {
    fontSize: 28,
    fontWeight: 'bold',
  },
  headerSubtitle: {
    fontSize: 14,
    marginTop: 4,
  },
  creditsContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
  },
  creditsText: {
    fontSize: 14,
    fontWeight: '600',
  },
  tabsContainer: {
    marginHorizontal: 20,
    marginBottom: 16,
  },
  tabsContent: {
    gap: 8,
  },
  tab: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 20,
  },
  activeTab: {},
  tabText: {
    fontSize: 14,
    fontWeight: '600',
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  listContent: {
    padding: 20,
  },
  emptyListContent: {
    flexGrow: 1,
  },
  projectCard: {
    padding: 16,
    borderRadius: 12,
    marginBottom: 12,
    borderWidth: 1,
    elevation: 2,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.1,
    shadowRadius: 2,
  },
  projectHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  projectTitleContainer: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  projectName: {
    fontSize: 18,
    fontWeight: '600',
    flex: 1,
  },
  statusBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 12,
  },
  statusText: {
    fontSize: 11,
    fontWeight: '600',
    textTransform: 'capitalize',
  },
  projectDescription: {
    fontSize: 14,
    marginBottom: 12,
    lineHeight: 20,
  },
  projectFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  tierBadge: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
  },
  tierText: {
    fontSize: 11,
    fontWeight: '700',
    color: '#FFFFFF',
  },
  projectDate: {
    fontSize: 12,
  },
  emptyState: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 40,
  },
  emptyTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    marginTop: 16,
  },
  emptyDescription: {
    fontSize: 14,
    textAlign: 'center',
    marginTop: 8,
    marginBottom: 24,
  },
  createButton: {
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 8,
  },
  createButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
  fab: {
    position: 'absolute',
    right: 20,
    bottom: 20,
    width: 56,
    height: 56,
    borderRadius: 28,
    justifyContent: 'center',
    alignItems: 'center',
    elevation: 4,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.3,
    shadowRadius: 4,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'flex-end',
  },
  modalContent: {
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    maxHeight: '90%',
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 20,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: 'bold',
  },
  modalBody: {
    paddingHorizontal: 20,
    maxHeight: 500,
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
  textArea: {
    height: 80,
    textAlignVertical: 'top',
  },
  sourceTypeButtons: {
    flexDirection: 'row',
    gap: 8,
  },
  sourceTypeButton: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 8,
    borderWidth: 1,
    alignItems: 'center',
  },
  sourceTypeText: {
    fontSize: 14,
    fontWeight: '600',
  },
  noBasesText: {
    fontSize: 14,
    textAlign: 'center',
    paddingVertical: 20,
  },
  baseOption: {
    padding: 12,
    borderRadius: 8,
    borderWidth: 1,
    marginBottom: 8,
  },
  baseName: {
    fontSize: 16,
    fontWeight: '600',
  },
  baseDescription: {
    fontSize: 13,
    marginTop: 4,
  },
  modalFooter: {
    flexDirection: 'row',
    gap: 12,
    padding: 20,
    borderTopWidth: 1,
  },
  cancelButton: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 8,
    borderWidth: 1,
    alignItems: 'center',
  },
  cancelButtonText: {
    fontSize: 16,
    fontWeight: '600',
  },
  createModalButton: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center',
  },
  createModalButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
});

export default DashboardScreen;
