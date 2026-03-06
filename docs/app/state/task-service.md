# Task Service

The Task Service is a singleton that manages background task tracking through WebSocket connections and provides subscription-based updates.

**File**: `app/src/services/taskService.ts`

## Overview

The Task Service handles:
- WebSocket connection for real-time task updates
- Task subscription management
- Polling fallback for task completion
- Notification delivery

## Type Definitions

### Task Progress

```typescript
export interface TaskProgress {
  current: number;
  total: number;
  percentage: number;
  message: string;
}
```

### Task Status

```typescript
export type TaskStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
```

### Task

```typescript
export interface Task {
  id: string;
  user_id: number;
  type: string;
  status: TaskStatus;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  progress: TaskProgress;
  result: unknown | null;
  error: string | null;
  logs: string[];
  metadata: Record<string, unknown>;
}
```

### Task Update Event

```typescript
export interface TaskUpdate {
  type: 'task_update';
  task: Task;
}
```

### Notification Event

```typescript
export interface Notification {
  type: 'notification';
  notification: {
    title: string;
    message: string;
    type: 'info' | 'success' | 'warning' | 'error';
    timestamp: number;
  };
}
```

## TaskService Class

### Properties

```typescript
class TaskService {
  private ws: WebSocket | null = null;
  private reconnectTimeout: NodeJS.Timeout | null = null;
  private pingInterval: NodeJS.Timeout | null = null;
  private taskCallbacks: Map<string, TaskCallback[]> = new Map();
  private globalTaskCallbacks: TaskCallback[] = [];
  private notificationCallbacks: NotificationCallback[] = [];
  private isConnecting = false;
}
```

### WebSocket Connection

```typescript
connect(token: string): void {
  if (this.ws?.readyState === WebSocket.OPEN || this.isConnecting) {
    return;
  }

  this.isConnecting = true;
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/api/tasks/ws`;

  this.ws = new WebSocket(wsUrl);

  this.ws.onopen = () => {
    this.isConnecting = false;
    // Send authentication
    this.ws?.send(JSON.stringify({ token: `Bearer ${token}` }));

    // Keep connection alive with pings
    this.pingInterval = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, 30000);
  };

  this.ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'task_update') {
      this.handleTaskUpdate(data);
    } else if (data.type === 'notification') {
      this.handleNotification(data);
    }
  };

  this.ws.onclose = () => {
    // Auto-reconnect after 5 seconds
    this.reconnectTimeout = setTimeout(() => {
      this.connect(token);
    }, 5000);
  };
}
```

### Disconnect

```typescript
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
```

### Task Subscriptions

```typescript
// Subscribe to specific task
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

// Subscribe to all task updates
subscribeToAllTasks(callback: TaskCallback): () => void {
  this.globalTaskCallbacks.push(callback);

  return () => {
    const index = this.globalTaskCallbacks.indexOf(callback);
    if (index > -1) {
      this.globalTaskCallbacks.splice(index, 1);
    }
  };
}

// Subscribe to notifications
subscribeToNotifications(callback: NotificationCallback): () => void {
  this.notificationCallbacks.push(callback);

  return () => {
    const index = this.notificationCallbacks.indexOf(callback);
    if (index > -1) {
      this.notificationCallbacks.splice(index, 1);
    }
  };
}
```

### API Methods

```typescript
// Get task status from API
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

// Get all active tasks
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
```

### Polling Fallback

```typescript
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
      // Timeout check
      if (Date.now() - startTime > timeout) {
        reject(new Error(`Task polling timeout after ${timeout}ms`));
        return;
      }

      // Max retries check
      if (retryCount >= maxRetries) {
        reject(new Error(`Task polling exceeded max retries (${maxRetries})`));
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
    };

    poll();
  });
}
```

## Singleton Instance

```typescript
export const taskService = new TaskService();
```

## Usage Examples

### Basic Connection

```typescript
import { taskService } from '../services/taskService';

// Connect on app mount
const token = localStorage.getItem('token');
if (token) {
  taskService.connect(token);
}

// Disconnect on unmount
taskService.disconnect();
```

### Subscribing to Task Updates

```typescript
// Subscribe to specific task
const unsubscribe = taskService.subscribeToTask(taskId, (task) => {
  console.log('Task status:', task.status);
  console.log('Progress:', task.progress.percentage + '%');

  if (task.status === 'completed') {
    console.log('Result:', task.result);
  }
});

// Cleanup
unsubscribe();
```

### Subscribing to All Tasks

```typescript
const unsubscribe = taskService.subscribeToAllTasks((task) => {
  // Handle any task update
  updateTaskList(task);
});
```

### Subscribing to Notifications

```typescript
const unsubscribe = taskService.subscribeToNotifications((notification) => {
  switch (notification.type) {
    case 'success':
      toast.success(notification.message);
      break;
    case 'error':
      toast.error(notification.message);
      break;
    case 'warning':
      toast.warning(notification.message);
      break;
    default:
      toast(notification.message);
  }
});
```

### Polling for Completion

```typescript
// Start a task
const { task_id } = await projectsApi.create(name);

// Poll until complete with progress updates
try {
  const completedTask = await taskService.pollTaskUntilComplete(
    task_id,
    (task) => {
      // Progress update
      setProgress(task.progress.percentage);
      setMessage(task.progress.message);
    }
  );

  console.log('Task completed:', completedTask.result);
} catch (error) {
  console.error('Task failed:', error.message);
}
```

## WebSocket Protocol

### Authentication Message

```json
{
  "token": "Bearer <jwt_token>"
}
```

### Ping Message (Keep-Alive)

```json
{
  "type": "ping"
}
```

### Task Update Message

```json
{
  "type": "task_update",
  "task": {
    "id": "task-123",
    "status": "running",
    "progress": {
      "current": 5,
      "total": 10,
      "percentage": 50,
      "message": "Installing dependencies..."
    }
  }
}
```

### Notification Message

```json
{
  "type": "notification",
  "notification": {
    "title": "Project Created",
    "message": "Your project is ready",
    "type": "success",
    "timestamp": 1704067200000
  }
}
```

## Connection Lifecycle

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   connect   │────>│    open     │────>│   auth      │
└─────────────┘     └─────────────┘     └─────────────┘
                                              │
                           ┌──────────────────┘
                           ▼
                    ┌─────────────┐
                    │   active    │◄──────┐
                    │  (receive   │       │ ping every
                    │  messages)  │───────┘ 30 seconds
                    └─────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
       ┌──────────┐ ┌──────────┐ ┌──────────┐
       │  close   │ │  error   │ │disconnect│
       └──────────┘ └──────────┘ └──────────┘
              │            │
              └────────────┘
                    │
                    ▼ (after 5s)
             ┌─────────────┐
             │  reconnect  │
             └─────────────┘
```
