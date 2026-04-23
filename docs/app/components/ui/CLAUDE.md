# UI Primitives

Shared low-level UI components in `app/src/components/ui/`. Every component here is presentation-only (no feature coupling) and is used across the app.

## File Index

| File | Purpose |
|------|---------|
| `ui/index.ts` | Barrel export (FloatingSidebar, FloatingPanel, MobileMenu, NavigationSidebar, Tooltip) |
| `ui/button.tsx` | shadcn/Radix `Slot`-based button with `cva` variants (default, destructive, outline, secondary, ghost, link) and sizes (sm/md/lg/icon) |
| `ui/textarea.tsx` | Styled textarea primitive with forwarded ref |
| `ui/Tooltip.tsx` | Hover tooltip rendered via `createPortal` with framer-motion fade, keyboard-accessible |
| `ui/InfoTooltip.tsx` | Tooltip variant anchored to an Info icon; used inline in forms and tables |
| `ui/Dropdown.tsx` | Generic click-outside dropdown with item icons and keyboard navigation |
| `ui/Tabs.tsx` | Controlled tab bar with active-indicator; accepts `Tab[]` with `id`, `label`, optional icon |
| `ui/ToggleSwitch.tsx` | Accessible on/off switch with disabled state |
| `ui/StatusBadge.tsx` | Status pill with three states: `idea`, `build`, `launch`; editable via popover |
| `ui/EnvironmentStatusBadge.tsx` | Environment/compute-tier badge. Consumes `environmentStatus.ts` for status -> style mapping |
| `ui/environmentStatus.ts` | `EnvironmentStatus` union (`running`, `agent_active`, etc.) and `STATUS_MAP` to icons/colors/labels |
| `ui/TaskProgress.tsx` | Progress bar for background tasks. Subscribes to `taskService` and auto-updates |
| `ui/Toast.tsx` | Custom toast provider wired into `taskService`; used alongside `react-hot-toast` for task-specific notifications |
| `ui/Breadcrumbs.tsx` | Header breadcrumb trail using React Router `Link` with ChevronRight separators |
| `ui/FloatingPanel.tsx` | Title-bar + close-button floating panel with theme-aware styling; used by project-builder side panels |
| `ui/FloatingSidebar.tsx` | Vertical icon sidebar with tooltips on hover |
| `ui/GlassContainer.tsx` | Glassmorphism wrapper (backdrop blur, translucent background) |
| `ui/NavigationSidebar.tsx` | Main app sidebar with Recent section, user dropdown, help menu, logout. Delegates logout to `AuthContext.logout()` |
| `ui/MobileMenu.tsx` | Mobile hamburger-triggered drawer wrapping `NavigationSidebar` |
| `ui/HelpButton.tsx` | "?" button that triggers `KeyboardShortcutsModal` via `useHotkeys` |
| `ui/HelpMenu.tsx` | Comprehensive help dropdown with submenus (Docs, Keyboard Shortcuts, Contact, Discord) |
| `ui/HelpModal.tsx` | Help docs modal (video links, chat, schedule a call) |
| `ui/UserDropdown.tsx` | Top-right user dropdown: avatar, name, credits, tier, settings, logout |
| `ui/TesslateLogo.tsx` | SVG logo component with configurable width/height |
| `ui/TechStackIcons.tsx` | Simple-Icons-based tech stack icons (React, TypeScript, Tailwind, Next.js, etc.) |
| `ui/ProjectCard.tsx` | Project-specific card with `ComputeTier`, status, visibility icon, `AgentTag`s |
| `ui/AgentTag.tsx` | Small pill showing an agent's icon + name |
| `ui/MarketplaceCard.tsx` | Generic marketplace listing card (simpler variant than `components/marketplace/AgentCard`) |
| `ui/MarkerPill.tsx` | Colored tag pill with optional remove-button |
| `ui/MarkerEditor.tsx` | Inline marker editor (add, rename, color) |
| `ui/MarkerPalette.tsx` | Predefined marker color palette. Also exports `Marker` interface |
| `ui/MoodyFace.tsx` | Animated mood indicator (neutral/happy/thinking/sad) for onboarding and empty states |
| `ui/ruixen-moon-chat.tsx` | Animated chat trigger variant (shadcn experimental) |

## Conventions

1. **Theme-aware**: Use CSS custom properties (`var(--surface)`, `var(--text)`, etc.) rather than hardcoded Tailwind color classes.
2. **Portal pattern**: Tooltips, dropdowns inside transformed ancestors (framer-motion), and modals all use `createPortal(..., document.body)` to escape containing blocks.
3. **Touch targets**: Minimum 44x44px for any interactive element (`min-h-[44px] min-w-[44px]`).
4. **Accessibility**: Every interactive primitive has `aria-label` or visible text; keyboard navigation supported via `react-hotkeys-hook` or native focus handling.

## Related Docs

- `docs/app/keyboard-shortcuts/CLAUDE.md` – `HelpButton`, `KeyboardShortcutsModal`
- `docs/app/components/CLAUDE.md` – component conventions
- `docs/app/layouts/CLAUDE.md` – layouts that use `NavigationSidebar`, `MobileMenu`
