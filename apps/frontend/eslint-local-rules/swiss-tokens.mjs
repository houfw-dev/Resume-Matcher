/**
 * Swiss design-system token governance.
 *
 * The Swiss International Style pack defines a small, intentional palette
 * exposed as brand tokens (primary/destructive/success/warning/canvas/ink/
 * steel-grey/ink-soft/paper-tint). Tailwind's default color scales
 * (blue-700, red-50, gray-400, arbitrary hex...) bypass those tokens and
 * have drifted across the app; this rule stops NEW drift while the legacy
 * inventory in `swiss-token-legacy.json` is migrated file by file.
 *
 * Note: `border-2` is intentionally NOT banned — the design system prescribes
 * 2px black borders for buttons and cards (see anti-patterns.md checklist).
 * Only color drift is in scope here.
 */

import { readFileSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));

/** Loaded lazily so RuleTester can monkey-patch the list when needed. */
function loadLegacyFiles() {
  const raw = readFileSync(join(HERE, 'swiss-token-legacy.json'), 'utf8');
  return new Set(JSON.parse(raw));
}

const COLOR_PREFIXES =
  '(?:bg|text|border|ring|ring-offset|from|to|via|fill|stroke|divide|outline|caret|accent|decoration|shadow-color|border-x|border-y|border-t|border-r|border-b|border-l)';

const PALETTE_NAMES =
  'red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone';

/** A Tailwind default-scale color utility, e.g. `bg-red-50`, `text-blue-700/50`. */
const PALETTE_CLASS = new RegExp(`^${COLOR_PREFIXES}-(?:${PALETTE_NAMES})-\\d{2,3}(?:/\\d+)?$`);

/** An arbitrary hex utility, e.g. `bg-[#F5F5F0]`, `border-[#DC2626]`. */
const HEX_CLASS = /#[0-9a-fA-F]{3,8}/;

function classifyToken(token) {
  if (PALETTE_CLASS.test(token)) {
    return { messageId: 'paletteClass', token };
  }
  if (token.startsWith('[') && HEX_CLASS.test(token)) {
    return { messageId: 'arbitraryHex', token };
  }
  if (HEX_CLASS.test(token) && token.includes('[#')) {
    return { messageId: 'arbitraryHex', token };
  }
  return null;
}

function checkClassString(source, node, context) {
  for (const rawToken of source.split(/\s+/)) {
    const token = rawToken.trim();
    if (!token) continue;
    const finding = classifyToken(token);
    if (finding) {
      context.report({ node, messageId: finding.messageId, data: { token: finding.token } });
    }
  }
}

/** Collect every statically visible class string inside a className value. */
function visitClassName(attribute, context) {
  const value = attribute.value;
  if (!value) return;

  if (value.type === 'Literal' && typeof value.value === 'string') {
    checkClassString(value.value, value, context);
    return;
  }

  if (value.type !== 'JSXExpressionContainer') return;

  const walk = (node) => {
    if (!node || typeof node !== 'object') return;
    if (node.type === 'Literal' && typeof node.value === 'string') {
      checkClassString(node.value, node, context);
    } else if (node.type === 'TemplateLiteral') {
      for (const quasi of node.quasis) {
        checkClassString(quasi.value.raw, quasi, context);
      }
    }
    for (const key of Object.keys(node)) {
      if (key === 'parent' || key === 'loc' || key === 'range') continue;
      const child = node[key];
      if (Array.isArray(child)) {
        child.forEach(walk);
      } else if (child && typeof child.type === 'string') {
        walk(child);
      }
    }
  };
  walk(value.expression);
}

/** @type {import('eslint').Rule.RuleModule} */
const rule = {
  meta: {
    type: 'problem',
    docs: {
      description:
        'Forbid off-palette Tailwind colors and arbitrary hex; require Swiss brand tokens',
    },
    messages: {
      paletteClass:
        "Tailwind default-scale color utility '{{token}}' — replace with a Swiss brand token (primary/destructive/success/warning/canvas/ink/steel-grey/ink-soft/paper-tint).",
      arbitraryHex:
        "Hard-coded hex utility '{{token}}' — add/use a Swiss brand token instead of an arbitrary value.",
    },
    schema: [
      {
        type: 'object',
        properties: {
          legacyFiles: { type: 'array', items: { type: 'string' } },
        },
        additionalProperties: false,
      },
    ],
  },

  create(context) {
    const option = context.options[0];
    const legacyFiles = option?.legacyFiles ? new Set(option.legacyFiles) : loadLegacyFiles();

    const filename = context.filename || context.getFilename();
    const projectRelative = relative(resolve(HERE, '..'), filename).replaceAll('\\', '/');

    // Legacy debt inventory: these files keep their existing violations but
    // cannot be copied as templates. Clean a file, then delete it from
    // swiss-token-legacy.json to bring the rule back into force there.
    if (legacyFiles.has(projectRelative)) {
      return {};
    }

    return {
      JSXAttribute(node) {
        if (node.name?.name === 'className') {
          visitClassName(node, context);
        }
      },
    };
  },
};

export default rule;
