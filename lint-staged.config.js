const path = require('path');

// Cross-platform command wrapper: Windows uses cmd /c, Unix uses sh -c
const isWindows = process.platform === 'win32';
const runInDir = (dir, cmd) =>
  isWindows ? `cmd /c "cd ${dir} && ${cmd}"` : `cd ${dir} && ${cmd}`;

module.exports = {
  // Frontend files - lint and format TypeScript/React
  'app/**/*.{ts,tsx}': (filenames) => {
    // Convert to paths relative to app/ for eslint/prettier
    const files = filenames
      .map((f) => path.relative(path.join(__dirname, 'app'), f).replace(/\\/g, '/'))
      .join(' ');
    return [
      runInDir('app', `npx eslint --fix ${files}`),
      runInDir('app', `npx prettier --write ${files}`),
    ];
  },
  'app/**/*.{js,jsx,json,css,md}': (filenames) => {
    const files = filenames
      .map((f) => path.relative(path.join(__dirname, 'app'), f).replace(/\\/g, '/'))
      .join(' ');
    return [runInDir('app', `npx prettier --write ${files}`)];
  },

  // Backend files - lint and format Python
  'orchestrator/**/*.py': ['ruff check --fix', 'ruff format'],
};
