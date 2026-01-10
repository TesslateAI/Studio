# Modal Components

**Location**: `app/src/components/modals/`

Modal dialog components for project creation, deployment configuration, Git operations, and user feedback.

## Components Overview

### CreateProjectModal.tsx

**New Project Dialog**: Simple modal for creating a new project with name input.

**Props**:
```typescript
interface CreateProjectModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (projectName: string) => void;
  isLoading?: boolean;
}
```

**Features**:
- Project name input with character limit (100 chars)
- Loading state during creation
- Keyboard shortcuts (Enter to confirm, Escape to cancel)
- Validation (require non-empty name)

**Usage**:
```typescript
const [showCreateModal, setShowCreateModal] = useState(false);
const [isCreating, setIsCreating] = useState(false);

<CreateProjectModal
  isOpen={showCreateModal}
  onClose={() => setShowCreateModal(false)}
  onConfirm={async (name) => {
    setIsCreating(true);
    try {
      await projectsApi.create({ name });
      toast.success('Project created!');
      setShowCreateModal(false);
    } catch (error) {
      toast.error('Failed to create project');
    } finally {
      setIsCreating(false);
    }
  }}
  isLoading={isCreating}
/>
```

---

### DeploymentModal.tsx

**External Deploy Configuration**: Multi-step wizard for deploying to Vercel, Netlify, or Cloudflare.

**Features**:
- Provider selection (Vercel/Netlify/Cloudflare)
- OAuth authentication flow
- Repository selection
- Build configuration
- Environment variables
- Deployment confirmation

**Steps**:
1. Choose provider
2. Connect account (OAuth)
3. Select repository (or create new)
4. Configure build settings
5. Add environment variables
6. Confirm and deploy

---

### GitCommitDialog.tsx

**Git Commit & Push**: Dialog for committing changes and pushing to remote.

**Props**:
```typescript
interface GitCommitDialogProps {
  projectSlug: string;
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}
```

**Features**:
- View changed files
- Commit message input with history
- Author info (name + email)
- Push to remote option
- Commit message templates

**Usage**:
```typescript
<GitCommitDialog
  projectSlug={project.slug}
  isOpen={showCommitDialog}
  onClose={() => setShowCommitDialog(false)}
  onSuccess={() => {
    toast.success('Changes committed and pushed!');
    refreshGitStatus();
  }}
/>
```

---

### GitHubConnectModal.tsx

**GitHub OAuth Connection**: Modal for connecting GitHub account.

**Features**:
- Initiates GitHub OAuth flow
- Callback handling
- Connection status
- Scopes explanation (repo access, commit, etc.)

---

### GitHubImportModal.tsx

**Import from GitHub**: Browse and import existing GitHub repositories.

**Features**:
- Repository list with search
- Organization selection
- Branch selection
- Import confirmation
- Clone status

---

### RepoImportModal/

**Multi-Provider Import**: Unified import experience for GitHub, GitLab, and Bitbucket.

**Structure**:
```
RepoImportModal/
├── index.tsx              # Main modal component
├── ProviderSelection.tsx  # GitHub/GitLab/Bitbucket buttons
├── RepoList.tsx           # Repository browser
└── ImportConfig.tsx       # Branch, path selection
```

**Features**:
- Provider detection
- OAuth for each provider
- Repository browsing
- Branch selection
- Subdirectory import support

---

### ConfirmDialog.tsx

**Generic Confirmation**: Reusable confirmation dialog for destructive actions.

**Props**:
```typescript
interface ConfirmDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  destructive?: boolean;  // Red confirm button
}
```

**Usage**:
```typescript
<ConfirmDialog
  isOpen={showDeleteConfirm}
  onClose={() => setShowDeleteConfirm(false)}
  onConfirm={async () => {
    await projectsApi.delete(project.id);
    navigate('/projects');
  }}
  title="Delete Project"
  message="Are you sure? This action cannot be undone."
  confirmText="Delete"
  destructive
/>
```

---

### FeedbackModal.tsx

**User Feedback**: Collect feedback, bug reports, and feature requests.

**Features**:
- Feedback type selection (bug, feature, general)
- Description textarea
- Screenshot attachment
- Contact info (optional)
- Submission to backend

---

### CreateFeedbackModal.tsx

**Bug Report Form**: Simplified feedback form specifically for bug reports.

**Features**:
- Pre-filled with "Bug Report" type
- Steps to reproduce
- Expected vs actual behavior
- Browser/OS info auto-collected

## Common Modal Pattern

All modals follow this structure:

```tsx
export function Modal({ isOpen, onClose, onConfirm }: Props) {
  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50"
      onClick={onClose}  // Close on backdrop click
    >
      <div
        className="bg-[var(--surface)] p-8 rounded-3xl max-w-md shadow-2xl border border-white/10"
        onClick={(e) => e.stopPropagation()}  // Prevent backdrop click
      >
        {/* Header */}
        <div className="flex items-start justify-between mb-6">
          <div className="flex items-start gap-4">
            <div className="w-12 h-12 bg-[var(--primary)]/20 rounded-xl flex items-center justify-center">
              <Icon className="text-[var(--primary)]" />
            </div>
            <div>
              <h2 className="text-xl font-bold">Modal Title</h2>
              <p className="text-sm text-gray-400">Description</p>
            </div>
          </div>
          <button onClick={onClose}>
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="mb-6">
          {/* Modal-specific content */}
        </div>

        {/* Actions */}
        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 bg-white/5 border border-white/10 py-3 rounded-xl"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="flex-1 bg-[var(--primary)] py-3 rounded-xl"
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
}
```

## Modal State Management

### Simple Boolean State

```typescript
const [showModal, setShowModal] = useState(false);

<button onClick={() => setShowModal(true)}>Open</button>

<Modal
  isOpen={showModal}
  onClose={() => setShowModal(false)}
/>
```

### With Data

```typescript
const [modalData, setModalData] = useState<{ id: string; name: string } | null>(null);

<button onClick={() => setModalData({ id: '1', name: 'Project' })}>
  Open
</button>

<Modal
  isOpen={!!modalData}
  onClose={() => setModalData(null)}
  data={modalData}
/>
```

## Keyboard Shortcuts

All modals should support:
- `Escape` to close
- `Enter` to confirm (if focused on input/button)

```typescript
const handleKeyDown = (e: React.KeyboardEvent) => {
  if (e.key === 'Enter' && !isLoading) {
    onConfirm();
  } else if (e.key === 'Escape' && !isLoading) {
    onClose();
  }
};

<div onKeyDown={handleKeyDown}>
  {/* Modal content */}
</div>
```

## Preventing Backdrop Click While Loading

```typescript
const handleBackdropClick = () => {
  if (!isLoading) {
    onClose();
  }
};

<div onClick={handleBackdropClick}>
  {/* Modal */}
</div>
```

## Animation

Modals use Tailwind's animation utilities:

```tsx
<div className="animate-in fade-in zoom-in-95 duration-200">
  {/* Modal content */}
</div>
```

## Accessibility

- Focus trap (focus stays within modal)
- ARIA labels
- Screen reader announcements

```tsx
<div
  role="dialog"
  aria-modal="true"
  aria-labelledby="modal-title"
  aria-describedby="modal-description"
>
  <h2 id="modal-title">Title</h2>
  <p id="modal-description">Description</p>
</div>
```

---

**See CLAUDE.md for advanced patterns and testing.**
