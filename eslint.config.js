const js = require('@eslint/js');

const BROWSER_GLOBALS = Object.fromEntries(['AudioContext', 'Image', 'alert', 'confirm', 'Option', 'clearTimeout', 'console', 'document', 'fetch', 'history', 'localStorage', 'location', 'navigator', 'performance', 'requestAnimationFrame', 'setInterval', 'setTimeout', 'webkitAudioContext', 'window'].map(name => [name, 'readonly']));

module.exports = [
  { ignores: ['dist/**', 'node_modules/**', '.worktrees/**', '.ai-team/**'] },
  js.configs.recommended,
  { rules: { 'no-empty': ['error', { allowEmptyCatch: true }] } },
  { files: ['web/js/**/*.js'], languageOptions: { globals: BROWSER_GLOBALS } },
  { files: ['tests/e2e/**/*.js'], languageOptions: { globals: { document: 'readonly', localStorage: 'readonly', window: 'readonly' } } },
  { files: ['**/*.mjs'], languageOptions: { globals: { process: 'readonly', fetch: 'readonly', setTimeout: 'readonly' } } },
  {
    files: ['server.js', 'scripts/**/*.js', 'tests/**/*.js', '*.config.cjs', '*.config.js'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'commonjs',
      globals: {
        AbortSignal: 'readonly',
        Buffer: 'readonly',
        console: 'readonly',
        exports: 'readonly',
        fetch: 'readonly',
        global: 'readonly',
        module: 'readonly',
        process: 'readonly',
        require: 'readonly',
        setInterval: 'readonly',
        setTimeout: 'readonly',
        __dirname: 'readonly',
        URL: 'readonly',
      },
    },
    rules: {
      'no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
    },
  },
];
