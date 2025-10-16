import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { useEffect } from 'react';

function Home() {
  return (
    <div className="min-h-screen bg-gray-100 flex items-center justify-center">
      <div className="bg-white p-8 rounded-lg shadow-md">
        <h1 className="text-3xl font-bold text-gray-800 mb-4">Welcome to Your New Project!</h1>
        <p className="text-gray-600">Start building something amazing.</p>
      </div>
    </div>
  );
}

function App() {
  useEffect(() => {
    // Listen for navigation messages from parent window (Tesslate Studio)
    const handleMessage = (event) => {
      // Security: verify the message is from a trusted origin
      if (event.data && event.data.type === 'navigate') {
        if (event.data.direction === 'back') {
          window.history.back();
        } else if (event.data.direction === 'forward') {
          window.history.forward();
        }
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  useEffect(() => {
    // Notify parent window when URL changes
    const notifyParent = () => {
      if (window.parent !== window) {
        // Get the base path from the import.meta.env
        const basePath = import.meta.env.BASE_URL || '/';
        // Strip the base path from the pathname before sending to parent
        let pathname = window.location.pathname;
        if (basePath !== '/' && pathname.startsWith(basePath)) {
          pathname = pathname.slice(basePath.length) || '/';
        }

        window.parent.postMessage({
          type: 'urlchange',
          url: pathname + window.location.search + window.location.hash
        }, '*');
      }
    };

    // Notify on initial load
    notifyParent();

    // Listen for popstate events (back/forward navigation)
    window.addEventListener('popstate', notifyParent);

    // Listen for pushState/replaceState (programmatic navigation)
    const originalPushState = window.history.pushState;
    const originalReplaceState = window.history.replaceState;

    window.history.pushState = function(...args) {
      originalPushState.apply(this, args);
      notifyParent();
    };

    window.history.replaceState = function(...args) {
      originalReplaceState.apply(this, args);
      notifyParent();
    };

    return () => {
      window.removeEventListener('popstate', notifyParent);
      window.history.pushState = originalPushState;
      window.history.replaceState = originalReplaceState;
    };
  }, []);

  // Get the base path from Vite's import.meta.env
  // This is automatically set by Vite based on the 'base' config option
  const basename = import.meta.env.BASE_URL;

  return (
    <Router basename={basename}>
      <Routes>
        <Route path="/" element={<Home />} />
      </Routes>
    </Router>
  );
}

export default App
