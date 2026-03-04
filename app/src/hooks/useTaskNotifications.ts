/**
 * Hook to handle task notifications using react-hot-toast
 */
import { useEffect } from 'react';
import toast from 'react-hot-toast';
import { taskService } from '../services/taskService';
import type { Task } from '../services/taskService';
import { useTaskWebSocket } from './useTask';

export function useTaskNotifications() {
  // Connect to WebSocket
  useTaskWebSocket();

  useEffect(() => {
    // Subscribe to all task updates
    const unsubscribe = taskService.subscribeToAllTasks((task: Task) => {
      // Show notification when task completes or fails
      if (task.status === 'completed') {
        const taskName = getTaskDisplayName(task);
        toast.success(`${taskName} completed successfully`, {
          duration: 4000,
        });
      } else if (task.status === 'failed') {
        const taskName = getTaskDisplayName(task);
        toast.error(`${taskName} failed: ${task.error || 'Unknown error'}`, {
          duration: 6000,
        });
      }
    });

    // Subscribe to backend notifications
    const unsubscribeNotifications = taskService.subscribeToNotifications(
      (notification) => {
        switch (notification.type) {
          case 'success':
            toast.success(notification.message, {
              duration: 4000,
            });
            break;
          case 'error':
            toast.error(notification.message, {
              duration: 6000,
            });
            break;
          case 'warning':
            toast(notification.message, {
              duration: 5000,
              icon: '⚠️',
            });
            break;
          default:
            toast(notification.message, {
              duration: 4000,
            });
        }
      }
    );

    return () => {
      unsubscribe();
      unsubscribeNotifications();
    };
  }, []);
}

function getTaskDisplayName(task: Task): string {
  switch (task.type) {
    case 'project_creation':
      return `Project "${task.metadata.project_name || 'creation'}"`;
    case 'project_deletion':
      return `Project "${task.metadata.project_name || 'deletion'}"`;
    case 'container_startup':
      return `Container for "${task.metadata.project_name || task.metadata.project_slug}"`;
    default:
      return task.type.replace(/_/g, ' ');
  }
}
