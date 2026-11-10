import { RuleTester } from 'eslint';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import tsParser from '@typescript-eslint/parser';
import rule from '../eslint-local-rules/swiss-tokens.mjs';

/**
 * Governance rule for the Swiss design-system palette: new code may only use
 * brand tokens, never Tailwind's default color scales or hard-coded hex.
 * RuleTester gives deterministic AST-level verification (no file IO).
 */
const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaFeatures: { jsx: true } },
  },
});

// RuleTester.run registers its own cases with the global test runner.
ruleTester.run('swiss-tokens', rule, {
  valid: [
    {
      name: 'brand token utilities',
      code: `const x = <div className="bg-primary text-destructive border-ink" />;`,
    },
    {
      name: 'tinted neutrals and semantic tokens inside cn()',
      code: `const x = <div className={cn('border border-black bg-canvas', isError && 'text-success')} />;`,
    },
    {
      name: 'template literals using only tokens',
      code: "const x = <div className={`min-h-96 ${open ? 'bg-paper-tint text-ink-soft' : ''}`} />;",
    },
    {
      name: 'border-2 is prescribed by the design system (buttons/cards)',
      code: `const x = <button className="border-2 border-black shadow-sw-sm" />;`,
    },
    {
      name: 'legacy allow-list suppresses pre-existing violations',
      filename: join(process.cwd(), 'app/legacy/page.tsx'),
      options: [{ legacyFiles: ['app/legacy/page.tsx'] }],
      code: `const x = <div className="bg-red-50 text-blue-700" />;`,
    },
  ],
  invalid: [
    {
      name: 'palette background utility',
      code: `const x = <div className="bg-red-50" />;`,
      errors: [{ messageId: 'paletteClass' }],
    },
    {
      name: 'palette text utility with opacity modifier',
      code: `const x = <span className="text-blue-700/50" />;`,
      errors: [{ messageId: 'paletteClass' }],
    },
    {
      name: 'arbitrary hex utility',
      code: `const x = <div className="bg-[#F5F5F0]" />;`,
      errors: [{ messageId: 'arbitraryHex' }],
    },
    {
      name: 'palette class inside a template literal quasi',
      code: "const x = <div className={`card ${active ? 'border-red-600' : ''}`} />;",
      errors: [{ messageId: 'paletteClass' }],
    },
    {
      name: 'palette class inside cn() expression container',
      code: `const x = <div className={cn('border border-black', isError && 'border-red-600')} />;`,
      errors: [{ messageId: 'paletteClass' }],
    },
    {
      name: 'two violating tokens produce two reports',
      code: `const x = <div className="bg-red-50 text-blue-700" />;`,
      errors: [{ messageId: 'paletteClass' }, { messageId: 'paletteClass' }],
    },
    {
      name: 'same code without the allow-list entry is enforced',
      filename: join(process.cwd(), 'app/new/page.tsx'),
      options: [{ legacyFiles: ['app/legacy/page.tsx'] }],
      code: `const x = <div className="bg-red-50" />;`,
      errors: [{ messageId: 'paletteClass' }],
    },
  ],
});

describe('swiss-token legacy inventory', () => {
  it('is sorted source-relative JSON covering only governed directories', () => {
    // The allow-list is the debt contract: every entry must stay source-
    // relative and sorted, and migrated files drop out on regeneration.
    const list = JSON.parse(
      readFileSync(join(process.cwd(), 'eslint-local-rules/swiss-token-legacy.json'), 'utf8')
    ) as string[];

    expect(Array.isArray(list)).toBe(true);
    expect(list.length).toBeGreaterThan(0);
    expect(list).toEqual([...list].sort());
    for (const relativePath of list) {
      expect(relativePath).toMatch(/^(app|components|hooks|lib)\//);
    }
  });
});

/**
 * Migration contract: these four default shades are hex-identical to brand
 * tokens (blue-700 = #1D4ED8 = primary, red-600 = #DC2626 = destructive,
 * green-700 = #15803D = success, orange-500 = #F97316 = warning), so they may
 * never appear again — including inside files still grandfathered for OTHER
 * shades, where the ESLint rule stays silent. The guard scans source text so
 * variant-prefixed utilities (hover:bg-blue-700) are caught as well.
 */
const EXACT_EQUIVALENT_SHADE =
  /\b(?:bg|text|border|ring|ring-offset|from|to|via|fill|stroke|divide|outline|caret|accent|decoration|shadow-color|border-x|border-y|border-t|border-r|border-b|border-l)-(?:blue-700|red-600|green-700|orange-500)\b/;

const GOVERNED_DIRS = ['app', 'components', 'hooks', 'lib'];

function collectSourceFiles(dir: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectSourceFiles(full));
    } else if (/\.(tsx?|jsx?)$/.test(entry.name)) {
      files.push(full);
    }
  }
  return files;
}

describe('exact-equivalent shade migration', () => {
  it('has replaced every hex-identical default shade with a brand token', () => {
    const offenders: string[] = [];
    for (const dir of GOVERNED_DIRS) {
      for (const file of collectSourceFiles(dir)) {
        if (EXACT_EQUIVALENT_SHADE.test(readFileSync(file, 'utf8'))) {
          offenders.push(file);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});
