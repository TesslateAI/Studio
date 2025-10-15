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
    // Parse and store auth_token from URL on initial load
    const urlParams = new URLSearchParams(window.location.search);
    const authToken = urlParams.get('auth_token');

    if (authToken) {
      // Store the token in localStorage for the dev preview
      localStorage.setItem('auth_token', authToken);

      // Remove the token from the URL to keep it clean
      urlParams.delete('auth_token');
      const newUrl = window.location.pathname +
        (urlParams.toString() ? '?' + urlParams.toString() : '') +
        window.location.hash;
      window.history.replaceState({}, '', newUrl);

      console.log('Auth token stored successfully');
    }
  }, []);

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
        window.parent.postMessage({
          type: 'urlchange',
          url: window.location.pathname + window.location.search + window.location.hash
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

  return (
    <Router>
      <Routes>
        <Route path="/" element={<Home />} />
      </Routes>
    </Router>
  );
}

export default App
