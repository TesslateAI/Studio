import { useState, useEffect } from 'react';
import {
  Plus,
  MagnifyingGlass,
  X,
  DotsThreeVertical,
  Calendar,
  User,
  Tag,
  Clock,
  Trash,
  PencilSimple,
  ArrowsDownUp,
  Funnel,
  ChatCircle
} from '@phosphor-icons/react';
import { DragDropContext, Droppable, Draggable, type DropResult } from '@hello-pangea/dnd';
import api from '../../lib/api';
import toast from 'react-hot-toast';

interface KanbanPanelProps {
  projectId: string;
}

interface Column {
  id: string;
  name: string;
  description?: string;
  position: number;
  color?: string;
  icon?: string;
  is_backlog: boolean;
  is_completed: boolean;
  task_limit?: number;
  tasks: Task[];
}

interface Task {
  id: string;
  column_id: string;
  title: string;
  description?: string;
  position: number;
  priority?: 'low' | 'medium' | 'high' | 'critical';
  status?: string;
  task_type?: 'feature' | 'bug' | 'task' | 'epic';
  tags?: string[];
  assignee?: {
    id: string;
    name: string;
    username: string;
  };
  reporter?: {
    id: string;
    name: string;
    username: string;
  };
  estimate_hours?: number;
  spent_hours?: number;
  due_date?: string;
  started_at?: string;
  completed_at?: string;
  created_at: string;
  updated_at: string;
}

interface TaskDetails extends Task {
  attachments?: any[];
  custom_fields?: any;
  comments: Comment[];
}

interface Comment {
  id: string;
  content: string;
  user: {
    id: string;
    name: string;
    username: string;
  };
  created_at: string;
  updated_at: string;
}

const API_BASE = import.meta.env.VITE_API_URL || '';

const priorityColors = {
  low: 'text-blue-400',
  medium: 'text-yellow-400',
  high: 'text-[var(--primary)]',
  critical: 'text-red-400'
};

const taskTypeIcons = {
  feature: '✨',
  bug: '🐛',
  task: '📋',
  epic: '🎯'
};

export function KanbanPanel({ projectId }: KanbanPanelProps) {
  const [board, setBoard] = useState<{ columns: Column[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const [filterPriority, setFilterPriority] = useState<string>('');
  const [filterType, setFilterType] = useState<string>('');
  const [showNewTaskModal, setShowNewTaskModal] = useState(false);
  const [newTaskColumnId, setNewTaskColumnId] = useState<string | null>(null);
  const [selectedTask, setSelectedTask] = useState<TaskDetails | null>(null);
  const [showTaskDetails, setShowTaskDetails] = useState(false);
  const [newComment, setNewComment] = useState('');

  const [newTask, setNewTask] = useState({
    title: '',
    description: '',
    priority: 'medium' as const,
    task_type: 'task' as const,
    tags: [] as string[],
    estimate_hours: undefined as number | undefined
  });

  useEffect(() => {
    loadBoard();
  }, [projectId]);

  const loadBoard = async () => {
    try {
      const response = await api.get(`/api/kanban/projects/${projectId}/board`);
      setBoard(response.data);
    } catch (error: any) {
      console.error('Failed to load board:', error);
      toast.error(error.response?.data?.detail || 'Failed to load kanban board');
    } finally {
      setLoading(false);
    }
  };

  const loadTaskDetails = async (taskId: string) => {
    try {
      const response = await api.get(`/api/kanban/tasks/${taskId}`);
      setSelectedTask(response.data);
      setShowTaskDetails(true);
    } catch (error: any) {
      toast.error('Failed to load task details');
    }
  };

  const createTask = async () => {
    if (!newTask.title.trim() || !newTaskColumnId) return;

    try {
      await api.post(
        `/api/kanban/projects/${projectId}/tasks`,
        {
          column_id: newTaskColumnId,
          ...newTask
        }
      );
      toast.success('Task created successfully');
      setShowNewTaskModal(false);
      setNewTask({
        title: '',
        description: '',
        priority: 'medium',
        task_type: 'task',
        tags: [],
        estimate_hours: undefined
      });
      await loadBoard();
    } catch (error: any) {
      toast.error(error.response?.data?.detail || 'Failed to create task');
    }
  };

  const updateTask = async (taskId: string, updates: Partial<Task>) => {
    try {
      await api.patch(
        `/api/kanban/tasks/${taskId}`,
        updates
      );
      toast.success('Task updated');
      await loadBoard();
      if (selectedTask?.id === taskId) {
        await loadTaskDetails(taskId);
      }
    } catch (error: any) {
      toast.error('Failed to update task');
    }
  };

  const deleteTask = async (taskId: string) => {
    if (!confirm('Are you sure you want to delete this task?')) return;

    try {
      await api.delete(`/api/kanban/tasks/${taskId}`);
      toast.success('Task deleted');
      setShowTaskDetails(false);
      await loadBoard();
    } catch (error: any) {
      toast.error('Failed to delete task');
    }
  };

  const addComment = async () => {
    if (!selectedTask || !newComment.trim()) return;

    try {
      await api.post(
        `/api/kanban/tasks/${selectedTask.id}/comments`,
        { content: newComment }
      );
      setNewComment('');
      await loadTaskDetails(selectedTask.id);
    } catch (error: any) {
      toast.error('Failed to add comment');
    }
  };

  const handleDragEnd = async (result: DropResult) => {
    if (!result.destination || !board) return;

    const { source, destination, draggableId } = result;
    const taskId = draggableId.replace('task-', '');

    // Same column reorder
    if (source.droppableId === destination.droppableId) {
      const columnId = source.droppableId.replace('column-', '');
      const column = board.columns.find(c => c.id === columnId);
      if (!column) return;

      const newTasks = Array.from(column.tasks);
      const [movedTask] = newTasks.splice(source.index, 1);
      newTasks.splice(destination.index, 0, movedTask);

      // Update local state optimistically
      setBoard({
        ...board,
        columns: board.columns.map(col =>
          col.id === columnId
            ? { ...col, tasks: newTasks.map((t, idx) => ({ ...t, position: idx })) }
            : col
        )
      });
    } else {
      // Move to different column
      const sourceColumnId = source.droppableId.replace('column-', '');
      const destColumnId = destination.droppableId.replace('column-', '');

      const sourceColumn = board.columns.find(c => c.id === sourceColumnId);
      const destColumn = board.columns.find(c => c.id === destColumnId);
      if (!sourceColumn || !destColumn) return;

      const sourceTasks = Array.from(sourceColumn.tasks);
      const destTasks = Array.from(destColumn.tasks);
      const [movedTask] = sourceTasks.splice(source.index, 1);
      destTasks.splice(destination.index, 0, { ...movedTask, column_id: destColumnId });

      // Update local state optimistically
      setBoard({
        ...board,
        columns: board.columns.map(col => {
          if (col.id === sourceColumnId) {
            return { ...col, tasks: sourceTasks.map((t, idx) => ({ ...t, position: idx })) };
          }
          if (col.id === destColumnId) {
            return { ...col, tasks: destTasks.map((t, idx) => ({ ...t, position: idx, column_id: destColumnId })) };
          }
          return col;
        })
      });
    }

    // Send to backend
    try {
      await api.post(
        `/api/kanban/tasks/${taskId}/move`,
        {
          column_id: destination.droppableId.replace('column-', ''),
          position: destination.index
        }
      );
    } catch (error: any) {
      toast.error('Failed to move task');
      await loadBoard(); // Reload on error
    }
  };

  const filteredColumns = board?.columns.map(col => ({
    ...col,
    tasks: col.tasks.filter(task => {
      const matchesSearch = searchQuery === '' ||
        task.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        task.description?.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesPriority = !filterPriority || task.priority === filterPriority;
      const matchesType = !filterType || task.task_type === filterType;
      return matchesSearch && matchesPriority && matchesType;
    })
  }));

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-[var(--text)]/60">Loading kanban board...</div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-[var(--background)]">
      {/* Header */}
      <div className="flex-shrink-0 p-4 border-b border-[var(--text)]/15 bg-[var(--surface)]/50 backdrop-blur-sm">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-[var(--text)]">Kanban Board</h2>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowFilters(!showFilters)}
              className={`p-2 rounded-lg transition-colors ${
                showFilters
                  ? 'bg-[rgba(var(--primary-rgb),0.2)] text-[var(--primary)]'
                  : 'hover:bg-white/10 text-[var(--text)]/60'
              }`}
              title="Filters"
            >
              <Funnel size={20} weight="bold" />
            </button>
          </div>
        </div>

        {/* Search Bar */}
        <div className="relative mb-3">
          <MagnifyingGlass
            size={18}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text)]/40"
            weight="bold"
          />
          <input
            type="text"
            placeholder="Search tasks..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2 bg-[var(--background)] border border-[var(--text)]/20 rounded-lg text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:border-[var(--primary)]"
          />
        </div>

        {/* Filters */}
        {showFilters && (
          <div className="flex gap-3 flex-wrap">
            <select
              value={filterPriority}
              onChange={(e) => setFilterPriority(e.target.value)}
              className="px-3 py-1.5 bg-[var(--background)] border border-[var(--text)]/20 rounded-lg text-sm text-[var(--text)] focus:outline-none focus:border-[var(--primary)] [&>option]:bg-[var(--surface)] [&>option]:text-[var(--text)]"
            >
              <option value="">All Priorities</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
            <select
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
              className="px-3 py-1.5 bg-[var(--background)] border border-[var(--text)]/20 rounded-lg text-sm text-[var(--text)] focus:outline-none focus:border-[var(--primary)] [&>option]:bg-[var(--surface)] [&>option]:text-[var(--text)]"
            >
              <option value="">All Types</option>
              <option value="feature">Feature</option>
              <option value="bug">Bug</option>
              <option value="task">Task</option>
              <option value="epic">Epic</option>
            </select>
          </div>
        )}
      </div>

      {/* Kanban Board */}
      <div className="flex-1 overflow-auto">
        <DragDropContext onDragEnd={handleDragEnd}>
          <div className="p-4 flex gap-4 items-start" style={{ minWidth: 'max-content' }}>
            {filteredColumns?.map((column) => (
              <div
                key={column.id}
                className="flex-shrink-0 w-80 flex flex-col bg-[var(--surface)]/30 rounded-lg border border-[var(--text)]/20"
              >
                {/* Column Header */}
                <div className="flex-shrink-0 p-4 border-b border-[var(--text)]/15">
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      {column.icon && <span className="text-lg">{column.icon}</span>}
                      <h3 className="font-semibold text-[var(--text)]">{column.name}</h3>
                      <span className="text-xs text-[var(--text)]/50 bg-white/5 px-2 py-0.5 rounded-full">
                        {column.tasks.length}
                      </span>
                    </div>
                    <button
                      onClick={() => {
                        setNewTaskColumnId(column.id);
                        setShowNewTaskModal(true);
                      }}
                      className="p-1 hover:bg-white/10 rounded transition-colors text-[var(--text)]/60 hover:text-[var(--primary)]"
                      title="Add task"
                    >
                      <Plus size={18} weight="bold" />
                    </button>
                  </div>
                  {column.description && (
                    <p className="text-xs text-[var(--text)]/50">{column.description}</p>
                  )}
                </div>

                {/* Tasks */}
                <Droppable droppableId={`column-${column.id}`}>
                  {(provided, snapshot) => (
                    <div
                      ref={provided.innerRef}
                      {...provided.droppableProps}
                      className={`p-3 space-y-2 min-h-[200px] ${
                        snapshot.isDraggingOver ? 'bg-[rgba(var(--primary-rgb),0.05)]' : ''
                      }`}
                    >
                      {column.tasks.map((task, index) => (
                        <Draggable key={task.id} draggableId={`task-${task.id}`} index={index}>
                          {(provided, snapshot) => (
                            <div
                              ref={provided.innerRef}
                              {...provided.draggableProps}
                              {...provided.dragHandleProps}
                              onClick={() => loadTaskDetails(task.id)}
                              className={`p-3 bg-[var(--background)] border border-[var(--text)]/20 rounded-lg cursor-pointer transition-all hover:border-[rgba(var(--primary-rgb),0.5)] hover:shadow-lg ${
                                snapshot.isDragging ? 'shadow-2xl border-[var(--primary)]' : ''
                              }`}
                            >
                              {/* Task Header */}
                              <div className="flex items-start justify-between gap-2 mb-2">
                                <h4 className="text-sm font-medium text-[var(--text)] flex-1 line-clamp-2">
                                  {task.title}
                                </h4>
                                {task.task_type && (
                                  <span className="text-base" title={task.task_type}>
                                    {taskTypeIcons[task.task_type]}
                                  </span>
                                )}
                              </div>

                              {/* Task Metadata */}
                              <div className="flex flex-wrap gap-2 items-center text-xs">
                                {task.priority && (
                                  <span className={`${priorityColors[task.priority]} flex items-center gap-1`}>
                                    <ArrowsDownUp size={12} weight="bold" />
                                    {task.priority}
                                  </span>
                                )}
                                {task.tags && task.tags.length > 0 && (
                                  <div className="flex gap-1">
                                    {task.tags.slice(0, 2).map((tag, idx) => (
                                      <span
                                        key={idx}
                                        className="px-1.5 py-0.5 bg-[rgba(var(--primary-rgb),0.2)] text-[var(--primary)] rounded text-[10px]"
                                      >
                                        {tag}
                                      </span>
                                    ))}
                                    {task.tags.length > 2 && (
                                      <span className="text-[var(--text)]/40">+{task.tags.length - 2}</span>
                                    )}
                                  </div>
                                )}
                                {task.assignee && (
                                  <span className="text-[var(--text)]/60 flex items-center gap-1">
                                    <User size={12} weight="bold" />
                                    {task.assignee.name}
                                  </span>
                                )}
                                {task.due_date && (
                                  <span className="text-[var(--text)]/60 flex items-center gap-1">
                                    <Calendar size={12} weight="bold" />
                                    {new Date(task.due_date).toLocaleDateString()}
                                  </span>
                                )}
                              </div>
                            </div>
                          )}
                        </Draggable>
                      ))}
                      {provided.placeholder}
                    </div>
                  )}
                </Droppable>
              </div>
            ))}
          </div>
        </DragDropContext>
      </div>

      {/* New Task Modal */}
      {showNewTaskModal && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-[300] p-4">
          <div className="bg-[var(--surface)] border border-white/20 rounded-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
            <div className="p-6 border-b border-[var(--text)]/15 flex items-center justify-between">
              <h3 className="text-xl font-bold text-[var(--text)]">Create New Task</h3>
              <button
                onClick={() => setShowNewTaskModal(false)}
                className="p-2 hover:bg-white/10 rounded-lg transition-colors text-[var(--text)]/60"
              >
                <X size={20} weight="bold" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-[var(--text)] mb-2">Title *</label>
                <input
                  type="text"
                  value={newTask.title}
                  onChange={(e) => setNewTask({ ...newTask, title: e.target.value })}
                  className="w-full px-4 py-2 bg-[var(--background)] border border-[var(--text)]/20 rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]"
                  placeholder="Task title..."
                  autoFocus
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-[var(--text)] mb-2">Description</label>
                <textarea
                  value={newTask.description}
                  onChange={(e) => setNewTask({ ...newTask, description: e.target.value })}
                  rows={4}
                  className="w-full px-4 py-2 bg-[var(--background)] border border-[var(--text)]/20 rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)] resize-none"
                  placeholder="Add details..."
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-[var(--text)] mb-2">Priority</label>
                  <select
                    value={newTask.priority}
                    onChange={(e) => setNewTask({ ...newTask, priority: e.target.value as any })}
                    className="w-full px-4 py-2 bg-[var(--background)] border border-[var(--text)]/20 rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)] [&>option]:bg-[var(--surface)] [&>option]:text-[var(--text)]"
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                    <option value="critical">Critical</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-[var(--text)] mb-2">Type</label>
                  <select
                    value={newTask.task_type}
                    onChange={(e) => setNewTask({ ...newTask, task_type: e.target.value as any })}
                    className="w-full px-4 py-2 bg-[var(--background)] border border-[var(--text)]/20 rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)] [&>option]:bg-[var(--surface)] [&>option]:text-[var(--text)]"
                  >
                    <option value="task">Task</option>
                    <option value="feature">Feature</option>
                    <option value="bug">Bug</option>
                    <option value="epic">Epic</option>
                  </select>
                </div>
              </div>
              <div className="flex gap-4 pt-4">
                <button
                  onClick={createTask}
                  disabled={!newTask.title.trim()}
                  className="flex-1 px-4 py-2 bg-[var(--primary)] hover:bg-[var(--primary-hover)] disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg font-medium transition-colors"
                >
                  Create Task
                </button>
                <button
                  onClick={() => setShowNewTaskModal(false)}
                  className="px-4 py-2 bg-white/5 hover:bg-white/10 text-[var(--text)] rounded-lg font-medium transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Task Details Modal */}
      {showTaskDetails && selectedTask && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-[300] p-4">
          <div className="bg-[var(--surface)] border border-white/20 rounded-xl max-w-4xl w-full max-h-[90vh] overflow-y-auto">
            <div className="p-6 border-b border-[var(--text)]/15 flex items-center justify-between">
              <div className="flex items-center gap-3">
                {selectedTask.task_type && (
                  <span className="text-2xl">{taskTypeIcons[selectedTask.task_type]}</span>
                )}
                <h3 className="text-xl font-bold text-[var(--text)]">{selectedTask.title}</h3>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => deleteTask(selectedTask.id)}
                  className="p-2 hover:bg-red-500/20 text-red-400 rounded-lg transition-colors"
                  title="Delete task"
                >
                  <Trash size={20} weight="bold" />
                </button>
                <button
                  onClick={() => setShowTaskDetails(false)}
                  className="p-2 hover:bg-white/10 rounded-lg transition-colors text-[var(--text)]/60"
                >
                  <X size={20} weight="bold" />
                </button>
              </div>
            </div>
            <div className="p-6 space-y-6">
              {/* Description */}
              <div>
                <label className="block text-sm font-medium text-[var(--text)] mb-2">Description</label>
                <p className="text-[var(--text)]/80 whitespace-pre-wrap">
                  {selectedTask.description || 'No description'}
                </p>
              </div>

              {/* Metadata Grid */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-[var(--text)] mb-2">Priority</label>
                  <select
                    value={selectedTask.priority || 'medium'}
                    onChange={(e) => updateTask(selectedTask.id, { priority: e.target.value as any })}
                    className="w-full px-3 py-2 bg-[var(--background)] border border-[var(--text)]/20 rounded-lg text-[var(--text)] text-sm focus:outline-none focus:border-[var(--primary)] [&>option]:bg-[var(--surface)] [&>option]:text-[var(--text)]"
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                    <option value="critical">Critical</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-[var(--text)] mb-2">Type</label>
                  <select
                    value={selectedTask.task_type || 'task'}
                    onChange={(e) => updateTask(selectedTask.id, { task_type: e.target.value as any })}
                    className="w-full px-3 py-2 bg-[var(--background)] border border-[var(--text)]/20 rounded-lg text-[var(--text)] text-sm focus:outline-none focus:border-[var(--primary)] [&>option]:bg-[var(--surface)] [&>option]:text-[var(--text)]"
                  >
                    <option value="task">Task</option>
                    <option value="feature">Feature</option>
                    <option value="bug">Bug</option>
                    <option value="epic">Epic</option>
                  </select>
                </div>
                {selectedTask.estimate_hours !== undefined && (
                  <div>
                    <label className="block text-sm font-medium text-[var(--text)] mb-2">Estimate</label>
                    <div className="flex items-center gap-2 text-sm text-[var(--text)]/80">
                      <Clock size={16} weight="bold" />
                      {selectedTask.estimate_hours}h
                    </div>
                  </div>
                )}
                {selectedTask.assignee && (
                  <div>
                    <label className="block text-sm font-medium text-[var(--text)] mb-2">Assignee</label>
                    <div className="flex items-center gap-2 text-sm text-[var(--text)]/80">
                      <User size={16} weight="bold" />
                      {selectedTask.assignee.name}
                    </div>
                  </div>
                )}
              </div>

              {/* Tags */}
              {selectedTask.tags && selectedTask.tags.length > 0 && (
                <div>
                  <label className="block text-sm font-medium text-[var(--text)] mb-2">Tags</label>
                  <div className="flex flex-wrap gap-2">
                    {selectedTask.tags.map((tag, idx) => (
                      <span
                        key={idx}
                        className="px-2 py-1 bg-[rgba(var(--primary-rgb),0.2)] text-[var(--primary)] rounded text-sm"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Comments */}
              <div>
                <label className="block text-sm font-medium text-[var(--text)] mb-3">Comments</label>
                <div className="space-y-3 mb-4">
                  {selectedTask.comments.map((comment) => (
                    <div key={comment.id} className="p-3 bg-[var(--background)] rounded-lg border border-[var(--text)]/20">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-sm font-medium text-[var(--text)]">{comment.user.name}</span>
                        <span className="text-xs text-[var(--text)]/40">
                          {new Date(comment.created_at).toLocaleString()}
                        </span>
                      </div>
                      <p className="text-sm text-[var(--text)]/80">{comment.content}</p>
                    </div>
                  ))}
                </div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={newComment}
                    onChange={(e) => setNewComment(e.target.value)}
                    onKeyPress={(e) => e.key === 'Enter' && addComment()}
                    placeholder="Add a comment..."
                    className="flex-1 px-4 py-2 bg-[var(--background)] border border-[var(--text)]/20 rounded-lg text-[var(--text)] text-sm focus:outline-none focus:border-[var(--primary)]"
                  />
                  <button
                    onClick={addComment}
                    disabled={!newComment.trim()}
                    className="px-4 py-2 bg-[var(--primary)] hover:bg-[var(--primary-hover)] disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg font-medium transition-colors"
                  >
                    <ChatCircle size={18} weight="bold" />
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
