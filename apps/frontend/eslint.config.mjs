import nextCoreWebVitals from 'eslint-config-next/core-web-vitals';
import nextTypescript from 'eslint-config-next/typescript';
import prettierPlugin from 'eslint-plugin-prettier';
import prettierConfig from 'eslint-config-prettier/flat';
import swissTokens from './eslint-local-rules/swiss-tokens.mjs';

const eslintConfig = [
  {
    ignores: [
      'node_modules/**',
      '.next/**',
      'out/**',
      'dist/**',
      '*.config.js',
      '*.config.mjs',
      'next-env.d.ts',
    ],
  },
  ...nextCoreWebVitals,
  ...nextTypescript,
  prettierConfig,
  {
    plugins: {
      prettier: prettierPlugin,
    },
    rules: {
      'prettier/prettier': 'error',
      // Disable new rule from eslint-config-next@16 — existing code uses
      // setState in effects for syncing props and DOM measurements.
      'react-hooks/set-state-in-effect': 'off',
    },
  },
  {
    // Swiss token governance. Scoped to shipped source: test fixtures may
    // legitimately mention forbidden classes as regression strings. Legacy
    // files carrying pre-existing drift are grandfathered inside the rule
    // via eslint-local-rules/swiss-token-legacy.json.
    files: ['app/**', 'components/**', 'hooks/**', 'lib/**'],
    plugins: {
      'local-rules': {
        rules: { 'swiss-tokens': swissTokens },
      },
    },
    rules: {
      'local-rules/swiss-tokens': 'error',
    },
  },
];

export default eslintConfig;
