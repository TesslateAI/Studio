import { useState } from 'react';
import { Preloader } from './Preloader';

/**
 * Example usage of the Preloader component
 *
 * Use cases:
 * 1. On application load
 * 2. When logging in
 * 3. When navigating to a new page
 * 4. During any async operation that needs a beautiful loading screen
 */

export function PreloaderExample() {
  const [showPreloader, setShowPreloader] = useState(true);

  const handlePreloaderComplete = () => {
    console.log('Preloader animation completed!');
    setShowPreloader(false);
    // Your app logic here - e.g., redirect to dashboard
  };

  return (
    <div>
      {showPreloader && <Preloader onComplete={handlePreloaderComplete} />}

      {/* Your main app content */}
      {!showPreloader && (
        <div className="min-h-screen bg-black text-white flex items-center justify-center">
          <div className="text-center">
            <h1 className="text-4xl font-bold mb-4">Welcome to Tesslate!</h1>
            <p className="text-gray-400">The preloader animation has completed.</p>
            <button
              onClick={() => setShowPreloader(true)}
              className="mt-8 px-6 py-3 bg-orange-500 hover:bg-orange-600 rounded-lg transition-colors"
            >
              Show Preloader Again
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Alternative Usage: In your App.tsx or Login callback
 *
 * import { Preloader } from './components/Preloader';
 *
 * function App() {
 *   const [isLoading, setIsLoading] = useState(true);
 *
 *   return (
 *     <>
 *       {isLoading && <Preloader onComplete={() => setIsLoading(false)} />}
 *       {!isLoading && <YourMainApp />}
 *     </>
 *   );
 * }
 *
 * // Or in a login callback:
 * const handleLogin = async () => {
 *   setShowPreloader(true);
 *   await loginUser();
 *   // Preloader will auto-hide after animation completes
 * };
 */
