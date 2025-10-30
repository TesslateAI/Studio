# Contributing to Tesslate Studio

Thank you for your interest in contributing to Tesslate Studio! This guide will help you get started with contributing to the project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)
- [Project Structure](#project-structure)
- [Coding Guidelines](#coding-guidelines)
- [Commit Message Guidelines](#commit-message-guidelines)
- [Pull Request Process](#pull-request-process)
- [Getting Help](#getting-help)

## Code of Conduct

By participating in this project, you agree to maintain a respectful and inclusive environment. We expect all contributors to:

- Be respectful and constructive in discussions
- Welcome newcomers and help them get started
- Focus on what is best for the community
- Show empathy towards other community members

## Getting Started

### Find Something to Work On

1. **Good First Issues**: Check out issues labeled [`good first issue`](https://github.com/TesslateAI/Studio/labels/good%20first%20issue) - these are great for newcomers
2. **Bug Reports**: Look for issues labeled [`bug`](https://github.com/TesslateAI/Studio/labels/bug)
3. **Feature Requests**: Browse issues labeled [`enhancement`](https://github.com/TesslateAI/Studio/labels/enhancement)
4. **Documentation**: Help improve docs - always welcome!

### Before You Start

1. **Check existing issues**: Make sure someone isn't already working on it
2. **Comment on the issue**: Let others know you're working on it
3. **Ask questions**: If anything is unclear, ask in the issue or discussions

## Development Setup

### Prerequisites

- **Node.js** 18+ and npm
- **Python** 3.11+
- **Docker** and Docker Compose
- **Git**

### Fork and Clone

1. Fork the repository on GitHub
2. Clone your fork:

```bash
git clone https://github.com/YOUR-USERNAME/Studio.git
cd Studio
```

3. Add the upstream repository:

```bash
git remote add upstream https://github.com/TesslateAI/Studio.git
```

### Install Dependencies

**Frontend (React + Vite):**

```bash
cd app
npm install
```

**Backend (FastAPI):**

```bash
cd orchestrator
pip install uv  # If you don't have uv
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -r requirements.txt
```

### Environment Configuration

```bash
# From project root
cp .env.example .env
```

Edit `.env` and set required keys:

```env
SECRET_KEY=dev-key-for-testing
LITELLM_MASTER_KEY=sk-dev-key
OPENAI_API_KEY=sk-your-dev-key  # Or use Ollama for free local models
```

### Start Development Environment

**Option 1: Full Docker (Recommended for first-time contributors)**

```bash
docker compose up -d
```

Access at: http://studio.localhost

**Option 2: Hybrid Mode (Faster for active development)**

```bash
# Terminal 1: Start infrastructure
docker compose up -d traefik postgres

# Terminal 2: Run backend with hot reload
cd orchestrator
uv run uvicorn app.main:app --reload

# Terminal 3: Run frontend with hot reload
cd app
npm run dev
```

Access frontend at: http://localhost:5173

## Making Changes

### Create a Branch

Always create a new branch for your changes:

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/bug-description
```

Branch naming conventions:
- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation changes
- `refactor/` - Code refactoring
- `test/` - Adding or updating tests

### Development Workflow

1. **Make your changes** in your branch
2. **Test locally** to ensure everything works
3. **Commit frequently** with clear commit messages
4. **Keep your branch updated** with main:

```bash
git fetch upstream
git rebase upstream/main
```

## Testing

### Frontend Tests

```bash
cd app
npm test                 # Run tests
npm run test:watch      # Run tests in watch mode
npm run test:coverage   # Run with coverage report
```

### Backend Tests

```bash
cd orchestrator
pytest                           # Run all tests
pytest tests/test_agents.py     # Run specific test file
pytest -v                        # Verbose output
pytest --cov=app                # With coverage
```

### Manual Testing

1. Start the development environment
2. Test your changes in the browser
3. Check the browser console for errors
4. Review backend logs: `docker compose logs orchestrator`

### Testing Checklist

Before submitting, verify:
- [ ] All existing tests pass
- [ ] New tests added for new features
- [ ] Manually tested the feature in browser
- [ ] No console errors or warnings
- [ ] Works in both Docker and hybrid mode
- [ ] Database migrations work (if applicable)

## Submitting Changes

### Before You Submit

1. **Update documentation** if you changed functionality
2. **Run tests** to make sure everything passes
3. **Update CHANGELOG** (if applicable)
4. **Rebase on main** to get latest changes:

```bash
git fetch upstream
git rebase upstream/main
```

5. **Push to your fork**:

```bash
git push origin your-branch-name
```

## Project Structure

```
Studio/
├── app/                      # Frontend (React + Vite)
│   ├── src/
│   │   ├── components/      # React components
│   │   ├── pages/           # Page components
│   │   ├── services/        # API services
│   │   ├── hooks/           # Custom React hooks
│   │   └── utils/           # Utility functions
│   └── public/              # Static assets
│
├── orchestrator/            # Backend (FastAPI)
│   ├── app/
│   │   ├── agents/         # AI agent implementations
│   │   ├── api/            # API routes
│   │   ├── models/         # Database models
│   │   ├── services/       # Business logic
│   │   └── utils/          # Utility functions
│   └── tests/              # Backend tests
│
├── scripts/                 # Utility scripts
│   ├── migrations/         # Database migrations
│   ├── seed/               # Database seeding
│   └── agents/             # Agent management
│
├── docs/                    # Documentation
├── docker-compose.yml      # Docker configuration
└── .env.example            # Environment template
```

## Coding Guidelines

### General Principles

- **Keep it simple**: Prefer simple, readable code over clever solutions
- **Be consistent**: Follow existing patterns in the codebase
- **Write tests**: All new features should have tests
- **Document your code**: Use clear variable names and add comments for complex logic

### Frontend Guidelines

**File Organization:**
- One component per file
- Group related components in folders
- Use index.ts for clean imports

**Component Style:**
- Use functional components with hooks
- Props should have TypeScript interfaces
- Extract complex logic into custom hooks

**Example:**

```typescript
// Good
interface TodoItemProps {
  todo: Todo;
  onToggle: (id: string) => void;
  onDelete: (id: string) => void;
}

export const TodoItem: React.FC<TodoItemProps> = ({ todo, onToggle, onDelete }) => {
  return (
    <div className="todo-item">
      <input
        type="checkbox"
        checked={todo.completed}
        onChange={() => onToggle(todo.id)}
      />
      <span>{todo.title}</span>
      <button onClick={() => onDelete(todo.id)}>Delete</button>
    </div>
  );
};
```

### Backend Guidelines

**Code Style:**
- Follow PEP 8 guidelines
- Use type hints for function parameters and returns
- Keep functions focused and small

**API Routes:**
- Use appropriate HTTP methods (GET, POST, PUT, DELETE)
- Include proper error handling
- Add docstrings to endpoints

**Example:**

```python
# Good
@router.post("/projects", response_model=ProjectResponse)
async def create_project(
    project_data: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> ProjectResponse:
    """
    Create a new project for the current user.

    Args:
        project_data: Project creation data
        current_user: Authenticated user
        db: Database session

    Returns:
        Created project details

    Raises:
        HTTPException: If project creation fails
    """
    try:
        project = await project_service.create(db, project_data, current_user.id)
        return project
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

## Commit Message Guidelines

Write clear, descriptive commit messages that explain **what** changed and **why**.

### Format

```
<type>: <short summary>

<optional body>

<optional footer>
```

### Types

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, no logic change)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

### Examples

```bash
# Good commit messages
feat: add dark mode toggle to settings page

fix: resolve container restart issue on Windows
- Update Docker socket path detection
- Add Windows-specific error handling

docs: update configuration guide with new environment variables

refactor: extract agent validation into separate service
```

## Pull Request Process

### Creating a Pull Request

1. **Push your changes** to your fork
2. **Open a PR** on GitHub from your branch to `main`
3. **Fill out the PR template** with all required information
4. **Link related issues** using "Fixes #123" or "Closes #456"

### PR Title Format

Use the same format as commit messages:

```
feat: add user preferences API
fix: resolve Docker network issue on macOS
docs: improve quick start guide
```

### PR Description Template

```markdown
## Description
Brief description of what this PR does.

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Code refactoring
- [ ] Other (please describe)

## Related Issues
Fixes #123
Related to #456

## Testing
- [ ] Tested in Docker mode
- [ ] Tested in hybrid mode
- [ ] Added/updated tests
- [ ] All tests passing

## Screenshots (if applicable)
[Add screenshots here]

## Checklist
- [ ] Code follows project guidelines
- [ ] Self-reviewed the code
- [ ] Commented complex code sections
- [ ] Updated documentation
- [ ] No new warnings generated
- [ ] Added tests for new features
- [ ] All tests pass locally
```

### Review Process

1. **Automated checks** will run (tests, linting)
2. **Maintainers will review** your code
3. **Address feedback** by pushing new commits
4. Once approved, a maintainer will **merge** your PR

### What Reviewers Look For

- **Correctness**: Does it work as intended?
- **Tests**: Are there adequate tests?
- **Documentation**: Is new functionality documented?
- **Style**: Does it follow project conventions?
- **Performance**: Are there any performance concerns?
- **Security**: Are there any security implications?

## Common Contribution Scenarios

### Adding a New Agent

1. Create agent class in `orchestrator/app/agents/`
2. Implement required methods (execute, validate, etc.)
3. Add agent to database seed script
4. Create tests in `orchestrator/tests/test_agents/`
5. Document agent capabilities

### Adding a Project Template

1. Create template files in appropriate directory
2. Add template metadata to seed script
3. Test template creation in browser
4. Document template in README

### Fixing a Bug

1. Write a test that reproduces the bug
2. Fix the bug
3. Verify the test now passes
4. Add regression test if needed

### Updating Documentation

1. Make changes in `docs/` or README
2. Verify links work
3. Check for typos and clarity
4. Build docs locally if applicable

## Development Tips

### Debugging Backend

```bash
# View orchestrator logs
docker compose logs -f orchestrator

# Access Python shell in container
docker compose exec orchestrator python

# Run specific test
docker compose exec orchestrator pytest tests/test_agents.py -v
```

### Debugging Frontend

```bash
# View frontend logs
docker compose logs -f app

# Check for TypeScript errors
cd app && npm run type-check

# Build for production locally
cd app && npm run build
```

### Database Operations

```bash
# Access PostgreSQL
docker compose exec postgres psql -U tesslate -d tesslate_db

# Reset database
docker compose down -v
docker compose up -d

# Run migrations
docker compose exec orchestrator python scripts/migrations/migrate.py
```

## Getting Help

### Where to Ask

- **GitHub Discussions**: For questions and general discussion
- **GitHub Issues**: For bug reports and feature requests
- **Email**: support@tesslate.com for direct support

### Before Asking

1. Check existing issues and discussions
2. Review documentation
3. Search the codebase for similar patterns
4. Try to reproduce the issue

### When Asking

Provide:
- What you're trying to do
- What you've tried
- Error messages (full text)
- Environment details (OS, Docker version, etc.)
- Steps to reproduce

## Recognition

Contributors are recognized in:
- README contributors section
- Release notes for significant contributions
- Special thanks for major features

Thank you for contributing to Tesslate Studio! Your efforts help make this project better for everyone.
