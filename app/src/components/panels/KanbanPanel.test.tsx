import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ---------------------------------------------------------------------------
// Mock dependencies
// ---------------------------------------------------------------------------

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockPatch = vi.fn();
const mockDelete = vi.fn();

vi.mock('../../lib/api', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    patch: (...args: unknown[]) => mockPatch(...args),
    delete: (...args: unknown[]) => mockDelete(...args),
  },
}));

vi.mock('react-hot-toast', () => ({
  default: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

// Stub drag-and-drop — not testing DnD interactions here
vi.mock('@hello-pangea/dnd', () => ({
  DragDropContext: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Droppable: ({ children }: { children: (p: unknown, s: unknown) => React.ReactNode }) =>
    children(
      { innerRef: vi.fn(), droppableProps: {}, placeholder: null },
      { isDraggingOver: false },
    ),
  Draggable: ({ children }: { children: (p: unknown, s: unknown) => React.ReactNode }) =>
    children(
      { innerRef: vi.fn(), draggableProps: {}, dragHandleProps: {} },
      { isDragging: false },
    ),
}));

import { KanbanPanel } from './KanbanPanel';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeBoard(overrides?: { tasks?: Partial<Record<string, unknown>>[] }) {
  return {
    id: 'board-1',
    project_id: 'proj-1',
    name: 'Test Board',
    columns: [
      {
        id: 'col-1',
        name: 'To Do',
        position: 0,
        color: 'blue',
        icon: '📝',
        is_backlog: false,
        is_completed: false,
        tasks: overrides?.tasks ?? [
          {
            id: 'task-1',
            column_id: 'col-1',
            title: 'Fix login bug',
            description: 'Auth is broken',
            position: 0,
            priority: 'high',
            task_type: 'bug',
            tags: ['frontend'],
            point_value: 5,
            assignee: { id: 'u1', name: 'Alice', username: 'alice' },
            estimate_hours: 4,
            created_at: '2026-04-01T00:00:00Z',
            updated_at: '2026-04-01T00:00:00Z',
          },
        ],
      },
      {
        id: 'col-2',
        name: 'Done',
        position: 1,
        color: 'green',
        icon: '✅',
        is_backlog: false,
        is_completed: true,
        tasks: [],
      },
    ],
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-01T00:00:00Z',
  };
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  mockGet.mockResolvedValue({ data: makeBoard() });
  mockPost.mockResolvedValue({ data: { id: 'new-1', message: 'ok' } });
  mockPatch.mockResolvedValue({ data: { message: 'ok' } });
  mockDelete.mockResolvedValue({ data: { message: 'ok' } });
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('KanbanPanel', () => {
  it('renders board with columns and tasks', async () => {
    render(<KanbanPanel projectId="proj-1" />);

    await waitFor(() => {
      expect(screen.getByText('Fix login bug')).toBeInTheDocument();
    });

    expect(screen.getByText('To Do')).toBeInTheDocument();
    expect(screen.getByText('Done')).toBeInTheDocument();
  });

  it('displays point_value badge on task card', async () => {
    render(<KanbanPanel projectId="proj-1" />);

    await waitFor(() => {
      expect(screen.getByText('5 pts')).toBeInTheDocument();
    });
  });

  it('does not render point badge when point_value is null', async () => {
    const board = makeBoard({
      tasks: [
        {
          id: 'task-2',
          column_id: 'col-1',
          title: 'No points task',
          position: 0,
          priority: 'low',
          task_type: 'task',
          tags: [],
          created_at: '2026-04-01T00:00:00Z',
          updated_at: '2026-04-01T00:00:00Z',
        },
      ],
    });
    mockGet.mockResolvedValue({ data: board });

    render(<KanbanPanel projectId="proj-1" />);

    await waitFor(() => {
      expect(screen.getByText('No points task')).toBeInTheDocument();
    });

    expect(screen.queryByText(/pts/)).not.toBeInTheDocument();
  });

  it('shows Story Points input in create task modal', async () => {
    render(<KanbanPanel projectId="proj-1" />);

    await waitFor(() => {
      expect(screen.getByText('To Do')).toBeInTheDocument();
    });

    // Click the "+" button on the To Do column
    const addButtons = screen.getAllByTitle('Add task');
    fireEvent.click(addButtons[0]);

    expect(screen.getByText('Story Points')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('e.g. 5')).toBeInTheDocument();
  });

  it('includes point_value in create task API call', async () => {
    render(<KanbanPanel projectId="proj-1" />);

    await waitFor(() => {
      expect(screen.getByText('To Do')).toBeInTheDocument();
    });

    // Open create modal
    const addButtons = screen.getAllByTitle('Add task');
    fireEvent.click(addButtons[0]);

    // Fill in title
    const titleInput = screen.getByPlaceholderText('Task title...');
    fireEvent.change(titleInput, { target: { value: 'New task' } });

    // Fill in point_value
    const pointsInput = screen.getByPlaceholderText('e.g. 5');
    fireEvent.change(pointsInput, { target: { value: '8' } });

    // Submit
    const createButton = screen.getByRole('button', { name: 'Create Task' });
    fireEvent.click(createButton);

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        '/api/kanban/projects/proj-1/tasks',
        expect.objectContaining({
          title: 'New task',
          point_value: 8,
        }),
      );
    });
  });

  it('shows point_value in task details modal', async () => {
    // Mock task details endpoint
    mockGet.mockImplementation((url: string) => {
      if (url.includes('/tasks/task-1')) {
        return Promise.resolve({
          data: {
            id: 'task-1',
            title: 'Fix login bug',
            description: 'Auth is broken',
            priority: 'high',
            task_type: 'bug',
            point_value: 5,
            estimate_hours: 4,
            tags: ['frontend'],
            assignee: { id: 'u1', name: 'Alice', username: 'alice' },
            comments: [],
            created_at: '2026-04-01T00:00:00Z',
            updated_at: '2026-04-01T00:00:00Z',
          },
        });
      }
      return Promise.resolve({ data: makeBoard() });
    });

    render(<KanbanPanel projectId="proj-1" />);

    await waitFor(() => {
      expect(screen.getByText('Fix login bug')).toBeInTheDocument();
    });

    // Click the task card to open details
    fireEvent.click(screen.getByText('Fix login bug'));

    await waitFor(() => {
      expect(screen.getByText('Story Points')).toBeInTheDocument();
    });

    // The details modal should show "5 pts"
    const ptsBadges = screen.getAllByText('5 pts');
    expect(ptsBadges.length).toBeGreaterThanOrEqual(1);
  });

  it('renders in readOnly mode without add buttons', async () => {
    render(<KanbanPanel projectId="proj-1" readOnly />);

    await waitFor(() => {
      expect(screen.getByText('Fix login bug')).toBeInTheDocument();
    });

    expect(screen.queryByTitle('Add task')).not.toBeInTheDocument();
  });
});
