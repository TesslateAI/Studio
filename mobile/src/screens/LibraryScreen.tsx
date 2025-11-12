import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TouchableOpacity,
  ActivityIndicator,
  SafeAreaView,
  ScrollView,
  Modal,
  TextInput,
  Switch,
  Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../theme/ThemeContext';
import { marketplaceApi } from '../lib/api';
import Toast from 'react-native-toast-message';
import { Picker } from '@react-native-picker/picker';

interface Agent {
  id: string;
  name: string;
  description?: string;
  icon: string;
  is_active?: boolean;
  model?: string;
  is_custom?: boolean;
}

interface Model {
  id: string;
  name: string;
}

const LibraryScreen: React.FC = () => {
  const { theme } = useTheme();
  const [selectedTab, setSelectedTab] = useState<'agents' | 'bases'>('agents');
  const [myAgents, setMyAgents] = useState<Agent[]>([]);
  const [bases, setBases] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [availableModels, setAvailableModels] = useState<Model[]>([]);

  useEffect(() => {
    fetchLibraryData();
    fetchModels();
  }, [selectedTab]);

  const fetchLibraryData = async () => {
    setIsLoading(true);
    try {
      if (selectedTab === 'agents') {
        const data = await marketplaceApi.getMyAgents();
        setMyAgents(data);
      } else {
        const data = await marketplaceApi.getUserBases();
        setBases(data);
      }
    } catch (error) {
      console.error('Failed to fetch library:', error);
      Toast.show({
        type: 'error',
        text1: 'Error',
        text2: 'Failed to load library',
      });
    } finally {
      setIsLoading(false);
    }
  };

  const fetchModels = async () => {
    try {
      const data = await marketplaceApi.getAvailableModels();
      setAvailableModels(data);
    } catch (error) {
      console.error('Failed to fetch models:', error);
    }
  };

  const handleToggleAgent = async (agentId: string, currentState: boolean) => {
    try {
      await marketplaceApi.toggleAgent(agentId, !currentState);
      Toast.show({
        type: 'success',
        text1: 'Success',
        text2: `Agent ${!currentState ? 'enabled' : 'disabled'}`,
      });
      fetchLibraryData();
    } catch (error) {
      Toast.show({
        type: 'error',
        text1: 'Error',
        text2: 'Failed to update agent',
      });
    }
  };

  const handleDeleteAgent = (agentId: string, agentName: string) => {
    Alert.alert(
      'Delete Agent',
      `Are you sure you want to remove "${agentName}" from your library?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            try {
              await marketplaceApi.removeFromLibrary(agentId);
              Toast.show({
                type: 'success',
                text1: 'Success',
                text2: 'Agent removed from library',
              });
              fetchLibraryData();
            } catch (error) {
              Toast.show({
                type: 'error',
                text1: 'Error',
                text2: 'Failed to remove agent',
              });
            }
          },
        },
      ]
    );
  };

  const renderAgent = ({ item }: { item: Agent }) => (
    <TouchableOpacity
      style={[styles.agentCard, { backgroundColor: theme.card, borderColor: theme.border }]}
      onLongPress={() => handleDeleteAgent(item.id, item.name)}
    >
      <View style={styles.agentHeader}>
        <View style={[styles.iconContainer, { backgroundColor: theme.primaryLight }]}>
          <Text style={styles.iconText}>{item.icon || '🤖'}</Text>
        </View>
        <View style={styles.agentInfo}>
          <Text style={[styles.agentName, { color: theme.text }]} numberOfLines={1}>
            {item.name}
          </Text>
          {item.model && (
            <Text style={[styles.agentModel, { color: theme.textTertiary }]}>
              {item.model}
            </Text>
          )}
        </View>
        <Switch
          value={item.is_active}
          onValueChange={() => handleToggleAgent(item.id, item.is_active || false)}
          trackColor={{ false: theme.border, true: theme.primaryLight }}
          thumbColor={item.is_active ? theme.primary : theme.textTertiary}
        />
      </View>

      {item.description && (
        <Text style={[styles.agentDescription, { color: theme.textSecondary }]} numberOfLines={2}>
          {item.description}
        </Text>
      )}

      {item.is_custom && (
        <View style={[styles.customBadge, { backgroundColor: theme.warningLight }]}>
          <Text style={[styles.customText, { color: theme.warning }]}>Custom</Text>
        </View>
      )}
    </TouchableOpacity>
  );

  const renderBase = ({ item }: { item: any }) => (
    <TouchableOpacity
      style={[styles.baseCard, { backgroundColor: theme.card, borderColor: theme.border }]}
    >
      <Text style={[styles.baseName, { color: theme.text }]}>{item.name}</Text>
      {item.description && (
        <Text style={[styles.baseDescription, { color: theme.textSecondary }]} numberOfLines={2}>
          {item.description}
        </Text>
      )}
      {item.category && (
        <View style={[styles.categoryBadge, { backgroundColor: theme.backgroundSecondary }]}>
          <Text style={[styles.categoryText, { color: theme.textSecondary }]}>
            {item.category}
          </Text>
        </View>
      )}
    </TouchableOpacity>
  );

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: theme.background }]}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={[styles.headerTitle, { color: theme.text }]}>Library</Text>
        <TouchableOpacity
          style={[styles.createButton, { backgroundColor: theme.primary }]}
          onPress={() => setCreateModalVisible(true)}
        >
          <Ionicons name="add" size={20} color="#FFFFFF" />
        </TouchableOpacity>
      </View>

      {/* Tabs */}
      <View style={styles.tabsContainer}>
        <TouchableOpacity
          style={[
            styles.tab,
            selectedTab === 'agents' && [styles.activeTab, { backgroundColor: theme.primary }],
          ]}
          onPress={() => setSelectedTab('agents')}
        >
          <Text
            style={[
              styles.tabText,
              { color: selectedTab === 'agents' ? '#FFFFFF' : theme.textSecondary },
            ]}
          >
            My Agents
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[
            styles.tab,
            selectedTab === 'bases' && [styles.activeTab, { backgroundColor: theme.primary }],
          ]}
          onPress={() => setSelectedTab('bases')}
        >
          <Text
            style={[
              styles.tabText,
              { color: selectedTab === 'bases' ? '#FFFFFF' : theme.textSecondary },
            ]}
          >
            Bases
          </Text>
        </TouchableOpacity>
      </View>

      {/* Content */}
      {isLoading ? (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={theme.primary} />
        </View>
      ) : (
        <FlatList
          data={selectedTab === 'agents' ? myAgents : bases}
          renderItem={selectedTab === 'agents' ? renderAgent : renderBase}
          keyExtractor={(item) => item.id.toString()}
          contentContainerStyle={styles.listContent}
          ListEmptyComponent={
            <View style={styles.emptyState}>
              <Ionicons name="folder-open-outline" size={64} color={theme.textTertiary} />
              <Text style={[styles.emptyText, { color: theme.textSecondary }]}>
                No {selectedTab} in your library
              </Text>
            </View>
          }
        />
      )}

      {/* Create Agent Modal */}
      <CreateAgentModal
        visible={createModalVisible}
        onClose={() => setCreateModalVisible(false)}
        onSuccess={() => {
          setCreateModalVisible(false);
          fetchLibraryData();
        }}
        availableModels={availableModels}
        theme={theme}
      />
    </SafeAreaView>
  );
};

// Create Agent Modal Component
interface CreateAgentModalProps {
  visible: boolean;
  onClose: () => void;
  onSuccess: () => void;
  availableModels: Model[];
  theme: any;
}

const CreateAgentModal: React.FC<CreateAgentModalProps> = ({
  visible,
  onClose,
  onSuccess,
  availableModels,
  theme,
}) => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [isCreating, setIsCreating] = useState(false);

  const handleCreate = async () => {
    if (!name.trim() || !systemPrompt.trim() || !selectedModel) {
      Toast.show({
        type: 'error',
        text1: 'Error',
        text2: 'Please fill in all required fields',
      });
      return;
    }

    setIsCreating(true);
    try {
      await marketplaceApi.createCustomAgent({
        name: name.trim(),
        description: description.trim(),
        system_prompt: systemPrompt.trim(),
        mode: 'agent',
        agent_type: 'CustomAgent',
        model: selectedModel,
      });

      Toast.show({
        type: 'success',
        text1: 'Success',
        text2: 'Agent created successfully',
      });

      setName('');
      setDescription('');
      setSystemPrompt('');
      setSelectedModel('');
      onSuccess();
    } catch (error) {
      Toast.show({
        type: 'error',
        text1: 'Error',
        text2: 'Failed to create agent',
      });
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <Modal visible={visible} animationType="slide" transparent={true}>
      <View style={styles.modalOverlay}>
        <View style={[styles.modalContent, { backgroundColor: theme.card }]}>
          <View style={styles.modalHeader}>
            <Text style={[styles.modalTitle, { color: theme.text }]}>Create Custom Agent</Text>
            <TouchableOpacity onPress={onClose}>
              <Ionicons name="close" size={24} color={theme.textSecondary} />
            </TouchableOpacity>
          </View>

          <ScrollView style={styles.modalBody}>
            <View style={styles.inputGroup}>
              <Text style={[styles.label, { color: theme.text }]}>Name *</Text>
              <TextInput
                style={[
                  styles.input,
                  { backgroundColor: theme.backgroundSecondary, borderColor: theme.border, color: theme.text },
                ]}
                placeholder="My Custom Agent"
                placeholderTextColor={theme.textTertiary}
                value={name}
                onChangeText={setName}
              />
            </View>

            <View style={styles.inputGroup}>
              <Text style={[styles.label, { color: theme.text }]}>Description</Text>
              <TextInput
                style={[
                  styles.input,
                  { backgroundColor: theme.backgroundSecondary, borderColor: theme.border, color: theme.text },
                ]}
                placeholder="Describe your agent..."
                placeholderTextColor={theme.textTertiary}
                value={description}
                onChangeText={setDescription}
                multiline
                numberOfLines={2}
              />
            </View>

            <View style={styles.inputGroup}>
              <Text style={[styles.label, { color: theme.text }]}>System Prompt *</Text>
              <TextInput
                style={[
                  styles.input,
                  styles.textArea,
                  { backgroundColor: theme.backgroundSecondary, borderColor: theme.border, color: theme.text },
                ]}
                placeholder="You are a helpful AI assistant..."
                placeholderTextColor={theme.textTertiary}
                value={systemPrompt}
                onChangeText={setSystemPrompt}
                multiline
                numberOfLines={6}
              />
            </View>

            <View style={styles.inputGroup}>
              <Text style={[styles.label, { color: theme.text }]}>Model *</Text>
              <View style={[styles.pickerContainer, { backgroundColor: theme.backgroundSecondary, borderColor: theme.border }]}>
                <Picker
                  selectedValue={selectedModel}
                  onValueChange={setSelectedModel}
                  style={{ color: theme.text }}
                >
                  <Picker.Item label="Select a model..." value="" />
                  {availableModels.map((model) => (
                    <Picker.Item key={model.id} label={model.name} value={model.id} />
                  ))}
                </Picker>
              </View>
            </View>
          </ScrollView>

          <View style={[styles.modalFooter, { borderTopColor: theme.border }]}>
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
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 20,
  },
  headerTitle: {
    fontSize: 28,
    fontWeight: 'bold',
  },
  createButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    justifyContent: 'center',
    alignItems: 'center',
  },
  tabsContainer: {
    flexDirection: 'row',
    paddingHorizontal: 20,
    gap: 12,
    marginBottom: 16,
  },
  tab: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 8,
    alignItems: 'center',
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
  agentCard: {
    padding: 16,
    borderRadius: 12,
    marginBottom: 12,
    borderWidth: 1,
  },
  agentHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  iconContainer: {
    width: 40,
    height: 40,
    borderRadius: 20,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  iconText: {
    fontSize: 20,
  },
  agentInfo: {
    flex: 1,
  },
  agentName: {
    fontSize: 16,
    fontWeight: '600',
  },
  agentModel: {
    fontSize: 12,
    marginTop: 2,
  },
  agentDescription: {
    fontSize: 14,
    lineHeight: 20,
  },
  customBadge: {
    alignSelf: 'flex-start',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
    marginTop: 8,
  },
  customText: {
    fontSize: 12,
    fontWeight: '600',
  },
  baseCard: {
    padding: 16,
    borderRadius: 12,
    marginBottom: 12,
    borderWidth: 1,
  },
  baseName: {
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 8,
  },
  baseDescription: {
    fontSize: 14,
    marginBottom: 8,
  },
  categoryBadge: {
    alignSelf: 'flex-start',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
  },
  categoryText: {
    fontSize: 12,
    fontWeight: '600',
  },
  emptyState: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingTop: 60,
  },
  emptyText: {
    fontSize: 16,
    marginTop: 16,
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
    height: 100,
    textAlignVertical: 'top',
  },
  pickerContainer: {
    borderWidth: 1,
    borderRadius: 8,
    overflow: 'hidden',
  },
  modalFooter: {
    padding: 20,
    borderTopWidth: 1,
  },
  createModalButton: {
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

export default LibraryScreen;
