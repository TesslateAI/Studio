# Tesslate Preloader Component

A beautiful, animated preloader component inspired by premium web design. Features a smooth character animation, progress bar, and logo mask reveal effect.

## Features

- ✨ Character-by-character text animation
- 🎨 Smooth progress bar with custom easing
- 🎭 Logo mask reveal effect with your Tesslate logo
- 📱 Responsive design (works on mobile, tablet, desktop)
- ⚡ Built with GSAP for performant animations
- 🎯 TypeScript support
- 🔄 Callback support for when animation completes

## Installation

The component is already set up! GSAP has been installed as a dependency.

## Usage

### Basic Usage

```tsx
import { Preloader } from './components/Preloader';
import { useState } from 'react';

function App() {
  const [showPreloader, setShowPreloader] = useState(true);

  return (
    <>
      {showPreloader && (
        <Preloader onComplete={() => setShowPreloader(false)} />
      )}
      {!showPreloader && <YourMainContent />}
    </>
  );
}
```

### Use on Login

```tsx
import { Preloader } from './components/Preloader';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

function LoginPage() {
  const [showPreloader, setShowPreloader] = useState(false);
  const navigate = useNavigate();

  const handleLogin = async () => {
    setShowPreloader(true);
    await loginUser();
    // Preloader will auto-complete and navigate
  };

  const handlePreloaderComplete = () => {
    setShowPreloader(false);
    navigate('/dashboard');
  };

  return (
    <>
      {showPreloader && <Preloader onComplete={handlePreloaderComplete} />}
      {/* Your login form */}
    </>
  );
}
```

### Use Globally (Recommended)

Add to your main App.tsx to show on initial app load:

```tsx
// App.tsx
import { Preloader } from './components/Preloader';
import { useState, useEffect } from 'react';

function App() {
  const [isInitialLoad, setIsInitialLoad] = useState(true);

  return (
    <>
      {isInitialLoad && (
        <Preloader onComplete={() => setIsInitialLoad(false)} />
      )}
      <YourRoutes />
    </>
  );
}
```

## Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `onComplete` | `() => void` | `undefined` | Callback function called when the animation completes |

## Animation Timeline

1. **0s - 0.5s**: Logo text characters animate in (random stagger)
2. **0.5s - 1.25s**: Characters repeat animation
3. **0s - 2.8s**: Progress bar fills from left to right (custom stutter ease)
4. **2.8s - 3.7s**: Logo mask scales up 3x
5. **2.8s - 3.65s**: Everything fades out
6. **3.65s - 3.95s**: Container fades out completely
7. **3.95s**: `onComplete` callback fires

**Total Duration: ~4 seconds**

## Customization

### Change the Text

Edit the text in `Preloader.tsx`:

```tsx
const text = 'YourText'; // Change from 'Tesslate'
```

### Change Colors

Update the CSS in the `<style>` block:

```css
.preloader-mask {
  background-color: #1C1917; /* Change mask background */
}

.preloader-progress-bar {
  background-color: #2D2925; /* Change progress bar background */
}

.preloader-bg {
  background-color: #fff; /* Change progress bar fill color */
}

.logo-text {
  color: #fff; /* Change text color */
}
```

### Change Logo

Replace the SVG in the mask URL with your own logo SVG (must be base64 encoded).

## Performance

- Uses GSAP for hardware-accelerated animations
- Fixed positioning to avoid layout shifts
- Minimal DOM elements for optimal performance
- Automatically cleans up animations on unmount

## Browser Support

- Chrome/Edge (latest)
- Firefox (latest)
- Safari (latest)
- Mobile browsers (iOS Safari, Chrome Mobile)

## Notes

- The component uses `position: fixed` and `z-index: 9999` to overlay the entire screen
- Make sure GSAP is installed: `npm install gsap`
- The component is self-contained with inline styles to avoid CSS conflicts
- The animation automatically removes itself from the DOM after completion
