const path = require('path');

// lint-staged runs commands directly (not via a shell), so `cd dir && cmd`
// breaks because `cd` resolves to /usr/bin/cd instead of the shell builtin.
// Wrap with `sh -c` (or `cmd /c` on Windows) to get proper shell execution.
const isWindows = process.platform === 'win32';
const shell = (cmd) => (isWindows ? `cmd /c "${cmd}"` : `sh -c '${cmd}'`);

module.exports = {
  // Frontend files - lint and format TypeScript/React
  'app/**/*.{ts,tsx}': (filenames) => {
    const files = filenames
      .map((f) => path.relative(path.join(__dirname, 'app'), f).replace(/\\/g, '/'))
      .join(' ');
    return [
      shell(`cd app && npx eslint --fix ${files}`),
      shell(`cd app && npx prettier --write ${files}`),
    ];
  },
  'app/**/*.{js,jsx,json,css,md}': (filenames) => {
    const files = filenames
      .map((f) => path.relative(path.join(__dirname, 'app'), f).replace(/\\/g, '/'))
      .join(' ');
    return [shell(`cd app && npx prettier --write ${files}`)];
  },

  // Backend files - lint and format Python
  'orchestrator/**/*.py': ['ruff check --fix', 'ruff format'],
};
