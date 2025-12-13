/**
 * Task Progress Component
 * Shows progress for background tasks
 */
import React from 'react';
import { useTask } from '../../hooks/useTask';
import type { Task } from '../../services/taskService';

interface TaskProgressProps {
  taskId: string;
  onComplete?: (task: Task) => void;
  onError?: (error: string) => void;
}

export function TaskProgress({ taskId, onComplete, onError }: TaskProgressProps) {
  const { task, loading, error } = useTask(taskId);

  React.useEffect(() => {
    if (task?.status === 'completed' && onComplete) {
      onComplete(task);
    }
  }, [task?.status, onComplete, task]);

  React.useEffect(() => {
    if (task?.status === 'failed' && onError) {
      onError(task.error || 'Task failed');
    }
  }, [task?.status, onError, task]);

  React.useEffect(() => {
    if (error && onError) {
      onError(error);
    }
  }, [error, onError]);

  if (loading || !task) {
    return (
      <div className="flex items-center gap-2">
        <div className="animate-spin rounded-full h-4 w-4 border-2 border-blue-500 border-t-transparent" />
        <span className="text-sm text-gray-600">Loading...</span>
      </div>
    );
  }

  const statusColors = {
    queued: 'text-gray-500',
    running: 'text-blue-500',
    completed: 'text-green-500',
    failed: 'text-red-500',
    cancelled: 'text-orange-500',
  };

  const statusIcons = {
    queued: '⏳',
    running: '⚙️',
    completed: '✓',
    failed: '✕',
    cancelled: '⊘',
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-lg">{statusIcons[task.status]}</span>
        <span className={`font-medium ${statusColors[task.status]}`}>
          {task.status.charAt(0).toUpperCase() + task.status.slice(1)}
        </span>
      </div>

      {task.status === 'running' && (
        <div className="space-y-1">
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className="bg-blue-500 h-2 rounded-full transition-all duration-300"
              style={{ width: `${task.progress.percentage}%` }}
            />
          </div>
          <div className="text-xs text-gray-600">{task.progress.message}</div>
          <div className="text-xs text-gray-500">
            {task.progress.percentage}% complete
          </div>
        </div>
      )}

      {task.status === 'failed' && task.error && (
        <div className="text-sm text-red-600 bg-red-50 p-2 rounded">
          {task.error}
        </div>
      )}

      {task.status === 'completed' && task.result && (
        <div className="text-sm text-green-600">
          {typeof task.result === 'string' ? task.result : 'Completed successfully'}
        </div>
      )}
    </div>
  );
}

/**
 * Inline task progress indicator (minimal)
 */
export function InlineTaskProgress({ taskId }: { taskId: string }) {
  const { task } = useTask(taskId);

  if (!task) return null;

  if (task.status === 'completed') {
    return <span className="text-green-500 text-sm">✓ Complete</span>;
  }

  if (task.status === 'failed') {
    return <span className="text-red-500 text-sm">✕ Failed</span>;
  }

  if (task.status === 'running') {
    return (
      <span className="text-blue-500 text-sm flex items-center gap-1">
        <div className="animate-spin rounded-full h-3 w-3 border-2 border-blue-500 border-t-transparent" />
        {task.progress.percentage}%
      </span>
    );
  }

  return <span className="text-gray-500 text-sm">Queued...</span>;
}
