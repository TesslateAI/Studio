# Linear Issue Management Conventions

## Purpose

This document captures all conventions and patterns used in Linear issue management for the Tesslate team. These conventions ensure consistency, clarity, and efficient workflow management across all projects.

## Team Structure

**Team Name:** Tesslate (TES)
**Team ID:** 1150dd6c-9cd2-4e6b-b3e4-883f10f58159

**Only Sprint 2 issues are tracked.** All issues must be assigned to Sprint 2 project.

## Issue Identifier Convention

All issues follow the pattern: `TES-{number}`

**Examples:**
- TES-174: Agent Reliability issues - Service discovery, EKS
- TES-110: Integrate project creation from GitHub/Bitbucket/GitLab
- TES-165: [Security] kubectl Command Injection

## Title Conventions

### 1. Security Issues
Security issues are prefixed with `[Security]` and include specific vulnerability types:

**Format:** `[Security] {Vulnerability Type}`

**Examples:**
- `[Security] kubectl Command Injection`
- `[Security] Tool Config Can Override Tool Behavior`
- `[Security] Insufficient Fork Authorization Check`
- `[Security] File Path Traversal Vulnerability`

### 2. Product-Specific Issues
Product-related issues are prefixed with the product name:

**Teals Format:** `Teals {Feature/Component}`
**Trackstars Format:** `Trackstars {Feature/Component}`

**Examples:**
- `Teals Organizations/Hierarchy UX`
- `Teals Contract List View Redesign`
- `Trackstars Rankings/Leaderboard Design`
- `Trackstars Profile Claim Flow`

### 3. Integration/Deployment Issues
Integration and deployment issues follow clear naming patterns:

**Format:** `{Platform} deployment integration`

**Examples:**
- `Vercel deployment integration`
- `Netlify deployment integration`
- `AWS deployment integration`

### 4. Action-Oriented Titles
Most issues use action verbs to clearly indicate what needs to be done:

**Common patterns:**
- `Create {component/feature}` - "Create code analysis agent"
- `Implement {feature}` - "Implement user onboarding workflow"
- `Add {feature}` - "Add 10+ bases, connectors, and integrations to marketplace"
- `Design {component}` - "Design logical blocks building system"
- `Fix {issue}` - Implied by Bug label
- `Validate {component}` - "Validate container cleanup functionality"

## Label Conventions (UPDATED)

### Type Labels (Pick ONE per issue)

| Label | When to Use |
|-------|-------------|
| `Feature` | New functionality |
| `Bug` | Something broken |
| `Security` | Security issue |
| `Enhancement` | Improve existing feature |
| `docs` | Documentation only |
| `chore` | Refactoring, dependencies, tooling |
| `Design` | UI/UX design work |

### Area Labels (Pick 1-2 per issue)

| Label | When to Use |
|-------|-------------|
| `backend` | Orchestrator, API, database, deployment integrations |
| `frontend` | React app, UI components |
| `Infrastructure` | K8s, deployment, DevOps |
| `Agent` | AI agent system |
| `Marketplace` | Marketplace features |

**Note:** Deployment integrations (Vercel, Netlify, AWS, etc.) use `backend` label since they are backend features of Tesslate Studio that allow users to deploy their software.

### Product Labels (Pick ONE per issue)

**REQUIRED:** Every issue must have exactly ONE product label:

| Label | When to Use |
|-------|-------------|
| `tesslate-studio` | Core Tesslate Studio features |
| `Teals` | Teals product work |
| `Trackstars` | Trackstars product work |

### Example Label Combinations

- `Security` + `Bug` + `backend` + `tesslate-studio`
- `Feature` + `Agent` + `tesslate-studio`
- `Design` + `frontend` + `Teals`
- `chore` + `Infrastructure` + `tesslate-studio`
- `Feature` + `backend` + `tesslate-studio` (deployment integrations)
- `chore` + `tesslate-studio` (business/company operations)

## Priority Conventions (UPDATED)

**Priority Levels (1-4):**

### 1. Urgent
Production down, security breach, critical bugs blocking all work

**Examples:**
- TES-162: [Security] Template Injection in substitute_markers()
- TES-163: [Security] Missing System Prompt Input Validation
- TES-164: [Security] Insufficient Fork Authorization Check
- TES-166: [Security] File Path Traversal Vulnerability
- TES-180: Hibernated Projects Don't Hydrate and show files

### 2. High
Blocks next sprint, key customer issue, high-value features, important security issues

**Examples:**
- TES-110: Integrate project creation from GitHub/Bitbucket/GitLab
- TES-127: Agent pod control in project view
- TES-157: Get everything documented (Legal & Financial)
- TES-158: Evaluate Vanta and get started on SOC 2 compliance
- TES-159: Compliance: Set up Carta account & offer letters
- TES-160: Create data room for investors
- TES-165: [Security] kubectl Command Injection
- TES-168: [Security] Tool Config Can Override Tool Behavior
- TES-172: Create automated and oracle tests for each agent
- TES-174: Agent Reliability issues - Service discovery, EKS
- TES-181: Teals New Logo
- TES-184: Updated UX Product Design for Teals
- TES-188: Teals Organizations/Hierarchy UX
- TES-189: Teals Contract Creation Flow
- TES-190: Teals Contract List View Redesign

### 3. Medium (Default)
Important but not blocking - standard work items

**Examples:**
- Most feature development
- Infrastructure improvements
- Design work
- Business operations
- Agent development

### 4. Low
Nice-to-have, technical debt, future optimizations, low-priority deployment integrations

**Examples:**
- TES-112: Research additional integrations for marketplace
- TES-114: Design logical blocks building system
- All deployment integrations (TES-130 through TES-140)
- TES-169: [Security] Missing Audit Logging for Agent Modifications
- TES-170: [Security] Add rehype-sanitize to ReactMarkdown

## Status Conventions

**Standard Workflow:**
1. **Backlog** - Not yet scheduled or planned
2. **Todo** - Scheduled but not started
3. **In Progress** - Actively being worked on
4. **In Review** - Completed and under review
5. **Done** - Completed and verified
6. **Canceled** - Will not be completed

**Status Usage Patterns:**
- Security issues often remain in "In Review" for thorough validation
- Design issues move through: Backlog → Todo → [Design work] → Done
- Parent tasks may stay in Backlog while subtasks are completed

## Description Conventions

### 1. Security Issues
Security issue descriptions include:
- Clear vulnerability description
- Affected files with line numbers
- Technical details of the vulnerability

**Example:**
```
Namespace and pod names are interpolated directly into shell commands without escaping.
Shell metacharacters in user-controlled values could lead to command injection.

**File:** `orchestrator/app/agent/prompts.py` (lines 85-86, 103-104)
```

### 2. Feature Issues with Requirements
Feature descriptions often include structured requirements:

**Pattern:**
```
Brief description of the feature.

**Requirements:**
* Bullet point requirement 1
* Bullet point requirement 2
* Bullet point requirement 3
```

### 3. Design Issues with Acceptance Criteria
Design issues include structured acceptance criteria:

**Pattern:**
```
Brief description of the design work needed.

**Context:** (if applicable)
* Background information
* Example scenarios

**Acceptance Criteria:**
* Specific deliverable 1
* Specific deliverable 2
* Specific deliverable 3
```

### 4. Minimal Descriptions
Some issues (especially internal workflow issues) have minimal or no description, relying on the title alone.

## Project Assignment

**IMPORTANT:** All issues must be assigned to the **Sprint 2** project.

- **Sprint 2** - Current sprint project (ID: ad30bd38-16f2-4c30-af8f-03b022fcd354)
  - Start Date: 2026-01-12
  - Target Date: 2026-01-19

## Assignee Conventions

**Team Members:**
- Manav Majumdar (c98f7fd3-5346-4443-b000-22a255c71387) - Lead, handles infrastructure, agent work
- ernest@tesslate.com (1b3f071d-98b3-4a32-9c4e-c5c06be986ff) - Security, bug fixes
- joshua@tesslate.com (06c51bd4-0944-4fea-a11a-e27e1a3887ba) - Website, features
- zakiya@tesslate.com (7b036507-ee0d-4311-a87a-184996849223) - Marketplace, UX
- kavya@tesslate.com (f5ea7ca5-cf73-4617-bc48-06a4f68b2a9c) - Business, design strategy
- vanshika@tesslate.com (9be849f0-3ff6-4656-8cb4-fc3e7eb9c062) - Design, UX
- vartika@tesslate.com (34c7da3b-07b3-4317-ab35-d0d4ff32b3ce) - Design, UX
- stephen@tesslate.com (4f1f089b-4fe1-4180-8da2-f3f77916553a) - Documentation, open source

**Assignment Patterns:**
- Security issues → ernest@tesslate.com
- Design issues → vanshika@, vartika@, zakiya@
- Infrastructure → Manav Majumdar
- Business → kavya@tesslate.com
- Documentation → stephen@tesslate.com

## Git Branch Naming Convention

All issues have associated git branches following the pattern:

**Format:** `manav/{issue-identifier}-{slugified-title}`

**Examples:**
- `manav/tes-174-agent-reliability-issues-service-discovery-eks`
- `manav/tes-110-integrate-project-creation-from-githubbitbucketgitlab`
- `manav/tes-165-security-kubectl-command-injection`
- `manav/tes-188-teals-organizationshierarchy-ux`

**Pattern Rules:**
- Always prefixed with `manav/` (team lead's name)
- Issue identifier in lowercase: `tes-{number}`
- Title is slugified (lowercase, hyphens instead of spaces)
- Special characters removed or replaced with hyphens

## Parent-Child Task Relationships

Issues use the `parentId` field to create hierarchical relationships:

**Examples:**
- **TES-116** - K8s autoscaling validation and optimization (parent)
  - TES-117: Test autoscaling performance under load (subtask)
  - TES-118: Calculate and document infrastructure costs (subtask)
  - TES-119: Validate container cleanup functionality (subtask)
  - TES-120: S3 project archive storage strategy (subtask)

- **TES-129** - Multi-platform deployment support (parent)
  - TES-130 through TES-140: Various deployment integrations (subtasks)

## Notes for AI Agents

When creating or updating Linear issues:

### 1. Always use appropriate prefixes
- `[Security]` for security issues
- `Teals` / `Trackstars` for product-specific work

### 2. Label Requirements
**Type + Area + Product (REQUIRED)**

Example: `security` + `bug` + `backend` + `tesslate-studio`

### 3. Product Label is MANDATORY
Every issue MUST have exactly ONE product label:
- `tesslate-studio` - Default for Tesslate Studio features
- `teals` - Only for Teals-specific work
- `trackstars` - Only for Trackstars-specific work

### 4. Priority Guidelines (Use the updated levels)
- **Urgent (1)**: Production down, critical security, blocking bugs
- **High (2)**: Blocks next sprint, important features, key security issues
- **Medium (3)**: Standard work items (default for most work)
- **Low (4)**: Nice-to-have, future features, low-priority integrations

### 5. Follow git branch naming
- `manav/tes-{number}-{slugified-title}`
- All lowercase, hyphens for spaces

### 6. Use parent-child relationships
- Break complex tasks into subtasks
- Reference parent task ID

### 7. Status progression
- Backlog → Todo → In Progress → In Review → Done
- Security issues stay in Review longer

### 8. Assignment patterns
- Match expertise: security → ernest@, design → vanshika@/vartika@
- Lead (Manav) handles infrastructure and agents

### 9. Sprint 2 Project Only
- ALL issues MUST be assigned to Sprint 2 project
- Delete or archive issues not in Sprint 2

## Related Contexts

- `C:\Users\Smirk\Downloads\Tesslate-Studio\CLAUDE.md` - Root project context
- `docs/orchestrator/CLAUDE.md` - Backend architecture
- `docs/app/CLAUDE.md` - Frontend architecture
- `docs/infrastructure/kubernetes/CLAUDE.md` - Kubernetes deployment

## When to Load This Context

Load this context when:
- Creating new Linear issues
- Updating existing issues
- Planning sprints or organizing backlog
- Understanding team workflow and conventions
- Setting up integrations with Linear API
- Training new team members on issue management
