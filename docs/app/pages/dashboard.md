# Dashboard Page

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/Dashboard.tsx`
**Route**: `/dashboard`
**Layout**: DashboardLayout (with NavigationSidebar)

## Purpose

The Dashboard is the main landing page after login. It displays all of a user's projects as cards, provides project creation and import functionality, and shows user profile information including credits and subscription tier.

## Key Features

### 1. Project List Display
Projects are displayed as cards in a grid layout, each showing:
- Project name and description
- Status badge (build, running, stopped, failed)
- Environment status indicator
- Assigned agents (avatars)
- Created/updated timestamps
- Action buttons (open, delete)

### 2. Project Creation
Two methods to create projects:
- **Create from Template**: Select a base template or start blank
- **Import from Git**: Import existing repository from GitHub, GitLab, or Bitbucket

### 3. Task Polling
After project creation, the dashboard polls the backend for task status updates, showing progress in real-time until the project is ready to use.

### 4. Project Deletion
Delete projects with confirmation dialog. Projects being deleted show a loading state and are removed from the list upon completion.

### 5. User Profile
Top-right dropdown shows:
- User name
- Credit balance
- Subscription tier
- Links to settings, billing, and logout

## Component Structure

```
Dashboard
├── Header
│   ├── Logo
│   ├── Welcome message
│   └── User profile dropdown
│       ├── User info (name, credits, tier)
│       ├── Settings link
│       ├── Billing link
│       └── Logout button
│
├── Action Bar
│   ├── "New Project" button
│   ├── "Import from Git" button
│   └── Theme toggle
│
└── Projects Grid
    └── ProjectCard (for each project)
        ├── Project info
        ├── Status badge
        ├── Agents avatars
        └── Actions (open, delete)
```

## State Management

```typescript
// Project data
const [projects, setProjects] = useState<Project[]>([]);
const [loading, setLoading] = useState(true);

// UI state
const [showCreateDialog, setShowCreateDialog] = useState(false);
const [showImportDialog, setShowImportDialog] = useState(false);
const [deletingProjectIds, setDeletingProjectIds] = useState<Set<string>>(new Set());

// Delete confirmation
const [showDeleteDialog, setShowDeleteDialog] = useState(false);
const [projectToDelete, setProjectToDelete] = useState<Project | null>(null);

// User data
const [userName, setUserName] = useState<string>('');
const [userCredits, setUserCredits] = useState<number>(0);
const [userTier, setUserTier] = useState<string>('free');
const [showUserDropdown, setShowUserDropdown] = useState(false);
```

## Data Flow

### Loading Projects

```typescript
useEffect(() => {
  loadProjects();
}, []);

const loadProjects = async () => {
  try {
    const data = await projectsApi.getAll();
    const projectsWithMeta = data.map((p: Project) => ({
      ...p,
      status: (p.status || 'build') as Status,
      agents: p.agents || []
    }));
    setProjects(projectsWithMeta);
  } catch {
    toast.error('Failed to load projects');
  } finally {
    setLoading(false);
  }
};
```

### Creating a Project

Projects are created with a base template selected. After creation, the user is navigated based on the task result:
- If `container_id === 'needs_setup'`: redirects to the **Project Setup** page (`/project/:slug/setup`)
- If `container_id` is a valid ID: navigates to the **Builder view** with that container
- Otherwise: navigates to the **Builder view** without a container

```typescript
const handleCreateProject = async (projectName: string, baseId?: string) => {
  try {
    setIsCreating(true);
    const response = await projectsApi.create(
      projectName,
      '',
      'base',
      undefined,
      'main',
      baseId
    );

    const project = response.project;
    const taskId = response.task_id;

    if (taskId) {
      const result = await tasksApi.pollUntilComplete(taskId);
      const taskResult = result?.result as { container_id?: string } | undefined;

      if (taskResult?.container_id === 'needs_setup') {
        // Project needs setup - redirect to setup screen
        navigate(`/project/${project.slug}/setup`);
      } else if (taskResult?.container_id) {
        navigate(`/project/${project.slug}/builder?container=${taskResult.container_id}`);
      } else {
        navigate(`/project/${project.slug}/builder`);
      }
    } else {
      navigate(`/project/${project.slug}/builder`);
    }
  } catch (error) {
    toast.error('Failed to create project');
  } finally {
    setIsCreating(false);
  }
};
```

### Deleting a Project

```typescript
const confirmDelete = (project: Project) => {
  setProjectToDelete(project);
  setShowDeleteDialog(true);
};

const handleDeleteConfirmed = async () => {
  if (!projectToDelete) return;

  // Add to deleting set
  setDeletingProjectIds(prev => new Set(prev).add(projectToDelete.id));
  setShowDeleteDialog(false);

  try {
    await projectsApi.delete(projectToDelete.slug);

    // Remove from list
    setProjects(prev => prev.filter(p => p.id !== projectToDelete.id));
    toast.success('Project deleted');
  } catch (error) {
    toast.error('Failed to delete project');
  } finally {
    // Remove from deleting set
    setDeletingProjectIds(prev => {
      const next = new Set(prev);
      next.delete(projectToDelete.id);
      return next;
    });
    setProjectToDelete(null);
  }
};
```

### Importing from Git

```typescript
const handleImportProject = async (importData: RepoImportData) => {
  try {
    setIsCreating(true);
    const response = await projectsApi.importFromGit({
      provider: importData.provider, // 'github', 'gitlab', 'bitbucket'
      repo_url: importData.repo_url,
      branch: importData.branch || 'main',
    });

    toast.success('Importing project...');
    setShowImportDialog(false);

    // Poll task status (similar to create)
    pollTaskStatus(response.task_id);
  } catch (error) {
    toast.error('Failed to import project');
  } finally {
    setIsCreating(false);
  }
};
```

## User Profile Dropdown

```typescript
// Fetch user data on mount
useEffect(() => {
  const fetchUserData = async () => {
    try {
      const user = await authApi.getCurrentUser();
      setUserName(user.name || user.username || 'there');
      setUserCredits(user.credits_balance || 0);
      setUserTier(user.subscription_tier || 'free');
    } catch (e) {
      console.error('Failed to fetch user data:', e);
      setUserName('there');
      setUserCredits(0);
      setUserTier('free');
    }
  };
  fetchUserData();
}, []);

// Dropdown menu
<Dropdown show={showUserDropdown} onClose={() => setShowUserDropdown(false)}>
  <div className="user-info">
    <p className="user-name">Hi, {userName}</p>
    <p className="user-credits">{userCredits} credits</p>
    <p className="user-tier">{userTier} tier</p>
  </div>
  <DropdownItem onClick={() => navigate('/settings')}>
    <Gear /> Settings
  </DropdownItem>
  <DropdownItem onClick={() => navigate('/billing')}>
    <CreditCard /> Billing
  </DropdownItem>
  <DropdownDivider />
  <DropdownItem onClick={logout}>
    <SignOut /> Logout
  </DropdownItem>
</Dropdown>
```

## Polling for Updates

The dashboard polls for project status changes every 60 seconds to keep the UI in sync:

```typescript
useEffect(() => {
  const pollInterval = setInterval(() => {
    loadProjects();
  }, 60000); // Poll every 60 seconds

  return () => clearInterval(pollInterval);
}, []);
```

## Project Card Component

Clicking "Open" on a project card navigates directly to the **Builder view** (`/project/:slug/builder`) rather than the architecture canvas. This provides a more immediate coding experience.

```typescript
interface ProjectCardProps {
  project: Project;
  onOpen: (slug: string) => void;  // Navigates to /project/:slug/builder
  onDelete: (project: Project) => void;
  isDeleting: boolean;
}

function ProjectCard({ project, onOpen, onDelete, isDeleting }: ProjectCardProps) {
  return (
    <div className="project-card">
      <div className="card-header">
        <h3>{project.name}</h3>
        <StatusBadge status={project.status} />
      </div>

      <p className="description">{project.description}</p>

      <div className="agents">
        {project.agents?.map(agent => (
          <Tooltip key={agent.name} content={agent.name}>
            <span className="agent-avatar">{agent.icon}</span>
          </Tooltip>
        ))}
      </div>

      <div className="card-footer">
        <span className="timestamp">
          {formatDate(project.updated_at)}
        </span>

        <div className="actions">
          <button onClick={() => onOpen(project.slug)}>
            <ArrowRight /> Open
          </button>
          <button
            onClick={() => onDelete(project)}
            disabled={isDeleting}
          >
            <Trash /> {isDeleting ? 'Deleting...' : 'Delete'}
          </button>
        </div>
      </div>
    </div>
  );
}
```

## Mobile Behavior

On mobile devices (< 768px), the dashboard shows a `MobileWarning` component suggesting users use a desktop browser for the best experience. This is because the project builder interface is not optimized for small screens.

```typescript
const [isDesktop, setIsDesktop] = useState(window.innerWidth >= 768);

useEffect(() => {
  const handleResize = () => setIsDesktop(window.innerWidth >= 768);
  window.addEventListener('resize', handleResize);
  return () => window.removeEventListener('resize', handleResize);
}, []);

if (!isDesktop) {
  return <MobileWarning />;
}
```

## Related Components

- **`CreateProjectModal`**: Modal for creating new projects
- **`RepoImportModal`**: Modal for importing from git repositories
- **`ConfirmDialog`**: Confirmation dialog for project deletion
- **`ProjectCard`**: Individual project card (from `ui/` directory)
- **`LoadingSpinner`**: Loading state indicator
- **`StatusBadge`**: Project status badge
- **`MobileMenu`**: Mobile navigation menu

## Related Pages

- **`ProjectSetup`** (`/project/:slug/setup`): Redirected to when project needs `.tesslate/config.json` setup. See `project-setup.md`.

## API Endpoints Used

```typescript
// Get all projects
GET /api/projects

// Create project
POST /api/projects
{
  name: string,
  description?: string,
  base_id?: number | null
}

// Import from git
POST /api/projects/import
{
  provider: 'github' | 'gitlab' | 'bitbucket',
  repo_url: string,
  branch?: string
}

// Delete project
DELETE /api/projects/{slug}

// Get task status
GET /api/tasks/{task_id}

// Get current user
GET /api/users/me
```

## Styling

The dashboard uses a combination of Tailwind utilities and custom CSS variables:

```css
/* Background gradient */
background: linear-gradient(135deg, var(--background) 0%, var(--surface) 100%);

/* Project cards */
.project-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 24px;
  transition: transform 0.2s, box-shadow 0.2s;
}

.project-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.2);
}

/* Status badges */
.status-build { background: #fbbf24; }
.status-running { background: #10b981; }
.status-stopped { background: #6b7280; }
.status-failed { background: #ef4444; }
```

## Best Practices

### 1. Optimistic UI Updates
Remove projects from the list immediately after deletion starts, then revert if the API call fails:

```typescript
const handleDelete = async (projectId: string) => {
  // Optimistically remove from UI
  const originalProjects = [...projects];
  setProjects(prev => prev.filter(p => p.id !== projectId));

  try {
    await projectsApi.delete(projectId);
    toast.success('Project deleted');
  } catch (error) {
    // Revert on error
    setProjects(originalProjects);
    toast.error('Failed to delete project');
  }
};
```

### 2. Task Polling Cleanup
Always clean up polling intervals to prevent memory leaks:

```typescript
useEffect(() => {
  const interval = setInterval(loadProjects, 60000);
  return () => clearInterval(interval); // Important!
}, []);
```

### 3. Error Boundaries
Wrap the dashboard in an error boundary to catch rendering errors gracefully:

```typescript
<ErrorBoundary fallback={<ErrorPage />}>
  <Dashboard />
</ErrorBoundary>
```

### 4. Loading State
Show skeleton loaders instead of spinners for better UX:

```typescript
if (loading) {
  return (
    <div className="projects-grid">
      {[1, 2, 3, 4].map(i => (
        <ProjectCardSkeleton key={i} />
      ))}
    </div>
  );
}
```

## Troubleshooting

### Issue: Projects not loading
**Check**: API endpoint, authentication token, CORS settings
**Solution**: Verify token in localStorage and backend is running

### Issue: Task polling not updating
**Check**: Task ID is correct, backend task system is running
**Solution**: Check backend logs for task processing errors

### Issue: Delete not working
**Check**: User has permission, project exists
**Solution**: Verify project ownership in backend

### Issue: Import failing
**Check**: Git provider OAuth token, repository access
**Solution**: Re-authenticate with git provider in Account Settings
