/**
 * React hooks for task management
 */
import { useEffect, useState, useCallback, useRef } from 'react';
import { taskService } from '../services/taskService';
import type { Task } from '../services/taskService';

/**
 * Hook to track a specific task
 */
export function useTask(taskId: string | null) {
  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!taskId) {
      setTask(null);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    // Fetch initial task status
    taskService
      .getTaskStatus(taskId)
      .then((task) => {
        setTask(task);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });

    // Subscribe to real-time updates
    const unsubscribe = taskService.subscribeToTask(taskId, (updatedTask) => {
      setTask(updatedTask);
      setLoading(false);
    });

    return unsubscribe;
  }, [taskId]);

  return { task, loading, error };
}

/**
 * Hook to track all active tasks
 */
export function useActiveTasks() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Fetch initial active tasks
    taskService.getActiveTasks().then((tasks) => {
      setTasks(tasks);
      setLoading(false);
    });

    // Subscribe to all task updates
    const unsubscribe = taskService.subscribeToAllTasks((task) => {
      setTasks((prevTasks) => {
        const index = prevTasks.findIndex((t) => t.id === task.id);

        if (index >= 0) {
          // Update existing task
          const newTasks = [...prevTasks];
          newTasks[index] = task;

          // Remove completed/failed tasks after 3 seconds
          if (
            task.status === 'completed' ||
            task.status === 'failed' ||
            task.status === 'cancelled'
          ) {
            setTimeout(() => {
              setTasks((current) =>
                current.filter((t) => t.id !== task.id)
              );
            }, 3000);
          }

          return newTasks;
        } else if (
          task.status === 'queued' ||
          task.status === 'running'
        ) {
          // Add new active task
          return [...prevTasks, task];
        }

        return prevTasks;
      });
    });

    return unsubscribe;
  }, []);

  return { tasks, loading };
}

/**
 * Hook to poll a task until completion
 */
export function useTaskPolling(taskId: string | null, enabled = true) {
  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollingRef = useRef<boolean>(false);

  useEffect(() => {
    if (!taskId || !enabled || pollingRef.current) {
      return;
    }

    pollingRef.current = true;
    setLoading(true);
    setError(null);

    taskService
      .pollTaskUntilComplete(taskId, (updatedTask) => {
        setTask(updatedTask);
      })
      .then((completedTask) => {
        setTask(completedTask);
        setLoading(false);
        pollingRef.current = false;
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
        pollingRef.current = false;
      });

    return () => {
      pollingRef.current = false;
    };
  }, [taskId, enabled]);

  return { task, loading, error };
}

/**
 * Hook to connect to WebSocket on mount
 */
export function useTaskWebSocket() {
  useEffect(() => {
    const token = localStorage.getItem('token');
    if (token) {
      taskService.connect(token);
    }

    return () => {
      taskService.disconnect();
    };
  }, []);
}
