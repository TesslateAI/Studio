import { useState, useEffect, useCallback } from 'react';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Placeholder from '@tiptap/extension-placeholder';
import Underline from '@tiptap/extension-underline';
import { TextAlign } from '@tiptap/extension-text-align';
import { Link } from '@tiptap/extension-link';
import { Image } from '@tiptap/extension-image';
import { Table } from '@tiptap/extension-table';
import { TableRow } from '@tiptap/extension-table-row';
import { TableCell } from '@tiptap/extension-table-cell';
import { TableHeader } from '@tiptap/extension-table-header';
import { TaskList } from '@tiptap/extension-task-list';
import { TaskItem } from '@tiptap/extension-task-item';
import { Highlight } from '@tiptap/extension-highlight';
import { CodeBlockLowlight } from '@tiptap/extension-code-block-lowlight';
import { common, createLowlight } from 'lowlight';
import {
  TextB,
  TextItalic,
  TextUnderline,
  TextStrikethrough,
  ListBullets,
  ListNumbers,
  Code,
  TextHOne,
  TextHTwo,
  TextHThree,
  Quotes,
  Link as LinkIcon,
  Image as ImageIcon,
  Table as TableIcon,
  TextAlignLeft,
  TextAlignCenter,
  TextAlignRight,
  CheckSquare,
  Highlighter,
  ArrowCounterClockwise,
  ArrowClockwise,
  FloppyDisk
} from '@phosphor-icons/react';
import toast from 'react-hot-toast';
import api from '../../lib/api';

const lowlight = createLowlight(common);

interface NotesPanelProps {
  projectSlug: string;
}

const API_URL = import.meta.env.VITE_API_URL || '';

export function NotesPanel({ projectSlug }: NotesPanelProps) {
  const [isSaving, setIsSaving] = useState(false);
  const [lastSaved, setLastSaved] = useState<Date | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        codeBlock: false, // We'll use CodeBlockLowlight instead
      }),
      Placeholder.configure({
        placeholder: 'Start writing your project notes... Press "/" for commands',
      }),
      Underline,
      TextAlign.configure({
        types: ['heading', 'paragraph'],
      }),
      Link.configure({
        openOnClick: false,
        HTMLAttributes: {
          class: 'text-[var(--primary)] hover:text-[var(--primary-hover)] underline cursor-pointer',
        },
      }).extend({
        name: 'customLink', // Rename to avoid conflict with StarterKit
      }),
      Image.configure({
        HTMLAttributes: {
          class: 'rounded-lg max-w-full h-auto',
        },
      }),
      Table.configure({
        resizable: true,
        HTMLAttributes: {
          class: 'border-collapse table-auto w-full my-4',
        },
      }),
      TableRow,
      TableHeader.configure({
        HTMLAttributes: {
          class: 'border border-[var(--text)]/20 bg-white/5 px-3 py-2 text-left font-semibold',
        },
      }),
      TableCell.configure({
        HTMLAttributes: {
          class: 'border border-[var(--text)]/20 px-3 py-2',
        },
      }),
      TaskList.configure({
        HTMLAttributes: {
          class: 'list-none pl-0',
        },
      }),
      TaskItem.configure({
        nested: true,
        HTMLAttributes: {
          class: 'flex items-start gap-2 my-1',
        },
      }),
      Highlight.configure({
        multicolor: true,
        HTMLAttributes: {
          class: 'bg-yellow-500/30 px-1 rounded',
        },
      }),
      CodeBlockLowlight.configure({
        lowlight,
        HTMLAttributes: {
          class: 'bg-black/40 rounded-lg p-4 my-4 overflow-x-auto',
        },
      }),
    ],
    editorProps: {
      attributes: {
        class: 'prose prose-invert max-w-none focus:outline-none min-h-[calc(100vh-200px)] p-6',
      },
    },
    onUpdate: ({ editor }) => {
      debouncedSave(editor.getHTML());
    },
  });

  // Load notes from backend
  useEffect(() => {
    loadNotes();
  }, [projectSlug]);

  const loadNotes = async () => {
    try {
      const response = await api.get(
        `/api/kanban/projects/${projectSlug}/notes`
      );

      if (editor && response.data.content) {
        editor.commands.setContent(response.data.content);
      }
      setLastSaved(response.data.updated_at ? new Date(response.data.updated_at) : null);
    } catch (error: any) {
      console.error('Failed to load notes:', error);
      toast.error('Failed to load notes');
    } finally {
      setIsLoading(false);
    }
  };

  const saveNotes = async (content: string) => {
    try {
      setIsSaving(true);
      await api.put(
        `/api/kanban/projects/${projectSlug}/notes`,
        {
          content,
          content_format: 'html'
        }
      );
      setLastSaved(new Date());
    } catch (error: any) {
      console.error('Failed to save notes:', error);
      toast.error('Failed to save notes');
    } finally {
      setIsSaving(false);
    }
  };

  // Debounced save function
  const debouncedSave = useCallback(
    (() => {
      let timeoutId: ReturnType<typeof setTimeout>;
      return (content: string) => {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => {
          saveNotes(content);
        }, 1000); // Save 1 second after user stops typing
      };
    })(),
    [projectSlug]
  );

  const addLink = () => {
    const url = window.prompt('Enter URL:');
    if (url) {
      editor?.chain().focus().setLink({ href: url }).run();
    }
  };

  const addImage = () => {
    const url = window.prompt('Enter image URL:');
    if (url) {
      editor?.chain().focus().setImage({ src: url }).run();
    }
  };

  if (!editor || isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-[var(--text)]/60">Loading notes...</div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-[var(--background)]">
      {/* Toolbar */}
      <div className="flex-shrink-0 border-b border-[var(--text)]/15 bg-[var(--surface)]/50 backdrop-blur-sm">
        {/* Main Toolbar */}
        <div className="flex items-center gap-1 p-2 flex-wrap">
          {/* Text Formatting */}
          <div className="flex items-center gap-1 pr-2 border-r border-[var(--text)]/15">
            <button
              onClick={() => editor.chain().focus().toggleBold().run()}
              className={`p-2 rounded hover:bg-white/10 transition-colors ${
                editor.isActive('bold') ? 'bg-[rgba(var(--primary-rgb),0.2)] text-[var(--primary)]' : 'text-[var(--text)]/60'
              }`}
              title="Bold (Ctrl+B)"
            >
              <TextB size={18} weight="bold" />
            </button>
            <button
              onClick={() => editor.chain().focus().toggleItalic().run()}
              className={`p-2 rounded hover:bg-white/10 transition-colors ${
                editor.isActive('italic') ? 'bg-[rgba(var(--primary-rgb),0.2)] text-[var(--primary)]' : 'text-[var(--text)]/60'
              }`}
              title="Italic (Ctrl+I)"
            >
              <TextItalic size={18} weight="bold" />
            </button>
            <button
              onClick={() => editor.chain().focus().toggleUnderline().run()}
              className={`p-2 rounded hover:bg-white/10 transition-colors ${
                editor.isActive('underline') ? 'bg-[rgba(var(--primary-rgb),0.2)] text-[var(--primary)]' : 'text-[var(--text)]/60'
              }`}
              title="Underline (Ctrl+U)"
            >
              <TextUnderline size={18} weight="bold" />
            </button>
            <button
              onClick={() => editor.chain().focus().toggleStrike().run()}
              className={`p-2 rounded hover:bg-white/10 transition-colors ${
                editor.isActive('strike') ? 'bg-[rgba(var(--primary-rgb),0.2)] text-[var(--primary)]' : 'text-[var(--text)]/60'
              }`}
              title="Strikethrough"
            >
              <TextStrikethrough size={18} weight="bold" />
            </button>
            <button
              onClick={() => editor.chain().focus().toggleHighlight().run()}
              className={`p-2 rounded hover:bg-white/10 transition-colors ${
                editor.isActive('highlight') ? 'bg-[rgba(var(--primary-rgb),0.2)] text-[var(--primary)]' : 'text-[var(--text)]/60'
              }`}
              title="Highlight"
            >
              <Highlighter size={18} weight="bold" />
            </button>
          </div>

          {/* Headings */}
          <div className="flex items-center gap-1 pr-2 border-r border-[var(--text)]/15">
            <button
              onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
              className={`p-2 rounded hover:bg-white/10 transition-colors ${
                editor.isActive('heading', { level: 1 }) ? 'bg-[rgba(var(--primary-rgb),0.2)] text-[var(--primary)]' : 'text-[var(--text)]/60'
              }`}
              title="Heading 1"
            >
              <TextHOne size={18} weight="bold" />
            </button>
            <button
              onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
              className={`p-2 rounded hover:bg-white/10 transition-colors ${
                editor.isActive('heading', { level: 2 }) ? 'bg-[rgba(var(--primary-rgb),0.2)] text-[var(--primary)]' : 'text-[var(--text)]/60'
              }`}
              title="Heading 2"
            >
              <TextHTwo size={18} weight="bold" />
            </button>
            <button
              onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
              className={`p-2 rounded hover:bg-white/10 transition-colors ${
                editor.isActive('heading', { level: 3 }) ? 'bg-[rgba(var(--primary-rgb),0.2)] text-[var(--primary)]' : 'text-[var(--text)]/60'
              }`}
              title="Heading 3"
            >
              <TextHThree size={18} weight="bold" />
            </button>
          </div>

          {/* Lists */}
          <div className="flex items-center gap-1 pr-2 border-r border-[var(--text)]/15">
            <button
              onClick={() => editor.chain().focus().toggleBulletList().run()}
              className={`p-2 rounded hover:bg-white/10 transition-colors ${
                editor.isActive('bulletList') ? 'bg-[rgba(var(--primary-rgb),0.2)] text-[var(--primary)]' : 'text-[var(--text)]/60'
              }`}
              title="Bullet List"
            >
              <ListBullets size={18} weight="bold" />
            </button>
            <button
              onClick={() => editor.chain().focus().toggleOrderedList().run()}
              className={`p-2 rounded hover:bg-white/10 transition-colors ${
                editor.isActive('orderedList') ? 'bg-[rgba(var(--primary-rgb),0.2)] text-[var(--primary)]' : 'text-[var(--text)]/60'
              }`}
              title="Numbered List"
            >
              <ListNumbers size={18} weight="bold" />
            </button>
            <button
              onClick={() => editor.chain().focus().toggleTaskList().run()}
              className={`p-2 rounded hover:bg-white/10 transition-colors ${
                editor.isActive('taskList') ? 'bg-[rgba(var(--primary-rgb),0.2)] text-[var(--primary)]' : 'text-[var(--text)]/60'
              }`}
              title="Task List"
            >
              <CheckSquare size={18} weight="bold" />
            </button>
          </div>

          {/* Alignment */}
          <div className="flex items-center gap-1 pr-2 border-r border-[var(--text)]/15">
            <button
              onClick={() => editor.chain().focus().setTextAlign('left').run()}
              className={`p-2 rounded hover:bg-white/10 transition-colors ${
                editor.isActive({ textAlign: 'left' }) ? 'bg-[rgba(var(--primary-rgb),0.2)] text-[var(--primary)]' : 'text-[var(--text)]/60'
              }`}
              title="Align Left"
            >
              <TextAlignLeft size={18} weight="bold" />
            </button>
            <button
              onClick={() => editor.chain().focus().setTextAlign('center').run()}
              className={`p-2 rounded hover:bg-white/10 transition-colors ${
                editor.isActive({ textAlign: 'center' }) ? 'bg-[rgba(var(--primary-rgb),0.2)] text-[var(--primary)]' : 'text-[var(--text)]/60'
              }`}
              title="Align Center"
            >
              <TextAlignCenter size={18} weight="bold" />
            </button>
            <button
              onClick={() => editor.chain().focus().setTextAlign('right').run()}
              className={`p-2 rounded hover:bg-white/10 transition-colors ${
                editor.isActive({ textAlign: 'right' }) ? 'bg-[rgba(var(--primary-rgb),0.2)] text-[var(--primary)]' : 'text-[var(--text)]/60'
              }`}
              title="Align Right"
            >
              <TextAlignRight size={18} weight="bold" />
            </button>
          </div>

          {/* Insert Elements */}
          <div className="flex items-center gap-1 pr-2 border-r border-[var(--text)]/15">
            <button
              onClick={() => editor.chain().focus().toggleCodeBlock().run()}
              className={`p-2 rounded hover:bg-white/10 transition-colors ${
                editor.isActive('codeBlock') ? 'bg-[rgba(var(--primary-rgb),0.2)] text-[var(--primary)]' : 'text-[var(--text)]/60'
              }`}
              title="Code Block"
            >
              <Code size={18} weight="bold" />
            </button>
            <button
              onClick={() => editor.chain().focus().toggleBlockquote().run()}
              className={`p-2 rounded hover:bg-white/10 transition-colors ${
                editor.isActive('blockquote') ? 'bg-[rgba(var(--primary-rgb),0.2)] text-[var(--primary)]' : 'text-[var(--text)]/60'
              }`}
              title="Quote"
            >
              <Quotes size={18} weight="bold" />
            </button>
            <button
              onClick={addLink}
              className={`p-2 rounded hover:bg-white/10 transition-colors ${
                editor.isActive('link') ? 'bg-[rgba(var(--primary-rgb),0.2)] text-[var(--primary)]' : 'text-[var(--text)]/60'
              }`}
              title="Add Link"
            >
              <LinkIcon size={18} weight="bold" />
            </button>
            <button
              onClick={addImage}
              className="p-2 rounded hover:bg-white/10 transition-colors text-[var(--text)]/60"
              title="Add Image"
            >
              <ImageIcon size={18} weight="bold" />
            </button>
            <button
              onClick={() => editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()}
              className="p-2 rounded hover:bg-white/10 transition-colors text-[var(--text)]/60"
              title="Insert Table"
            >
              <TableIcon size={18} weight="bold" />
            </button>
          </div>

          {/* History */}
          <div className="flex items-center gap-1 pr-2 border-r border-[var(--text)]/15">
            <button
              onClick={() => editor.chain().focus().undo().run()}
              disabled={!editor.can().undo()}
              className="p-2 rounded hover:bg-white/10 transition-colors text-[var(--text)]/60 disabled:opacity-30 disabled:cursor-not-allowed"
              title="Undo"
            >
              <ArrowCounterClockwise size={18} weight="bold" />
            </button>
            <button
              onClick={() => editor.chain().focus().redo().run()}
              disabled={!editor.can().redo()}
              className="p-2 rounded hover:bg-white/10 transition-colors text-[var(--text)]/60 disabled:opacity-30 disabled:cursor-not-allowed"
              title="Redo"
            >
              <ArrowClockwise size={18} weight="bold" />
            </button>
          </div>

          {/* Save Status */}
          <div className="flex items-center gap-2 ml-auto text-xs text-[var(--text)]/60">
            {isSaving ? (
              <span className="flex items-center gap-1">
                <FloppyDisk size={14} weight="bold" className="animate-pulse" />
                Saving...
              </span>
            ) : lastSaved ? (
              <span className="flex items-center gap-1">
                <FloppyDisk size={14} weight="bold" />
                Saved {lastSaved.toLocaleTimeString()}
              </span>
            ) : null}
          </div>
        </div>
      </div>

      {/* Editor */}
      <div className="flex-1 overflow-y-auto bg-[var(--background)]">
        <EditorContent editor={editor} className="h-full" />
      </div>
    </div>
  );
}
