import { useState } from 'react';

interface NotesPanelProps {
  projectId: number;
}

interface Task {
  id: number;
  text: string;
  status: 'todo' | 'inprogress' | 'done';
}

export function NotesPanel({ projectId }: NotesPanelProps) {
  const [notes, setNotes] = useState('Add your project notes and ideas here...');
  const [tasks, setTasks] = useState<Task[]>([
    { id: 1, text: 'Add login page', status: 'todo' },
    { id: 2, text: 'Setup database', status: 'todo' },
    { id: 3, text: 'Build hero section', status: 'inprogress' },
    { id: 4, text: 'Project setup', status: 'done' }
  ]);

  const getTasksByStatus = (status: Task['status']) => {
    return tasks.filter(task => task.status === status);
  };

  return (
    <div className="h-full overflow-y-auto">
      {/* Project Notes */}
      <div className="panel-section p-6 border-b border-white/5">
        <h3 className="text-sm font-semibold text-gray-400 mb-4">PROJECT NOTES</h3>
        <div
          contentEditable
          className="notes-editor bg-white/3 border border-white/10 rounded-lg p-4 min-h-[200px] text-gray-200 outline-none focus:border-[var(--primary)]"
          suppressContentEditableWarning
          onBlur={(e) => setNotes(e.currentTarget.textContent || '')}
        >
          {notes}
        </div>
      </div>

      {/* Task Board */}
      <div className="panel-section p-6">
        <h3 className="text-sm font-semibold text-gray-400 mb-4">TASK BOARD</h3>
        <div className="kanban-board grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* To Do Column */}
          <div className="kanban-column bg-white/3 border border-white/8 rounded-lg p-4">
            <div className="font-semibold text-sm mb-2 text-white">To Do</div>
            {getTasksByStatus('todo').map(task => (
              <div
                key={task.id}
                className="kanban-card bg-white/5 border border-white/10 rounded-lg p-3 mt-2 cursor-move transition-all hover:bg-white/8 hover:-translate-y-0.5"
              >
                <div className="text-sm text-white">{task.text}</div>
              </div>
            ))}
          </div>

          {/* In Progress Column */}
          <div className="kanban-column bg-white/3 border border-white/8 rounded-lg p-4">
            <div className="font-semibold text-sm mb-2 text-white">In Progress</div>
            {getTasksByStatus('inprogress').map(task => (
              <div
                key={task.id}
                className="kanban-card bg-white/5 border border-white/10 rounded-lg p-3 mt-2 cursor-move transition-all hover:bg-white/8 hover:-translate-y-0.5"
              >
                <div className="text-sm text-white">{task.text}</div>
              </div>
            ))}
          </div>

          {/* Done Column */}
          <div className="kanban-column bg-white/3 border border-white/8 rounded-lg p-4">
            <div className="font-semibold text-sm mb-2 text-white">Done</div>
            {getTasksByStatus('done').map(task => (
              <div
                key={task.id}
                className="kanban-card bg-white/5 border border-white/10 rounded-lg p-3 mt-2 cursor-move transition-all hover:bg-white/8 hover:-translate-y-0.5"
              >
                <div className="text-sm text-white">{task.text}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
