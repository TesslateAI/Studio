import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TouchableOpacity,
  ActivityIndicator,
  Modal,
  TextInput,
  ScrollView,
  Platform,
} from 'react-native';
import { useRoute } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../../theme/ThemeContext';
import { projectsApi } from '../../../lib/api';
import Toast from 'react-native-toast-message';

interface FileNode {
  name: string;
  path: string;
  type: 'file' | 'directory';
  children?: FileNode[];
}

const FilesTab: React.FC = () => {
  const route = useRoute();
  const { theme, isDark } = useTheme();
  const { projectSlug } = route.params as { projectSlug: string };

  const [files, setFiles] = useState<FileNode[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [selectedFile, setSelectedFile] = useState<{path: string; content: string; language: string} | null>(null);
  const [viewerVisible, setViewerVisible] = useState(false);

  useEffect(() => {
    fetchFiles();
  }, []);

  const fetchFiles = async () => {
    try {
      const data = await projectsApi.getFiles(projectSlug);
      setFiles(buildFileTree(data));
    } catch (error) {
      console.error('Failed to fetch files:', error);
      Toast.show({
        type: 'error',
        text1: 'Error',
        text2: 'Failed to load files',
      });
    } finally {
      setIsLoading(false);
    }
  };

  const buildFileTree = (flatFiles: any[]): FileNode[] => {
    const root: FileNode[] = [];
    const folders: Map<string, FileNode> = new Map();

    flatFiles.forEach((file) => {
      const parts = file.path.split('/');
      let currentLevel = root;

      parts.forEach((part, index) => {
        const currentPath = parts.slice(0, index + 1).join('/');
        const isLastPart = index === parts.length - 1;

        if (isLastPart && file.type === 'file') {
          currentLevel.push({
            name: part,
            path: file.path,
            type: 'file',
          });
        } else if (!isLastPart || file.type === 'directory') {
          let folder = folders.get(currentPath);
          if (!folder) {
            folder = {
              name: part,
              path: currentPath,
              type: 'directory',
              children: [],
            };
            folders.set(currentPath, folder);
            currentLevel.push(folder);
          }
          currentLevel = folder.children || [];
        }
      });
    });

    return root;
  };

  const toggleFolder = (path: string) => {
    const newExpanded = new Set(expandedFolders);
    if (newExpanded.has(path)) {
      newExpanded.delete(path);
    } else {
      newExpanded.add(path);
    }
    setExpandedFolders(newExpanded);
  };

  const handleFilePress = async (filePath: string) => {
    try {
      // Read file content (simulated - you'd need an API endpoint)
      // For now, we'll show a placeholder
      const extension = filePath.split('.').pop() || '';
      const languageMap: Record<string, string> = {
        js: 'javascript',
        jsx: 'javascript',
        ts: 'typescript',
        tsx: 'typescript',
        py: 'python',
        html: 'html',
        css: 'css',
        json: 'json',
        md: 'markdown',
      };

      const language = languageMap[extension] || 'plaintext';

      // TODO: Fetch actual file content from API
      const content = `// File: ${filePath}\n// Content would be loaded from API\n\n// Sample code`;

      setSelectedFile({ path: filePath, content, language });
      setViewerVisible(true);
    } catch (error) {
      Toast.show({
        type: 'error',
        text1: 'Error',
        text2: 'Failed to open file',
      });
    }
  };

  const renderFileNode = (node: FileNode, depth: number = 0) => {
    const isExpanded = expandedFolders.has(node.path);
    const items: JSX.Element[] = [];

    if (node.type === 'directory') {
      items.push(
        <TouchableOpacity
          key={node.path}
          style={[
            styles.fileItem,
            { paddingLeft: 16 + depth * 20, backgroundColor: theme.background },
          ]}
          onPress={() => toggleFolder(node.path)}
        >
          <Ionicons
            name={isExpanded ? 'folder-open' : 'folder'}
            size={20}
            color={theme.primary}
          />
          <Text style={[styles.fileName, { color: theme.text }]}>{node.name}</Text>
          <Ionicons
            name={isExpanded ? 'chevron-down' : 'chevron-forward'}
            size={16}
            color={theme.textTertiary}
          />
        </TouchableOpacity>
      );

      if (isExpanded && node.children) {
        node.children.forEach((child) => {
          items.push(...renderFileNode(child, depth + 1));
        });
      }
    } else {
      items.push(
        <TouchableOpacity
          key={node.path}
          style={[
            styles.fileItem,
            { paddingLeft: 16 + depth * 20, backgroundColor: theme.background },
          ]}
          onPress={() => handleFilePress(node.path)}
        >
          <Ionicons
            name={getFileIcon(node.name)}
            size={18}
            color={theme.textSecondary}
          />
          <Text style={[styles.fileName, { color: theme.text }]}>{node.name}</Text>
        </TouchableOpacity>
      );
    }

    return items;
  };

  const getFileIcon = (filename: string): keyof typeof Ionicons.glyphMap => {
    const extension = filename.split('.').pop()?.toLowerCase();
    const iconMap: Record<string, keyof typeof Ionicons.glyphMap> = {
      js: 'logo-javascript',
      jsx: 'logo-react',
      ts: 'logo-javascript',
      tsx: 'logo-react',
      py: 'logo-python',
      html: 'logo-html5',
      css: 'logo-css3',
      json: 'code-slash',
      md: 'document-text',
    };
    return iconMap[extension || ''] || 'document-outline';
  };

  return (
    <View style={[styles.container, { backgroundColor: theme.background }]}>
      {isLoading ? (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={theme.primary} />
        </View>
      ) : (
        <FlatList
          data={files.flatMap((node) => renderFileNode(node))}
          renderItem={({ item }) => item}
          keyExtractor={(_, index) => index.toString()}
          ListEmptyComponent={
            <View style={styles.emptyState}>
              <Ionicons name="folder-open-outline" size={64} color={theme.textTertiary} />
              <Text style={[styles.emptyText, { color: theme.textSecondary }]}>
                No files found
              </Text>
            </View>
          }
        />
      )}

      {/* File Viewer Modal */}
      <Modal visible={viewerVisible} animationType="slide">
        <View style={[styles.modalContainer, { backgroundColor: theme.background }]}>
          <View style={[styles.modalHeader, { borderBottomColor: theme.border }]}>
            <Text style={[styles.modalTitle, { color: theme.text }]} numberOfLines={1}>
              {selectedFile?.path}
            </Text>
            <TouchableOpacity onPress={() => setViewerVisible(false)}>
              <Ionicons name="close" size={24} color={theme.textSecondary} />
            </TouchableOpacity>
          </View>

          <ScrollView style={styles.codeContainer}>
            {selectedFile && (
              <View style={[styles.codeBlock, { backgroundColor: theme.backgroundSecondary }]}>
                <Text style={[styles.codeText, { color: theme.text }]}>
                  {selectedFile.content}
                </Text>
              </View>
            )}
          </ScrollView>
        </View>
      </Modal>
    </View>
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
  fileItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    paddingRight: 16,
    gap: 12,
  },
  fileName: {
    flex: 1,
    fontSize: 14,
  },
  emptyState: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingTop: 80,
  },
  emptyText: {
    fontSize: 16,
    marginTop: 16,
  },
  modalContainer: {
    flex: 1,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 16,
    borderBottomWidth: 1,
  },
  modalTitle: {
    flex: 1,
    fontSize: 16,
    fontWeight: '600',
    marginRight: 16,
  },
  codeContainer: {
    flex: 1,
  },
  codeBlock: {
    padding: 16,
    margin: 16,
    borderRadius: 8,
  },
  codeText: {
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
    fontSize: 13,
    lineHeight: 20,
  },
});

export default FilesTab;
