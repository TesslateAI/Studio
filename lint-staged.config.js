module.exports = {
  // Frontend files - lint and format TypeScript/React
  'app/**/*.{ts,tsx}': ['eslint --fix', 'prettier --write'],
  'app/**/*.{js,jsx,json,css,md}': ['prettier --write'],

  // Backend files - lint and format Python
  'orchestrator/**/*.py': ['ruff check --fix', 'ruff format'],
};
