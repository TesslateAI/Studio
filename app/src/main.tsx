import { createRoot } from 'react-dom/client'
import { PostHogProvider } from 'posthog-js/react'
import './theme/variables.css'
import './index.css'
import App from './App.tsx'

const options = {
  api_host: import.meta.env.VITE_PUBLIC_POSTHOG_HOST,
  defaults: '2025-05-24',
} as const

createRoot(document.getElementById('root')!).render(
  <PostHogProvider
    apiKey={import.meta.env.VITE_PUBLIC_POSTHOG_KEY}
    options={options}
  >
    <App />
  </PostHogProvider>
)
