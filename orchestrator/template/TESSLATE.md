# TESSLATE.md - Project Context

> Context for AI agents working on this project.

## Framework Configuration

**Framework**: Vite + React
**Version**: React 18
**Port**: 5173

**Tech Stack:**
- React 18 with Vite
- Tailwind CSS
- React Router DOM v6 (pre-configured in `src/App.jsx`)

## File Structure

```
src/
├── App.jsx          # Main app with routing
├── main.jsx         # Entry point
├── components/      # Reusable components
├── pages/           # Page components
└── utils/           # Utilities
```

## Development Server

**Start Command**:
```bash
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

**Production Build:**
```bash
npm run build
```
