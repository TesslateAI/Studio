# Theme System

The theme system provides light/dark mode support with CSS custom properties and localStorage persistence.

## Files

| File | Purpose |
|------|---------|
| `app/src/theme/ThemeContext.tsx` | React context and provider |
| `app/src/theme/variables.css` | CSS custom properties |
| `app/src/theme/fonts.ts` | Font configuration |
| `app/src/theme/index.ts` | Public exports |

## ThemeContext

**File**: `app/src/theme/ThemeContext.tsx`

### Interface

```typescript
interface ThemeContextType {
  theme: 'light' | 'dark';
  toggleTheme: () => void;
}
```

### Provider Implementation

```typescript
export function ThemeProvider({ children }: ThemeProviderProps) {
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    // Load from localStorage with 'dark' as default
    const saved = localStorage.getItem('theme');
    return (saved as 'light' | 'dark') || 'dark';
  });

  useEffect(() => {
    // Update body class and persist
    document.body.classList.remove('light-mode', 'dark-mode');
    document.body.classList.add(`${theme}-mode`);
    localStorage.setItem('theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme(prev => prev === 'dark' ? 'light' : 'dark');
  };

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}
```

### useTheme Hook

```typescript
export function useTheme() {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}
```

## CSS Variables

**File**: `app/src/theme/variables.css`

### Base Variables (Root)

```css
:root {
  /* Brand Colors */
  --primary: #F89521;
  --primary-hover: #fa9f35;
  --primary-rgb: 248, 149, 33;
  --accent: #00D9FF;

  /* Backgrounds */
  --bg-dark: #111113;
  --surface: #0a0a0a;
  --text: #ffffff;
  --border-color: hsl(var(--hue2), 12%, 20%);

  /* Status Colors */
  --status-purple: #a855f7;
  --status-purple-rgb: 168, 85, 247;
  --status-yellow: #F89521;
  --status-yellow-rgb: 248, 149, 33;
  --status-green: #22c55e;
  --status-green-rgb: 34, 197, 94;
  --status-blue: #3b82f6;
  --status-blue-rgb: 59, 130, 246;
  --status-red: #ef4444;
  --status-red-rgb: 239, 68, 68;
  --status-gray: #6b7280;
  --status-gray-rgb: 107, 114, 128;

  /* Spacing & Effects */
  --hue1: 25;
  --hue2: 240;
  --radius: 22px;
  --ease: cubic-bezier(0.4, 0, 0.2, 1);
}
```

### Light Mode Overrides

```css
body.light-mode {
  --text: #1a1a1a;
  --surface: #ffffff;
  --bg-dark: #ffffff;
  background: #ffffff;
  background-image: radial-gradient(circle, #e0e0e0 1px, transparent 1px);
  background-size: 20px 20px;
  color: #1a1a1a;
}
```

### Dark Mode Overrides

```css
body.dark-mode {
  --text: #ffffff;
  --surface: #0a0a0a;
  --bg-dark: #111113;
  background-color: #111113;
  background-image: url("data:image/svg+xml,..."); /* Texture pattern */
  color: #ffffff;
}
```

### Animations

```css
@keyframes slideIn {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes typing {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.5; }
  30% { transform: translateY(-8px); opacity: 1; }
}

@keyframes pulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

@keyframes modalIn {
  from { opacity: 0; transform: scale(0.9); }
  to { opacity: 1; transform: scale(1); }
}
```

### Utility Classes

```css
.animate-slide-in { animation: slideIn 0.4s var(--ease); }
.animate-typing { animation: typing 1.4s infinite; }
.animate-pulse { animation: pulse 2s infinite; }
.animate-pulse-dot { animation: pulse-dot 2s infinite; }
.animate-modal-in { animation: modalIn 0.3s var(--ease); }
```

## Font Configuration

**File**: `app/src/theme/fonts.ts`

```typescript
export const fonts = {
  heading: "'DM Sans', sans-serif",
  body: "'DM Sans', sans-serif"
} as const;

export type FontType = keyof typeof fonts;
```

## Usage Examples

### Basic Theme Toggle

```typescript
import { useTheme } from '../theme';

function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();

  return (
    <button onClick={toggleTheme}>
      {theme === 'dark' ? 'Light Mode' : 'Dark Mode'}
    </button>
  );
}
```

### Using CSS Variables

```tsx
// Inline styles
<div style={{
  backgroundColor: 'var(--surface)',
  color: 'var(--text)',
  borderRadius: 'var(--radius)'
}}>
  Content
</div>

// Tailwind with CSS variables
<div className="bg-[var(--surface)] text-[var(--text)]">
  Content
</div>
```

### Using Status Colors

```tsx
function StatusBadge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    running: 'var(--status-blue)',
    completed: 'var(--status-green)',
    failed: 'var(--status-red)',
    queued: 'var(--status-yellow)',
  };

  return (
    <span style={{ color: colorMap[status] || 'var(--status-gray)' }}>
      {status}
    </span>
  );
}
```

### Conditional Styling Based on Theme

```typescript
import { useTheme } from '../theme';

function Logo() {
  const { theme } = useTheme();

  return (
    <img
      src={theme === 'dark' ? '/logo-light.svg' : '/logo-dark.svg'}
      alt="Logo"
    />
  );
}
```

### Using Animation Classes

```tsx
// Modal with entrance animation
<div className="animate-modal-in">
  <Modal />
</div>

// Typing indicator
<div className="flex gap-1">
  <span className="animate-typing" style={{ animationDelay: '0s' }}>.</span>
  <span className="animate-typing" style={{ animationDelay: '0.2s' }}>.</span>
  <span className="animate-typing" style={{ animationDelay: '0.4s' }}>.</span>
</div>
```

## App Setup

Wrap your app with ThemeProvider and import variables.css:

```typescript
// main.tsx
import { ThemeProvider } from './theme';
import './theme/variables.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <ThemeProvider>
    <App />
  </ThemeProvider>
);
```

## CSS Variable Reference

| Variable | Dark Mode | Light Mode | Purpose |
|----------|-----------|------------|---------|
| `--primary` | #F89521 | #F89521 | Brand orange |
| `--primary-hover` | #fa9f35 | #fa9f35 | Hover state |
| `--accent` | #00D9FF | #00D9FF | Accent blue |
| `--bg-dark` | #111113 | #ffffff | Page background |
| `--surface` | #0a0a0a | #ffffff | Card/surface |
| `--text` | #ffffff | #1a1a1a | Text color |
| `--border-color` | hsl(240, 12%, 20%) | hsl(240, 12%, 20%) | Borders |
| `--radius` | 22px | 22px | Border radius |
| `--ease` | cubic-bezier(0.4, 0, 0.2, 1) | - | Animation easing |
