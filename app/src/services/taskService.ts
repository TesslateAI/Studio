/**
 * Task Service
 * Manages background task tracking and WebSocket connections
 */

export interface TaskProgress {
  current: number;
  total: number;
  percentage: number;
  message: string;
}

export type TaskStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface Task {
  id: string;
  user_id: number;
  type: string;
  status: TaskStatus;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  progress: TaskProgress;
  result: any | null;
  error: string | null;
  logs: string[];
  metadata: Record<string, any>;
}

export interface TaskUpdate {
  type: 'task_update';
  task: Task;
}

export interface Notification {
  type: 'notification';
  notification: {
    title: string;
    message: string;
    type: 'info' | 'success' | 'warning' | 'error';
    timestamp: number;
  };
}

type TaskCallback = (task: Task) => void;
type NotificationCallback = (notification: Notification['notification']) => void;

class TaskService {
  private ws: WebSocket | null = null;
  private reconnectTimeout: NodeJS.Timeout | null = null;
  private pingInterval: NodeJS.Timeout | null = null;
  private taskCallbacks: Map<string, TaskCallback[]> = new Map();
  private globalTaskCallbacks: TaskCallback[] = [];
  private notificationCallbacks: NotificationCallback[] = [];
  private isConnecting = false;

  /**
   * Connect to WebSocket for real-time task updates
   */
  connect(token: string): void {
    if (this.ws?.readyState === WebSocket.OPEN || this.isConnecting) {
      return;
    }

    this.isConnecting = true;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/tasks/ws`;

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        console.log('[TaskService] WebSocket connected');
        this.isConnecting = false;

        // Send authentication
        this.ws?.send(JSON.stringify({ token: `Bearer ${token}` }));

        // Clear existing ping interval to prevent memory leak
        if (this.pingInterval) {
          clearInterval(this.pingInterval);
          this.pingInterval = null;
        }

        // Send ping every 30 seconds to keep connection alive
        this.pingInterval = setInterval(() => {
          if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type: 'ping' }));
          }
        }, 30000);
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          if (data.type === 'task_update') {
            this.handleTaskUpdate(data as TaskUpdate);
          } else if (data.type === 'notification') {
            this.handleNotification(data as Notification);
          }
        } catch (error) {
          console.error('[TaskService] Failed to parse message:', error);
        }
      };

      this.ws.onclose = () => {
        console.log('[TaskService] WebSocket disconnected');
        this.isConnecting = false;
        this.ws = null;

        // Clear ping interval on disconnect
        if (this.pingInterval) {
          clearInterval(this.pingInterval);
          this.pingInterval = null;
        }

        // Reconnect after 5 seconds
        this.reconnectTimeout = setTimeout(() => {
          console.log('[TaskService] Attempting to reconnect...');
          this.connect(token);
        }, 5000);
      };

      this.ws.onerror = (error) => {
        console.error('[TaskService] WebSocket error:', error);
        this.isConnecting = false;
      };
    } catch (error) {
      console.error('[TaskService] Failed to connect WebSocket:', error);
      this.isConnecting = false;
    }
  }

  /**
   * Disconnect WebSocket
   */
  disconnect(): void {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  /**
   * Subscribe to task updates
   */
  subscribeToTask(taskId: string, callback: TaskCallback): () => void {
    if (!this.taskCallbacks.has(taskId)) {
      this.taskCallbacks.set(taskId, []);
    }
    this.taskCallbacks.get(taskId)!.push(callback);

    // Return unsubscribe function
    return () => {
      const callbacks = this.taskCallbacks.get(taskId);
      if (callbacks) {
        const index = callbacks.indexOf(callback);
        if (index > -1) {
          callbacks.splice(index, 1);
        }
      }
    };
  }

  /**
   * Subscribe to all task updates
   */
  subscribeToAllTasks(callback: TaskCallback): () => void {
    this.globalTaskCallbacks.push(callback);

    return () => {
      const index = this.globalTaskCallbacks.indexOf(callback);
      if (index > -1) {
        this.globalTaskCallbacks.splice(index, 1);
      }
    };
  }

  /**
   * Subscribe to notifications
   */
  subscribeToNotifications(callback: NotificationCallback): () => void {
    this.notificationCallbacks.push(callback);

    return () => {
      const index = this.notificationCallbacks.indexOf(callback);
      if (index > -1) {
        this.notificationCallbacks.splice(index, 1);
      }
    };
  }

  /**
   * Get task status from API
   */
  async getTaskStatus(taskId: string): Promise<Task> {
    const token = localStorage.getItem('token');
    const response = await fetch(`/api/tasks/${taskId}/status`, {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });

    if (!response.ok) {
      throw new Error('Failed to fetch task status');
    }

    return response.json();
  }

  /**
   * Get all active tasks
   */
  async getActiveTasks(): Promise<Task[]> {
    const token = localStorage.getItem('token');
    const response = await fetch('/api/tasks/user/active', {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });

    if (!response.ok) {
      throw new Error('Failed to fetch active tasks');
    }

    return response.json();
  }

  /**
   * Poll task status until completion with timeout and max retries
   */
  async pollTaskUntilComplete(
    taskId: string,
    onUpdate?: (task: Task) => void,
    interval = 1000,
    maxRetries = 300,
    timeout = 300000
  ): Promise<Task> {
    return new Promise((resolve, reject) => {
      let retryCount = 0;
      const startTime = Date.now();

      const poll = async () => {
        try {
          // Check timeout
          if (Date.now() - startTime > timeout) {
            reject(
              new Error(
                `Task polling timeout after ${timeout}ms for task ${taskId}`
              )
            );
            return;
          }

          // Check max retries
          if (retryCount >= maxRetries) {
            reject(
              new Error(
                `Task polling exceeded max retries (${maxRetries}) for task ${taskId}`
              )
            );
            return;
          }

          retryCount++;
          const task = await this.getTaskStatus(taskId);

          if (onUpdate) {
            onUpdate(task);
          }

          if (task.status === 'completed') {
            resolve(task);
          } else if (task.status === 'failed' || task.status === 'cancelled') {
            reject(new Error(task.error || 'Task failed'));
          } else {
            setTimeout(poll, interval);
          }
        } catch (error) {
          reject(error);
        }
      };

      poll();
    });
  }

  private handleTaskUpdate(data: TaskUpdate): void {
    const { task } = data;

    // Call task-specific callbacks
    const callbacks = this.taskCallbacks.get(task.id);
    if (callbacks) {
      callbacks.forEach((callback) => callback(task));
    }

    // Call global callbacks
    this.globalTaskCallbacks.forEach((callback) => callback(task));
  }

  private handleNotification(data: Notification): void {
    this.notificationCallbacks.forEach((callback) =>
      callback(data.notification)
    );
  }
}

// Singleton instance
export const taskService = new TaskService();
