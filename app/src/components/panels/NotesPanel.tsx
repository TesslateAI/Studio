import { useState } from 'react';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Placeholder from '@tiptap/extension-placeholder';
import {
  TextB,
  TextItalic,
  ListBullets,
  ListNumbers,
  Code,
  TextHOne,
  TextHTwo,
  TextHThree
} from '@phosphor-icons/react';

interface NotesPanelProps {
  projectId: number;
}

interface Task {
  id: number;
  text: string;
  status: 'todo' | 'inprogress' | 'done';
}

type TabType = 'notes' | 'kanban';

export function NotesPanel({ projectId }: NotesPanelProps) {
  const [activeTab, setActiveTab] = useState<TabType>('notes');
  const [tasks, setTasks] = useState<Task[]>([
    { id: 1, text: 'Add login page', status: 'todo' },
    { id: 2, text: 'Setup database', status: 'todo' },
    { id: 3, text: 'Build hero section', status: 'inprogress' },
    { id: 4, text: 'Project setup', status: 'done' }
  ]);

  const editor = useEditor({
    extensions: [
      StarterKit,
      Placeholder.configure({
        placeholder: 'Start writing your project notes...',
      }),
    ],
    content: '<p>Add your project notes and ideas here...</p>',
    editorProps: {
      attributes: {
        class: 'prose prose-invert max-w-none focus:outline-none min-h-[400px] p-4',
      },
    },
  });

  const getTasksByStatus = (status: Task['status']) => {
    return tasks.filter(task => task.status === status);
  };

  if (!editor) {
    return null;
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Tabs */}
      <div className="flex border-b border-white/10 bg-[var(--surface)]/50 backdrop-blur-sm">
        <button
          onClick={() => setActiveTab('notes')}
          className={`px-6 py-3 text-sm font-semibold transition-all ${
            activeTab === 'notes'
              ? 'text-orange-400 border-b-2 border-orange-500 bg-orange-500/10'
              : 'text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5'
          }`}
        >
          Notes
        </button>
        <button
          onClick={() => setActiveTab('kanban')}
          className={`px-6 py-3 text-sm font-semibold transition-all ${
            activeTab === 'kanban'
              ? 'text-orange-400 border-b-2 border-orange-500 bg-orange-500/10'
              : 'text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5'
          }`}
        >
          Kanban Board
        </button>
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-y-auto">
        {activeTab === 'notes' && (
          <div className="h-full flex flex-col">
            {/* Editor Toolbar */}
            <div className="flex items-center gap-1 p-2 border-b border-white/10 bg-[var(--background)]/50 backdrop-blur-sm flex-wrap">
              <button
                onClick={() => editor.chain().focus().toggleBold().run()}
                className={`p-2 rounded hover:bg-white/10 transition-colors ${
                  editor.isActive('bold') ? 'bg-orange-500/20 text-orange-400' : 'text-[var(--text)]/60'
                }`}
                title="Bold"
              >
                <TextB size={18} weight="bold" />
              </button>
              <button
                onClick={() => editor.chain().focus().toggleItalic().run()}
                className={`p-2 rounded hover:bg-white/10 transition-colors ${
                  editor.isActive('italic') ? 'bg-orange-500/20 text-orange-400' : 'text-[var(--text)]/60'
                }`}
                title="Italic"
              >
                <TextItalic size={18} weight="bold" />
              </button>
              <div className="w-px h-6 bg-white/10 mx-1" />
              <button
                onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
                className={`p-2 rounded hover:bg-white/10 transition-colors ${
                  editor.isActive('heading', { level: 1 }) ? 'bg-orange-500/20 text-orange-400' : 'text-[var(--text)]/60'
                }`}
                title="Heading 1"
              >
                <TextHOne size={18} weight="bold" />
              </button>
              <button
                onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
                className={`p-2 rounded hover:bg-white/10 transition-colors ${
                  editor.isActive('heading', { level: 2 }) ? 'bg-orange-500/20 text-orange-400' : 'text-[var(--text)]/60'
                }`}
                title="Heading 2"
              >
                <TextHTwo size={18} weight="bold" />
              </button>
              <button
                onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
                className={`p-2 rounded hover:bg-white/10 transition-colors ${
                  editor.isActive('heading', { level: 3 }) ? 'bg-orange-500/20 text-orange-400' : 'text-[var(--text)]/60'
                }`}
                title="Heading 3"
              >
                <TextHThree size={18} weight="bold" />
              </button>
              <div className="w-px h-6 bg-white/10 mx-1" />
              <button
                onClick={() => editor.chain().focus().toggleBulletList().run()}
                className={`p-2 rounded hover:bg-white/10 transition-colors ${
                  editor.isActive('bulletList') ? 'bg-orange-500/20 text-orange-400' : 'text-[var(--text)]/60'
                }`}
                title="Bullet List"
              >
                <ListBullets size={18} weight="bold" />
              </button>
              <button
                onClick={() => editor.chain().focus().toggleOrderedList().run()}
                className={`p-2 rounded hover:bg-white/10 transition-colors ${
                  editor.isActive('orderedList') ? 'bg-orange-500/20 text-orange-400' : 'text-[var(--text)]/60'
                }`}
                title="Numbered List"
              >
                <ListNumbers size={18} weight="bold" />
              </button>
              <button
                onClick={() => editor.chain().focus().toggleCodeBlock().run()}
                className={`p-2 rounded hover:bg-white/10 transition-colors ${
                  editor.isActive('codeBlock') ? 'bg-orange-500/20 text-orange-400' : 'text-[var(--text)]/60'
                }`}
                title="Code Block"
              >
                <Code size={18} weight="bold" />
              </button>
            </div>

            {/* Tiptap Editor */}
            <div className="flex-1 overflow-y-auto bg-[var(--background)]">
              <EditorContent editor={editor} className="h-full tiptap-editor" />
            </div>
          </div>
        )}

        {activeTab === 'kanban' && (
          <div className="p-6">
            <div className="kanban-board grid grid-cols-1 md:grid-cols-3 gap-4">
              {/* To Do Column */}
              <div className="kanban-column bg-[var(--surface)]/50 border border-white/10 rounded-lg p-4">
                <div className="font-semibold text-sm mb-3 text-[var(--text)] flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-blue-500"></div>
                  To Do
                  <span className="ml-auto text-xs text-[var(--text)]/50">{getTasksByStatus('todo').length}</span>
                </div>
                {getTasksByStatus('todo').map(task => (
                  <div
                    key={task.id}
                    className="kanban-card bg-[var(--background)] border border-white/10 rounded-lg p-3 mb-2 cursor-move transition-all hover:bg-[var(--surface)] hover:border-orange-500/50 hover:shadow-lg"
                  >
                    <div className="text-sm text-[var(--text)]">{task.text}</div>
                  </div>
                ))}
              </div>

              {/* In Progress Column */}
              <div className="kanban-column bg-[var(--surface)]/50 border border-white/10 rounded-lg p-4">
                <div className="font-semibold text-sm mb-3 text-[var(--text)] flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-orange-500"></div>
                  In Progress
                  <span className="ml-auto text-xs text-[var(--text)]/50">{getTasksByStatus('inprogress').length}</span>
                </div>
                {getTasksByStatus('inprogress').map(task => (
                  <div
                    key={task.id}
                    className="kanban-card bg-[var(--background)] border border-white/10 rounded-lg p-3 mb-2 cursor-move transition-all hover:bg-[var(--surface)] hover:border-orange-500/50 hover:shadow-lg"
                  >
                    <div className="text-sm text-[var(--text)]">{task.text}</div>
                  </div>
                ))}
              </div>

              {/* Done Column */}
              <div className="kanban-column bg-[var(--surface)]/50 border border-white/10 rounded-lg p-4">
                <div className="font-semibold text-sm mb-3 text-[var(--text)] flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-green-500"></div>
                  Done
                  <span className="ml-auto text-xs text-[var(--text)]/50">{getTasksByStatus('done').length}</span>
                </div>
                {getTasksByStatus('done').map(task => (
                  <div
                    key={task.id}
                    className="kanban-card bg-[var(--background)] border border-white/10 rounded-lg p-3 mb-2 cursor-move transition-all hover:bg-[var(--surface)] hover:border-orange-500/50 hover:shadow-lg"
                  >
                    <div className="text-sm text-[var(--text)]">{task.text}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
