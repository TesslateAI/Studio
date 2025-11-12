import React, { useState, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { useRoute } from '@react-navigation/native';
import { RichEditor, RichToolbar, actions } from 'react-native-pell-rich-editor';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../../theme/ThemeContext';
import Toast from 'react-native-toast-message';

const NotesTab: React.FC = () => {
  const route = useRoute();
  const { theme } = useTheme();
  const { projectSlug } = route.params as { projectSlug: string };

  const richText = useRef<RichEditor>(null);
  const [content, setContent] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  const handleSave = async () => {
    if (isSaving) return;

    setIsSaving(true);
    try {
      // TODO: Save to API
      // await projectsApi.saveNotes(projectSlug, content);

      Toast.show({
        type: 'success',
        text1: 'Saved',
        text2: 'Notes saved successfully',
      });
    } catch (error) {
      Toast.show({
        type: 'error',
        text1: 'Error',
        text2: 'Failed to save notes',
      });
    } finally {
      setTimeout(() => setIsSaving(false), 500);
    }
  };

  const handleCursorPosition = (scrollY: number) => {
    // Scroll to cursor position
  };

  return (
    <KeyboardAvoidingView
      style={[styles.container, { backgroundColor: theme.background }]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={Platform.OS === 'ios' ? 100 : 0}
    >
      {/* Header */}
      <View style={[styles.header, { backgroundColor: theme.card, borderBottomColor: theme.border }]}>
        <Text style={[styles.headerTitle, { color: theme.text }]}>Project Notes</Text>
        <TouchableOpacity
          style={[
            styles.saveButton,
            { backgroundColor: isSaving ? theme.backgroundSecondary : theme.primary },
          ]}
          onPress={handleSave}
          disabled={isSaving}
        >
          {isSaving ? (
            <Ionicons name="checkmark-circle" size={20} color={theme.success} />
          ) : (
            <Ionicons name="save-outline" size={20} color="#FFFFFF" />
          )}
          <Text
            style={[
              styles.saveButtonText,
              { color: isSaving ? theme.textSecondary : '#FFFFFF' },
            ]}
          >
            {isSaving ? 'Saved' : 'Save'}
          </Text>
        </TouchableOpacity>
      </View>

      {/* Rich Text Toolbar */}
      <RichToolbar
        editor={richText}
        actions={[
          actions.setBold,
          actions.setItalic,
          actions.setUnderline,
          actions.heading1,
          actions.heading2,
          actions.insertBulletsList,
          actions.insertOrderedList,
          actions.insertLink,
          actions.setStrikethrough,
          actions.checkboxList,
          actions.undo,
          actions.redo,
        ]}
        style={[styles.toolbar, { backgroundColor: theme.card, borderBottomColor: theme.border }]}
        iconTint={theme.text}
        selectedIconTint={theme.primary}
        disabledIconTint={theme.textTertiary}
      />

      {/* Rich Text Editor */}
      <ScrollView style={styles.editorContainer}>
        <RichEditor
          ref={richText}
          style={[styles.editor, { backgroundColor: theme.background }]}
          initialContentHTML={content}
          onChange={(html) => setContent(html)}
          placeholder="Start typing your notes..."
          onCursorPosition={handleCursorPosition}
          editorStyle={{
            backgroundColor: theme.background,
            color: theme.text,
            placeholderColor: theme.textTertiary,
            contentCSSText: `
              font-size: 16px;
              line-height: 1.6;
              padding: 16px;
              color: ${theme.text};
            `,
          }}
        />
      </ScrollView>

      {/* Helper Info */}
      <View style={[styles.helperBar, { backgroundColor: theme.backgroundSecondary }]}>
        <Ionicons name="information-circle-outline" size={16} color={theme.textSecondary} />
        <Text style={[styles.helperText, { color: theme.textSecondary }]}>
          Notes are auto-saved every 30 seconds
        </Text>
      </View>
    </KeyboardAvoidingView>
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
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: '600',
  },
  saveButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 8,
  },
  saveButtonText: {
    fontSize: 14,
    fontWeight: '600',
  },
  toolbar: {
    borderBottomWidth: 1,
  },
  editorContainer: {
    flex: 1,
  },
  editor: {
    flex: 1,
    minHeight: 400,
  },
  helperBar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  helperText: {
    fontSize: 12,
  },
});

export default NotesTab;
