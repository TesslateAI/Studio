import { createRoot } from 'react-dom/client'
import './theme/variables.css'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <App />
)
