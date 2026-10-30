const js = require('@eslint/js');

module.exports = [
  { ignores: ['dist/**', 'node_modules/**', '.worktrees/**', '.ai-team/**'] },
  js.configs.recommended,
  { files: ['dashboard.js'], languageOptions: { globals: { document: 'readonly', fetch: 'readonly', setInterval: 'readonly' } } },
  { files: ['tests/e2e/**/*.js'], languageOptions: { globals: { document: 'readonly', window: 'readonly' } } },
  { files: ['**/*.mjs'], languageOptions: { globals: { process: 'readonly', fetch: 'readonly' } } },
  {
    files: ['server.js', 'scripts/**/*.js', 'tests/**/*.js', '*.config.cjs', '*.config.js'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'commonjs',
      globals: {
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
