import { createRoot } from 'react-dom/client'
import { PostHogProvider } from 'posthog-js/react'
import './theme/variables.css'
import './index.css'
import App from './App.tsx'

// Easter egg for curious developers 👀
console.log(
  '%c' +
  '\n' +
  '████████╗███████╗███████╗███████╗██╗      █████╗ ████████╗███████╗\n' +
  '╚══██╔══╝██╔════╝██╔════╝██╔════╝██║     ██╔══██╗╚══██╔══╝██╔════╝\n' +
  '   ██║   █████╗  ███████╗███████╗██║     ███████║   ██║   █████╗  \n' +
  '   ██║   ██╔══╝  ╚════██║╚════██║██║     ██╔══██║   ██║   ██╔══╝  \n' +
  '   ██║   ███████╗███████║███████║███████╗██║  ██║   ██║   ███████╗\n' +
  '   ╚═╝   ╚══════╝╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝   ╚═╝   ╚══════╝\n' +
  '\n',
  'color: #ff6b00; font-weight: bold;'
);

console.log(
  '%c🔍 Snooping around our console, are we? We like that! 🕵️\n\n' +
  '%c💼 We\'re looking for curious minds who can\'t resist pressing F12.\n' +
  '%cIf you know your way around React, TypeScript, and Python,\n' +
  '%cand you\'re not afraid of building something actually useful...\n\n' +
  '%c👉 Come work with us! Email: %cmanav@tesslate.com\n\n' +
  '%c⚡ P.S. If you found this, you\'re already hired in our hearts. ❤️',
  'color: #ff6b00; font-size: 16px; font-weight: bold;',
  'color: #ffffff; font-size: 14px;',
  'color: #ffffff; font-size: 14px;',
  'color: #ffffff; font-size: 14px;',
  'color: #4ade80; font-size: 14px; font-weight: bold;',
  'color: #ff6b00; font-size: 14px; font-weight: bold; text-decoration: underline;',
  'color: #a855f7; font-size: 12px; font-style: italic;'
);

// PostHog configuration - only enable if API key is configured
const posthogApiKey = import.meta.env.VITE_PUBLIC_POSTHOG_KEY
const posthogHost = import.meta.env.VITE_PUBLIC_POSTHOG_HOST

const options = {
  api_host: posthogHost || 'https://app.posthog.com',
  // Disable autocapture and other features when no key is configured
  autocapture: !!posthogApiKey,
  capture_pageview: !!posthogApiKey,
  capture_pageleave: !!posthogApiKey,
  disable_session_recording: !posthogApiKey,
} as const

// Render app - PostHogProvider handles missing apiKey gracefully
// but we suppress the console warning by providing a dummy key when not configured
createRoot(document.getElementById('root')!).render(
  posthogApiKey ? (
    <PostHogProvider
      apiKey={posthogApiKey}
      options={options}
    >
      <App />
    </PostHogProvider>
  ) : (
    <App />
  )
)
