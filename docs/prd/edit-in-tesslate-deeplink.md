# PRD: "Edit in Tesslate" Deep Link

## Overview

Enable external websites to link users into Tesslate Studio with a pre-filled repository import. A single URL scheme (`/import?repo=<url>`) handles authentication, redirects, and opens the Import Repository modal ready to go.

## Motivation

Third-party sites hosting open-source projects (documentation sites, READMEs, landing pages) should be able to offer a one-click "Edit in Tesslate" experience. This drives user acquisition and reduces friction for new project creation from existing repositories.

## URL Scheme

```
https://your-domain.com/import?repo=<encoded-git-url>
```

**Examples:**
- `https://your-domain.com/import?repo=https%3A%2F%2Fgithub.com%2Ftesslateai%2Fagent-wrapped`
- `https://your-domain.com/import?repo=https%3A%2F%2Fgitlab.com%2Forg%2Frepo`

## User Flows

### Flow 1: Authenticated User

```
External Site
  → /import?repo=https://github.com/org/repo
  → ImportRedirect checks auth ✓
  → Navigate to /dashboard?import_repo=<encoded-url>
  → Dashboard reads param, opens RepoImportModal with URL pre-filled
  → User clicks "Create Project"
```

### Flow 2: Unauthenticated User (Email/Password)

```
External Site
  → /import?repo=https://github.com/org/repo
  → ImportRedirect checks auth ✗
  → Navigate to /login with state.from = "/import?repo=<encoded-url>"
  → User logs in
  → Login reads redirectTo from state.from
  → Navigate to /import?repo=<encoded-url>
  → ImportRedirect checks auth ✓ (re-enters Flow 1)
  → Dashboard with modal open
```

### Flow 3: Unauthenticated User (OAuth)

```
External Site
  → /import?repo=https://github.com/org/repo
  → ImportRedirect checks auth ✗
  → Navigate to /login with state.from = "/import?repo=<encoded-url>"
  → User clicks "Continue with GitHub/Google"
  → Login saves redirectTo to sessionStorage.oauth_redirect
  → OAuth provider callback → /oauth/callback
  → OAuthLoginCallback reads sessionStorage.oauth_redirect
  → Navigate to /import?repo=<encoded-url>
  → ImportRedirect checks auth ✓ (re-enters Flow 1)
  → Dashboard with modal open
```

### Flow 4: New User (Registration)

```
External Site
  → /import?repo=https://github.com/org/repo
  → ImportRedirect → /login with state.from
  → User clicks "Sign up" link
  → Login passes state.from to Register via Link state
  → User registers → auto-login
  → Register reads redirectTo from state.from
  → Navigate to /import?repo=<encoded-url>
  → ImportRedirect → Dashboard with modal open
```

### Flow 5: Invalid/Missing Repo Param

```
External Site
  → /import (no repo param)
  → ImportRedirect → /dashboard (no modal)

  → /import?repo=not-a-url
  → ImportRedirect → /dashboard (no modal)

  → /import?repo=http://github.com/org/repo (not https)
  → ImportRedirect → /dashboard (no modal)
```

## Implementation Details

### Tesslate Studio (this repo)

#### 1. New Page: `app/src/pages/ImportRedirect.tsx`

Lightweight redirect orchestrator. Reads `?repo=` search param, checks auth via `useAuth()`, and navigates accordingly. Not wrapped in `PrivateRoute` — handles auth internally to support both states.

#### 2. Modified: `app/src/components/modals/RepoImportModal/index.tsx`

Added optional `initialRepoUrl?: string` prop. When provided and the modal opens, the repo URL input is pre-filled, triggering the existing URL resolution pipeline (provider detection, repo metadata fetch, branch listing).

#### 3. Modified: `app/src/pages/Dashboard.tsx`

Reads `?import_repo=` search param (same pattern as existing `?create=true&base_id=`). When present, opens the import dialog with the URL passed as `initialRepoUrl`. Clears the param from the URL bar.

#### 4. Modified: `app/src/App.tsx`

Added `<Route path="/import" element={<ImportRedirect />} />` as a public route (no auth guard wrapper).

#### 5. Tests

- `app/src/pages/ImportRedirect.test.tsx` — Unit tests for all auth states and param variations
- `app/src/components/RouteGuards.test.tsx` — Added `/import` to route config as public route

### Agent-Wrapped Repo (external)

#### 1. Modified: `src/app/page.tsx`

Added "Edit in Tesslate" button in the navigation bar next to "Get Started". Links to:
```
https://your-domain.com/import?repo=https://github.com/tesslateai/agent-wrapped
```

Uses the Tesslate logo SVG icon for brand recognition. Styled to match the existing nav design system.

## Security Considerations

- **No open redirect**: The `repo` param is never used as a redirect target. `ImportRedirect` only navigates to internal paths (`/dashboard`, `/login`). The repo URL is only ever passed as a query parameter value.
- **URL validation**: Only `https://` URLs are accepted. Non-HTTPS and non-URL values are rejected (user is redirected to dashboard without the modal).
- **No XSS surface**: The repo URL flows through `useSearchParams()` → state → prop → controlled input. React's JSX escaping prevents injection.

## Integration Guide (for external sites)

Any website can add an "Edit in Tesslate" button:

```html
<a href="https://your-domain.com/import?repo=https://github.com/your-org/your-repo">
  Edit in Tesslate
</a>
```

**Markdown badge for READMEs:**
```markdown
[![Edit in Tesslate](https://img.shields.io/badge/Edit%20in-Tesslate-blue)](https://your-domain.com/import?repo=https://github.com/your-org/your-repo)
```

## Future Enhancements

- `branch` param: `/import?repo=...&branch=develop` to pre-select a branch
- `auto` param: `/import?repo=...&auto=true` to skip the modal and create the project immediately
- Custom badge/button SVG hosted at `your-domain.com/badge.svg`
- Analytics tracking for deep link conversions
