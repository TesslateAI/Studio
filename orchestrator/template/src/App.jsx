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
        // With subdomain routing, always use absolute pathname
        const pathname = window.location.pathname + window.location.search + window.location.hash;

        window.parent.postMessage({
          type: 'urlchange',
          url: pathname
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

  // No basename needed - always at root with subdomain routing!
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Home />} />
      </Routes>
    </Router>
  );
}

export default App
