# OpenSail — Design Rules

Canonical reference for the visual design system. All UI work on the dashboard, sidebar, and shared components must follow these rules.

---

## Typography

| Property | Value |
|---|---|
| Font family | `'DM Sans'` (variable font, weight 100–1000, optical size 9–40) |
| Fallback stack | `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif` |
| Mono font | `JetBrains Mono, Menlo, Monaco, 'Courier New', monospace` |
| Base font size | `12px` (`0.75rem`) |
| Base font weight | `500` (medium — compensates for readability at small size) |
| Line height | `1.5` |
| Loading text size | `13px` |
| Error text size | `15px` / line-height `24px` |
| Rendering | `-webkit-font-smoothing: antialiased` + `text-rendering: optimizeLegibility` |
| Word spacing | `normal` |

### Font Loading

Google Fonts variable import in `index.html`:
```
https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,100..1000;1,9..40,100..1000&display=swap
```

### Size Scale in Components

- Nav labels, body text, descriptions, timestamps: `text-xs` (12px)
- Card titles, section headings: `text-sm` (14px) at `font-semibold`
- Logo wordmark: `text-sm` at `font-semibold`
- Page headings (e.g. "Projects"): `text-xs` at `font-semibold`

---

## Color System

### Philosophy

- **Sidebar recedes, content glows.** Sidebar is darker (`#090909`) than the content area (`#0f0f11`). Only ~6 steps of difference, but the content panel "glows" slightly relative to the sidebar.
- **Opaque colors, not rgba.** All background, border, and muted text colors use opaque hex values instead of `rgba(255,255,255,0.x)`. This prevents stacking transparency artifacts.
- **Quiet borders.** Borders are extremely low-contrast against the base (`#1c1e21` on `#0f0f11`). Structure is felt, not seen.
- **Brand colors untouched.** Primary orange `#f89521` and accent cyan `#00d9ff` are never changed.

### Dark Mode Tokens (Default)

| Token | Value | Usage |
|---|---|---|
| `--primary` | `#f89521` | Brand orange — buttons, accents, focus rings |
| `--primary-hover` | `#fa9f35` | Hover state for primary |
| `--primary-rgb` | `248, 149, 33` | For rgba() usage |
| `--accent` | `#00d9ff` | Secondary accent — cyan |
| `--bg` | `#0f0f11` | Main content background — subtle warm shift |
| `--surface` | `#161618` | Cards, panels, elevated surfaces |
| `--surface-hover` | `#1c1e21` | Surface hover state |
| `--text` | `#ffffff` | Primary text — pure white |
| `--text-muted` | `#6b6f76` | Secondary/muted text — opaque cool mid-gray |
| `--text-subtle` | `#4a4e55` | Tertiary text — opaque dark gray |
| `--border` | `#1c1e21` | Borders — opaque, low contrast |
| `--border-hover` | `#2a2c30` | Border hover state |
| `--sidebar-bg` | `#090909` | Sidebar background — nearly pure black |
| `--sidebar-text` | `#ffffff` | Sidebar primary text |
| `--sidebar-border` | `#1c1e21` | Sidebar dividers |
| `--sidebar-hover` | `#111113` | Sidebar item hover |
| `--sidebar-active` | `#161618` | Sidebar active item |
| `--input-bg` | `#161618` | Input backgrounds |
| `--input-border` | `#1c1e21` | Input borders |
| `--input-border-focus` | `#f89521` | Input focus ring |
| `--input-placeholder` | `#4a4e55` | Input placeholder text |
| `--scrollbar-thumb` | `#2a2c30` | Scrollbar thumb |
| `--scrollbar-thumb-hover` | `#3a3c40` | Scrollbar thumb hover |
| `--code-block-bg` | `#0a0a0c` | Code block background |
| `--code-block-border` | `#1c1e21` | Code block border |

### Light Mode Tokens (Reference)

| Token | Value | Usage |
|---|---|---|
| `--bg` | `#fcfcfd` | Content area — almost white with hint of cool |
| `--sidebar-bg` | `#f5f5f5` | Sidebar — neutral light gray |
| `--border` | `#e0e0e0` | Borders — soft neutral gray |
| `--text` | `#23252a` | Primary text — warm dark, not pure black |
| `--text-muted` | `#b0b5c0` | Muted text — slightly blue-shifted gray |

### Status Colors (Unchanged)

| Token | Value |
|---|---|
| `--status-error` | `#ef4444` |
| `--status-success` | `#22c55e` |
| `--status-warning` | `#f59e0b` |
| `--status-info` | `#3b82f6` |
| `--status-purple` | `#a855f7` |
| `--status-gray` | `#6b7280` |

---

## Border Radius

| Element | Value | CSS Variable |
|---|---|---|
| Main content panel | `12px` | `--radius` / `--radius-xl` |
| Cards, modals, floating bars | `12px` | `--radius` |
| Buttons, inputs, small controls | `4px` | `--control-border-radius` |
| Badges, tags | `4px` | `--control-border-radius` |
| Scrollbar thumb | `4px` | — |
| Help button, plan badge | `full` (pill) | `rounded-full` |

The 12px on content panels gives the app a rounded-rectangle feel. Controls use tighter 4px.

---

## Border Weight

| Condition | Weight | CSS Variable |
|---|---|---|
| Standard displays (1x) | `1px` | `--border-width` |
| Retina/HiDPI displays (2x+) | `0.5px` | `--border-width` |

Implemented via media query:
```css
@media (-webkit-min-device-pixel-ratio: 2), (min-resolution: 192dpi) {
  :root { --border-width: 0.5px; }
}
```

Apply via inline style `borderWidth: 'var(--border-width)'` on elements that need it, or use the `.app-panel` class.

---

## Spacing & Layout

### Floating Panel Layout

The main content area floats as a rounded panel with margin on all sides. The sidebar background shows through the margin gap, creating depth without shadows.

| Element | Value | CSS Variable |
|---|---|---|
| App border margin | `8px` | `--app-margin` |
| Sidebar width (expanded) | `244px` | `--sidebar-width` |
| Sidebar width (collapsed) | `48px` | `--sidebar-width-collapsed` |
| Content panel border-radius | `12px` | `--radius` |
| Content panel border | `var(--border-width) solid var(--border)` | — |
| Content panel background | `var(--bg)` | — |
| Outer shell background | `var(--sidebar-bg)` | — |

### DashboardLayout Structure

```
┌─ outer shell (bg: --sidebar-bg) ─────────────────────────────────┐
│ ┌─ sidebar ─┐  ┌─ floating content panel (bg: --bg) ──────────┐ │
│ │           │  │  8px margin from edges                        │ │
│ │  244px    │  │  12px border-radius                           │ │
│ │  #090909  │  │  0.5px border (retina)                        │ │
│ │           │  │                                               │ │
│ │           │  │  ┌─ top bar ─────────────────────────────┐    │ │
│ │           │  │  │ h-10, border-bottom                   │    │ │
│ │           │  │  └───────────────────────────────────────┘    │ │
│ │           │  │  ┌─ scrollable content ──────────────────┐    │ │
│ │           │  │  │ p-5                                   │    │ │
│ │           │  │  │ project grid                          │    │ │
│ │           │  │  └───────────────────────────────────────┘    │ │
│ └───────────┘  └───────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

### Responsive Breakpoint

Single breakpoint. Desktop or not-desktop.

| Breakpoint | Behavior |
|---|---|
| `> 1023px` | Full layout with sidebar, 8px margins, floating panel |
| `<= 1023px` | Full-bleed content (`margin: -1px`), no sidebar, no floating panel |

Implemented in CSS:
```css
@media (max-width: 1023px) {
  .app-panel {
    margin: -1px !important;
    border-radius: 0 !important;
    border: none !important;
  }
}
```

### Scrollbar

| Property | Value |
|---|---|
| Width | `12px` |
| Height | `12px` |
| Thumb color | `var(--scrollbar-thumb)` — `#2a2c30` |
| Thumb hover | `var(--scrollbar-thumb-hover)` — `#3a3c40` |
| Track | `transparent` |
| Firefox | `scrollbar-width: thin` |

---

## Sidebar (NavigationSidebar)

### Dimensions

- Expanded: `244px` wide
- Collapsed: `48px` wide
- Logo area height: `48px` (h-12)
- Nav item height: `32px` (h-8)
- Nav item gap: `2px` (gap-0.5)
- Padding: `py-2 px-2` (expanded), centered (collapsed)
- Divider: `1px` with `mx-3` inset

### Icons

- Size: `16px` (`size={16}`)
- Active: `text-[var(--sidebar-text)]` (white)
- Inactive: `text-[var(--text-muted)]` (`#6b6f76`)
- Hover: `group-hover:text-[var(--sidebar-text)]`

### Animation

- Expand/collapse: `0.45s` with `cubic-bezier(0.45, 0, 0.55, 1)`
- Content fade: `0.4s ease-out`
- Login entry: sidebar slides from `x: -300` over `0.45s`

---

## Animation & Transitions

### Easing Curves

| Token | Value | Usage |
|---|---|---|
| `--easing` | `cubic-bezier(0.4, 0, 0.2, 1)` | General interactions |
| `--easing-layout` | `cubic-bezier(0.45, 0, 0.55, 1)` | Layout transitions (sidebar, margins) |

The layout easing is a **symmetric ease-in-out** — slightly faster than standard. Feels responsive but not jarring.

### Duration Scale

| Token | Value | Usage |
|---|---|---|
| `--duration-fast` | `150ms` | Micro-interactions (hover, focus) |
| `--duration-normal` | `200ms` | Standard transitions (buttons, inputs) |
| `--duration-slow` | `300ms` | Reveal animations |
| Layout transitions | `450ms` | Sidebar, panel margin/radius |

### Specific Animations

| Animation | Duration | Easing | Delay |
|---|---|---|---|
| Sidebar expand/collapse | `0.45s` | `cubic-bezier(.45, 0, .55, 1)` | — |
| Login: background fade | `0.3s` | `ease-out` | — |
| Login: sidebar slide-in | `0.45s` | `cubic-bezier(.45, 0, .55, 1)` | `200ms` |
| Login: content fade-in | `0.4s` | default | `500ms` |
| Login: sidebar content | `0.4s` | `ease-out` | `800ms` |
| Panel margin/radius | `0.45s` | `var(--easing-layout)` | — |
| Interactive elements | `200ms` | `var(--easing-layout)` | — |

### Reduced Motion

All animations and transitions are disabled via `prefers-reduced-motion: reduce`.

---

## ProjectCard

- Background: `var(--surface)` (`#161618`)
- Border: `var(--border)` with `var(--border-width)`, hover to `var(--border-hover)`
- Selected border: `var(--primary)`
- Border-radius: `var(--radius)` (12px)
- Hover: `-translate-y-0.5` (subtle, not dramatic)
- Title: `text-sm font-semibold`
- Description: `text-xs text-[var(--text-muted)]`
- Timestamp: `text-xs text-[var(--text-subtle)]`
- Open button: `bg-[var(--primary)]`, `rounded-[var(--control-border-radius)]`, `text-xs`, `py-2 px-3`
- Secondary buttons: `bg-[var(--surface-hover)]`, `border-[var(--border)]`, `rounded-[var(--control-border-radius)]`
- Delete button: hover to `bg-[rgba(var(--status-red-rgb),0.1)]`

---

## Dashboard Page

- Top bar: `h-10`, no background override (inherits from floating panel), border-bottom with `var(--border-width)`
- Content padding: `p-4 md:p-5`
- Grid: `grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4`
- Create card: dashed border with `rgba(var(--primary-rgb), 0.3)`, `rounded-[var(--radius)]`
- Create card icon box: `w-14 h-14`, `rounded-[var(--radius)]`
- Floating bulk action bar: `rounded-[var(--radius)]`, `var(--border-width)` border, buttons use `var(--control-border-radius)`

---

## Shadows

Shadows are minimal. The floating panel creates depth through the margin gap, not drop shadows.

| Token | Value |
|---|---|
| `--shadow-small` | `0 1px 2px rgba(0, 0, 0, 0.4)` |
| `--shadow-medium` | `0 4px 6px rgba(0, 0, 0, 0.4)` |
| `--shadow-large` | `0 10px 15px rgba(0, 0, 0, 0.4)` |

---

## Key Files

| File | What it controls |
|---|---|
| `app/src/index.css` | CSS variables, global styles, retina borders, scrollbar, animations |
| `app/src/theme/themePresets.ts` | `applyThemePreset()` — applies all CSS variables from theme objects |
| `app/src/types/theme.ts` | `DEFAULT_FALLBACK_THEME` — hardcoded fallback before API themes load |
| `app/src/theme/fonts.ts` | Font family constants |
| `app/index.html` | Google Fonts import (variable font) |
| `app/src/components/DashboardLayout.tsx` | Floating panel layout, sidebar container, login animations |
| `app/src/components/ui/NavigationSidebar.tsx` | Sidebar navigation, expand/collapse, 244px width |
| `app/src/pages/Dashboard.tsx` | Dashboard page, top bar, project grid, bulk actions |
| `app/src/components/ui/ProjectCard.tsx` | Project card styling, buttons, status badges |

---

## Design Principles (Summary)

| Principle | Implementation |
|---|---|
| Quiet borders | `0.5px` on retina, opaque low-contrast colors (`#1c1e21` on `#0f0f11`) |
| Sidebar recedes | Sidebar darker (`#090909`) than content (`#0f0f11`) |
| Floating content | `12px` radius, `8px` margin, depth without shadows |
| Minimal type | `12px` / weight `500` — dense but readable |
| Single brand accent | `#f89521` orange for primary actions only |
| Smooth motion | `0.45s` symmetric `cubic-bezier` for layout, `ease-out` for reveals |
| Opaque palette | No `rgba(255,255,255,…)` for structural colors — opaque hex only |
| Mobile: full-bleed | Single breakpoint at `1023px`, panel collapses to full-bleed |
