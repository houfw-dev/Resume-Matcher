/**
 * Regenerate swiss-token-legacy.json — the debt inventory for the
 * swiss-tokens ESLint rule.
 *
 * Scans every .ts/.tsx className string for the same patterns the rule
 * forbids and lists every file that still contains one. After migrating a
 * file to brand tokens, rerun this: the cleaned file drops out of the list
 * and the rule immediately starts enforcing it.
 *
 * Run from apps/frontend:  node eslint-local-rules/generate-legacy-list.mjs
 */

import { readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { dirname } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const SCAN_DIRS = ['app', 'components', 'hooks', 'lib'];

const COLOR_PREFIXES =
  '(?:bg|text|border|ring|ring-offset|from|to|via|fill|stroke|divide|outline|caret|accent|decoration|shadow-color|border-x|border-y|border-t|border-r|border-b|border-l)';
const PALETTE_NAMES =
  'red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone';
const PALETTE_CLASS = new RegExp(`${COLOR_PREFIXES}-(?:${PALETTE_NAMES})-\\d{2,3}(?:/\\d+)?`);
const ARBITRARY_HEX = /[a-z-]*\[#[0-9a-fA-F]{3,8}[^\]]*\]/;

function walk(dir) {
  const files = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...walk(full));
    } else if (/\.(tsx?|jsx?)$/.test(entry.name)) {
      files.push(full);
    }
  }
  return files;
}

const offenders = new Set();
for (const scanDir of SCAN_DIRS) {
  for (const file of walk(join(ROOT, scanDir))) {
    // Whole-source scan is deliberately conservative: over-listing a file
    // only delays enforcement; under-listing would break `eslint .` by
    // exposing a pre-existing violation as a new error.
    const source = readFileSync(file, 'utf8');
    if (PALETTE_CLASS.test(source) || ARBITRARY_HEX.test(source)) {
      offenders.add(relative(ROOT, file).replaceAll('\\', '/'));
    }
  }
}

const sorted = [...offenders].sort();
writeFileSync(
  join(ROOT, 'eslint-local-rules', 'swiss-token-legacy.json'),
  `${JSON.stringify(sorted, null, 2)}\n`
);
console.log(`Wrote ${sorted.length} legacy files to swiss-token-legacy.json`);
