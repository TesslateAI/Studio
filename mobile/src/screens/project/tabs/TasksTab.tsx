import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  TextInput,
  Modal,
  ScrollView,
} from 'react-native';
import { useRoute } from '@react-navigation/native';
import DraggableFlatList, {
  RenderItemParams,
  ScaleDecorator,
} from 'react-native-draggable-flatlist';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '../../../theme/ThemeContext';
import Toast from 'react-native-toast-message';

interface Task {
  id: string;
  title: string;
  description?: string;
  status: 'todo' | 'in_progress' | 'done';
  created_at: string;
}

const TasksTab: React.FC = () => {
  const route = useRoute();
  const { theme } = useTheme();
  const { projectSlug } = route.params as { projectSlug: string };

  const [tasks, setTasks] = useState<Task[]>([
    {
      id: '1',
      title: 'Setup project structure',
      description: 'Initialize the base project with necessary files',
      status: 'done',
      created_at: new Date().toISOString(),
    },
    {
      id: '2',
      title: 'Implement authentication',
      description: 'Add login and registration functionality',
      status: 'in_progress',
      created_at: new Date().toISOString(),
    },
    {
      id: '3',
      title: 'Create dashboard',
      description: 'Build the main dashboard UI',
      status: 'todo',
      created_at: new Date().toISOString(),
    },
  ]);

  const [selectedColumn, setSelectedColumn] = useState<'todo' | 'in_progress' | 'done'>('todo');
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [newTaskTitle, setNewTaskTitle] = useState('');
  const [newTaskDescription, setNewTaskDescription] = useState('');

  const columns = [
    { id: 'todo', title: 'To Do', color: theme.info },
    { id: 'in_progress', title: 'In Progress', color: theme.warning },
    { id: 'done', title: 'Done', color: theme.success },
  ] as const;

  const getTasksByStatus = (status: Task['status']) => {
    return tasks.filter((task) => task.status === status);
  };

  const handleCreateTask = () => {
    if (!newTaskTitle.trim()) {
      Toast.show({
        type: 'error',
        text1: 'Error',
        text2: 'Please enter a task title',
      });
      return;
    }

    const newTask: Task = {
      id: Date.now().toString(),
      title: newTaskTitle.trim(),
      description: newTaskDescription.trim() || undefined,
      status: selectedColumn,
      created_at: new Date().toISOString(),
    };

    setTasks([...tasks, newTask]);
    setNewTaskTitle('');
    setNewTaskDescription('');
    setCreateModalVisible(false);

    Toast.show({
      type: 'success',
      text1: 'Success',
      text2: 'Task created',
    });
  };

  const handleDeleteTask = (taskId: string) => {
    setTasks(tasks.filter((task) => task.id !== taskId));
    Toast.show({
      type: 'success',
      text1: 'Success',
      text2: 'Task deleted',
    });
  };

  const handleMoveTask = (taskId: string, newStatus: Task['status']) => {
    setTasks(
      tasks.map((task) =>
        task.id === taskId ? { ...task, status: newStatus } : task
      )
    );
  };

  const renderTask = ({ item, drag, isActive }: RenderItemParams<Task>) => (
    <ScaleDecorator>
      <TouchableOpacity
        style={[
          styles.taskCard,
          { backgroundColor: theme.card, borderColor: theme.border },
          isActive && { opacity: 0.5 },
        ]}
        onLongPress={drag}
        disabled={isActive}
      >
        <View style={styles.taskHeader}>
          <Text style={[styles.taskTitle, { color: theme.text }]} numberOfLines={2}>
            {item.title}
          </Text>
          <TouchableOpacity onPress={() => handleDeleteTask(item.id)}>
            <Ionicons name="trash-outline" size={18} color={theme.error} />
          </TouchableOpacity>
        </View>

        {item.description && (
          <Text style={[styles.taskDescription, { color: theme.textSecondary }]} numberOfLines={3}>
            {item.description}
          </Text>
        )}

        {/* Move buttons */}
        <View style={styles.taskActions}>
          {item.status !== 'todo' && (
            <TouchableOpacity
              style={[styles.moveButton, { backgroundColor: theme.backgroundSecondary }]}
              onPress={() => handleMoveTask(item.id, item.status === 'in_progress' ? 'todo' : 'in_progress')}
            >
              <Ionicons name="arrow-back" size={14} color={theme.textSecondary} />
            </TouchableOpacity>
          )}
          {item.status !== 'done' && (
            <TouchableOpacity
              style={[styles.moveButton, { backgroundColor: theme.backgroundSecondary }]}
              onPress={() => handleMoveTask(item.id, item.status === 'todo' ? 'in_progress' : 'done')}
            >
              <Ionicons name="arrow-forward" size={14} color={theme.textSecondary} />
            </TouchableOpacity>
          )}
        </View>
      </TouchableOpacity>
    </ScaleDecorator>
  );

  return (
    <View style={[styles.container, { backgroundColor: theme.background }]}>
      {/* Column Tabs */}
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={styles.columnTabs}
        contentContainerStyle={styles.columnTabsContent}
      >
        {columns.map((column) => {
          const columnTasks = getTasksByStatus(column.id);
          return (
            <TouchableOpacity
              key={column.id}
              style={[
                styles.columnTab,
                selectedColumn === column.id && [
                  styles.activeColumnTab,
                  { backgroundColor: column.color + '20', borderColor: column.color },
                ],
              ]}
              onPress={() => setSelectedColumn(column.id)}
            >
              <Text
                style={[
                  styles.columnTabTitle,
                  { color: selectedColumn === column.id ? column.color : theme.text },
                ]}
              >
                {column.title}
              </Text>
              <View style={[styles.columnBadge, { backgroundColor: column.color }]}>
                <Text style={styles.columnBadgeText}>{columnTasks.length}</Text>
              </View>
            </TouchableOpacity>
          );
        })}
      </ScrollView>

      {/* Tasks List */}
      <DraggableFlatList
        data={getTasksByStatus(selectedColumn)}
        renderItem={renderTask}
        keyExtractor={(item) => item.id}
        onDragEnd={({ data }) => {
          // Update order within the same column
          const otherTasks = tasks.filter((task) => task.status !== selectedColumn);
          setTasks([...otherTasks, ...data]);
        }}
        contentContainerStyle={styles.tasksList}
        ListEmptyComponent={
          <View style={styles.emptyState}>
            <Ionicons name="checkmark-circle-outline" size={64} color={theme.textTertiary} />
            <Text style={[styles.emptyText, { color: theme.textSecondary }]}>
              No tasks in {columns.find((c) => c.id === selectedColumn)?.title}
            </Text>
          </View>
        }
      />

      {/* Add Task Button */}
      <TouchableOpacity
        style={[styles.fab, { backgroundColor: theme.primary }]}
        onPress={() => setCreateModalVisible(true)}
      >
        <Ionicons name="add" size={28} color="#FFFFFF" />
      </TouchableOpacity>

      {/* Create Task Modal */}
      <Modal visible={createModalVisible} animationType="slide" transparent={true}>
        <View style={styles.modalOverlay}>
          <View style={[styles.modalContent, { backgroundColor: theme.card }]}>
            <View style={styles.modalHeader}>
              <Text style={[styles.modalTitle, { color: theme.text }]}>Create Task</Text>
              <TouchableOpacity onPress={() => setCreateModalVisible(false)}>
                <Ionicons name="close" size={24} color={theme.textSecondary} />
              </TouchableOpacity>
            </View>

            <ScrollView style={styles.modalBody}>
              <View style={styles.inputGroup}>
                <Text style={[styles.label, { color: theme.text }]}>Title *</Text>
                <TextInput
                  style={[
                    styles.input,
                    { backgroundColor: theme.backgroundSecondary, borderColor: theme.border, color: theme.text },
                  ]}
                  placeholder="Task title..."
                  placeholderTextColor={theme.textTertiary}
                  value={newTaskTitle}
                  onChangeText={setNewTaskTitle}
                />
              </View>

              <View style={styles.inputGroup}>
                <Text style={[styles.label, { color: theme.text }]}>Description</Text>
                <TextInput
                  style={[
                    styles.input,
                    styles.textArea,
                    { backgroundColor: theme.backgroundSecondary, borderColor: theme.border, color: theme.text },
                  ]}
                  placeholder="Describe the task..."
                  placeholderTextColor={theme.textTertiary}
                  value={newTaskDescription}
                  onChangeText={setNewTaskDescription}
                  multiline
                  numberOfLines={4}
                />
              </View>

              <View style={styles.inputGroup}>
                <Text style={[styles.label, { color: theme.text }]}>Column</Text>
                <View style={styles.columnSelector}>
                  {columns.map((column) => (
                    <TouchableOpacity
                      key={column.id}
                      style={[
                        styles.columnOption,
                        { borderColor: theme.border },
                        selectedColumn === column.id && { backgroundColor: column.color + '20', borderColor: column.color },
                      ]}
                      onPress={() => setSelectedColumn(column.id)}
                    >
                      <Text
                        style={[
                          styles.columnOptionText,
                          { color: selectedColumn === column.id ? column.color : theme.text },
                        ]}
                      >
                        {column.title}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </View>
              </View>
            </ScrollView>

            <View style={[styles.modalFooter, { borderTopColor: theme.border }]}>
              <TouchableOpacity
                style={[styles.createButton, { backgroundColor: theme.primary }]}
                onPress={handleCreateTask}
              >
                <Text style={styles.createButtonText}>Create Task</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  columnTabs: {
    borderBottomWidth: 1,
  },
  columnTabsContent: {
    padding: 16,
    gap: 12,
  },
  columnTab: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: 20,
    gap: 8,
  },
  activeColumnTab: {
    borderWidth: 2,
  },
  columnTabTitle: {
    fontSize: 14,
    fontWeight: '600',
  },
  columnBadge: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 10,
  },
  columnBadgeText: {
    color: '#FFFFFF',
    fontSize: 12,
    fontWeight: 'bold',
  },
  tasksList: {
    padding: 16,
  },
  taskCard: {
    padding: 16,
    borderRadius: 12,
    marginBottom: 12,
    borderWidth: 1,
  },
  taskHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 8,
  },
  taskTitle: {
    flex: 1,
    fontSize: 16,
    fontWeight: '600',
    marginRight: 12,
  },
  taskDescription: {
    fontSize: 14,
    marginBottom: 12,
    lineHeight: 20,
  },
  taskActions: {
    flexDirection: 'row',
    gap: 8,
  },
  moveButton: {
    padding: 8,
    borderRadius: 6,
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
    maxHeight: '80%',
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
    maxHeight: 400,
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
  columnSelector: {
    flexDirection: 'row',
    gap: 8,
  },
  columnOption: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 8,
    borderWidth: 2,
    alignItems: 'center',
  },
  columnOptionText: {
    fontSize: 13,
    fontWeight: '600',
  },
  modalFooter: {
    padding: 20,
    borderTopWidth: 1,
  },
  createButton: {
    paddingVertical: 14,
    borderRadius: 8,
    alignItems: 'center',
  },
  createButtonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '600',
  },
});

export default TasksTab;
