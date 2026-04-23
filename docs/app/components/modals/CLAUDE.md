# Modals

Dialog-based flows in `app/src/components/modals/`. Every modal uses the standard fixed-inset backdrop pattern (see `docs/app/components/CLAUDE.md`).

## File Index

| File | Purpose |
|------|---------|
| `modals/index.ts` | Barrel export |
| `modals/ConfirmDialog.tsx` | Generic confirm/cancel dialog: title, message, optional danger variant, loading state |
| `modals/CreateProjectModal.tsx` | New project wizard: name, base template picker (from `marketplaceApi.getAllBases`), visibility, compute tier |
| `modals/DeploymentModal.tsx` | External-deploy wizard: provider picker, credential check, environment picker, confirm |
| `modals/ExportTemplateModal.tsx` | Export project as a marketplace base: slug, name, description, category, tags, icon. Uses `createPortal` to escape transform ancestors |
| `modals/GitCommitDialog.tsx` | Commit staged files: message, author override, amend toggle, push-after-commit toggle |
| `modals/GitHubConnectModal.tsx` | Connect GitHub OAuth for git operations |
| `modals/GitHubImportModal.tsx` | Legacy GitHub-only import (superseded by `RepoImportModal` but retained for direct deep-links) |
| `modals/ProjectAccessModal.tsx` | Team/user project-access management: add members, set role (editor/viewer), remove |
| `modals/ProviderConnectModal.tsx` | Inline OAuth popup for deployment providers (Vercel, Netlify, Cloudflare, Amplify). Uses `useRef` for interval management, 5-minute timeout |
| `modals/FeedbackModal.tsx` | User-facing feedback submission (bug, idea, other) |
| `modals/CreateFeedbackModal.tsx` | Admin-side feedback creation |
| `modals/SubmitBaseModal.tsx` | Create/edit a marketplace base from a project. Visibility toggle (public/private), category, tags, icon, ownership check |

## RepoImportModal (decomposed)

`modals/RepoImportModal/` is broken into sub-components for maintainability:

| File | Purpose |
|------|---------|
| `RepoImportModal/index.tsx` | Orchestrator. Wires resolver, sections, and submit |
| `RepoImportModal/RepoUrlInput.tsx` | URL input with live validation indicator (green check / red cross) |
| `RepoImportModal/RepoInfoCard.tsx` | Resolved repo metadata card (name, description, stars, default branch) |
| `RepoImportModal/BranchSelector.tsx` | Branch/tag dropdown populated from `gitProvidersApi.listBranches` |
| `RepoImportModal/BrowseReposSection.tsx` | Grid of user's connected-provider repos with search |
| `RepoImportModal/ConnectProviderInline.tsx` | Inline OAuth popup to connect GitHub/GitLab/Bitbucket if none are connected |
| `RepoImportModal/useRepoResolver.ts` | Custom hook: debounced URL -> repo-metadata resolution with cancellation on unmount |

## Related Docs

- `docs/app/components/CLAUDE.md` – modal patterns (backdrop, focus trap, validation, OAuth popup)
- `docs/app/components/connectors/CLAUDE.md` – OAuth popup implementation details
