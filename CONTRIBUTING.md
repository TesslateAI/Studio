# Contributing to Tesslate Studio

Thank you for your interest in contributing to Tesslate Studio! This document provides guidelines and information for contributors.

## Code of Conduct

By participating in this project, you agree to maintain a respectful and inclusive environment.

## Getting Started

### Prerequisites

- **Node.js** 18+ and npm/pnpm
- **Python** 3.11+
- **Docker** and Docker Compose
- **Git**

### Development Setup

1. **Fork the repository** on GitHub

2. **Clone your fork**:
   ```bash
   git clone https://github.com/YOUR_USERNAME/Studio.git
   cd Studio
   ```

3. **Copy environment variables**:
   ```bash
   cp .env.example .env
   ```

4. **Start the development environment**:
   ```bash
   docker compose up -d
   ```

5. **Access the application**:
   - Frontend: http://localhost
   - API: http://localhost/api

### Running Tests

**Backend tests**:
```bash
cd orchestrator
uv run pytest
```

**Frontend tests**:
```bash
cd app
npm test
```

## How to Contribute

### Reporting Bugs

1. Check existing issues to avoid duplicates
2. Include steps to reproduce, expected vs actual behavior
3. Add screenshots if applicable

### Suggesting Features

1. Check if it's already been suggested
2. Clearly describe the problem it solves
3. Consider the impact on existing functionality

### Your First Contribution

Look for issues labeled:
- `good first issue`
- `help wanted`

## Pull Request Process

1. **Create a branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following our coding standards

3. **Commit your changes** with a descriptive message:
   ```bash
   git commit -m "feat: add new feature X"
   ```

   We follow [Conventional Commits](https://www.conventionalcommits.org/):
   - `feat:` - New feature
   - `fix:` - Bug fix
   - `docs:` - Documentation changes
   - `refactor:` - Code refactoring

4. **Push and create a Pull Request**

## Coding Standards

### Python (Backend)

- Follow [PEP 8](https://pep8.org/) style guide
- Use type hints where possible
- Write docstrings for public functions

### TypeScript (Frontend)

- Use TypeScript for all new code
- Define interfaces for component props
- Use functional components with hooks

## Project Structure

```
Studio/
├── app/                    # React frontend
├── orchestrator/          # FastAPI backend
├── k8s/                   # Kubernetes manifests
└── docker-compose.yml     # Local development setup
```

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).
