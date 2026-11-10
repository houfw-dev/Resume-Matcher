import { describe, expect, it } from 'vitest';

import en from '@/messages/en.json';
import es from '@/messages/es.json';
import fr from '@/messages/fr.json';
import ja from '@/messages/ja.json';
import ko from '@/messages/ko.json';
import pt from '@/messages/pt-BR.json';
import zh from '@/messages/zh.json';

/**
 * Terminology unification guard (batch-4 hygiene item).
 *
 * An audit found the pasted-job-description concept rendered under three
 * competing names in zh (职位描述 / 岗位描述 / JD) and resume sections split
 * across 板块 / 模块 / 区块, with smaller synonym drift in the other locales.
 * Each locale now has ONE canonical full term for the pasted text; this test
 * locks that decision so a later translation (or a regenerated locale file)
 * cannot silently reintroduce a synonym. Feature proper names (JD Match,
 * glossed "职位描述（JD）" labels) are allow-listed explicitly rather than
 * banned wholesale.
 */

type JsonObject = Record<string, unknown>;

function flatten(
  node: unknown,
  prefix = '',
  out: Map<string, string> = new Map()
): Map<string, string> {
  if (node === null || typeof node !== 'object') return out;
  if (Array.isArray(node)) return out;
  for (const [key, value] of Object.entries(node as JsonObject)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === 'string') {
      out.set(path, value);
    } else {
      flatten(value, path, out);
    }
  }
  return out;
}

const LOCALE_MESSAGES: Record<string, unknown> = {
  en,
  es,
  fr,
  ja,
  ko,
  'pt-BR': pt,
  zh,
};

interface LocaleTerminologyRule {
  locale: string;
  /** Canonical full term for the pasted job description — must stay in use. */
  canonicalTerm: string;
  /** Synonyms/short forms that must never render inside a translated string. */
  bannedSubstrings: string[];
}

const RULES: LocaleTerminologyRule[] = [
  {
    locale: 'zh',
    canonicalTerm: '职位描述',
    // 岗位描述 was the intruding synonym; 区块 conflicted with the section
    // term 板块 (fine-tune listed "Custom Sections" as 自定义区块).
    bannedSubstrings: ['岗位描述', '区块'],
  },
  {
    locale: 'es',
    canonicalTerm: 'descripción del puesto',
    // tracker used "empleo", prose used the bare abbreviation "la JD", and
    // JD Match alerts invented a third name "comparación con la oferta".
    bannedSubstrings: ['descripción del empleo', 'la JD', 'oferta'],
  },
  {
    locale: 'fr',
    canonicalTerm: 'fiche de poste',
    // The JD Match alerts called it "l'offre" instead of the feature's FP name.
    bannedSubstrings: ['offre'],
  },
  {
    locale: 'ja',
    canonicalTerm: '求人内容',
    // 求人情報 was a one-off variant; bare JD followed by a particle is prose
    // drift (feature names JD一致/JDマッチ and glossed （JD） labels stay).
    bannedSubstrings: ['求人情報', 'JDに', 'JDを', 'JDの'],
  },
  {
    locale: 'ko',
    canonicalTerm: '채용 공고',
    // Alerts renamed the feature to "JD 매칭" (tabs use 채용공고 매칭); the
    // cover-letter hint used a bare JD instead of the canonical term.
    bannedSubstrings: ['JD 매칭', 'JD를'],
  },
  {
    locale: 'pt-BR',
    canonicalTerm: 'descrição da vaga',
    // "na vaga"/"do JD" loosely named the pasted text instead of its term.
    bannedSubstrings: ['na vaga', 'do JD'],
  },
];

describe('terminology unification across locales', () => {
  for (const rule of RULES) {
    describe(rule.locale, () => {
      const entries = flatten(LOCALE_MESSAGES[rule.locale]);

      it('keeps its canonical job-description term in active use', () => {
        const usesCanonical = [...entries.values()].some((value) =>
          value.includes(rule.canonicalTerm)
        );
        expect(usesCanonical).toBe(true);
      });

      it.each(rule.bannedSubstrings)('never renders the banned substring %j', (banned) => {
        const offenders = [...entries.entries()]
          .filter(([, value]) => value.includes(banned))
          .map(([key]) => key);
        expect(offenders).toEqual([]);
      });
    });
  }
});

describe('zh JD abbreviation policy', () => {
  // Bare "JD" survives only as the JD Match feature proper name or inside an
  // explicit full-term gloss. Every other zh string must say 职位描述.
  const ALLOWED_JD_KEYS = [
    'builder.alerts.jdMatchDownloadFailed',
    'builder.alerts.jdMatchDownloadRequiresContext',
    'builder.generatePrompt.jobDescriptionLabel',
    'builder.jdMatch.aboutDescription',
    'builder.jdMatch.aboutTitle',
    'builder.leftPanel.jdMatchAnalysis',
    'builder.previewTabs.jdMatch',
    'coverLetter.studio.jobDescriptionLabel',
  ];

  it('limits JD to feature names and glossed labels on an explicit allow-list', () => {
    const jdKeys = [...flatten(zh).entries()]
      .filter(([, value]) => value.includes('JD'))
      .map(([key]) => key)
      .sort();
    expect(jdKeys).toEqual([...ALLOWED_JD_KEYS].sort());
  });

  it('names the diagnosis mode with the full term, never a bare JD alias', () => {
    const zhFlat = flatten(zh);
    expect(zhFlat.get('diagnosis.modeJdTitle')).toBe('职位描述诊断');
    expect(zhFlat.get('diagnosis.jdHint')).toContain('职位描述诊断');
    expect(zhFlat.get('diagnosis.jdRequiredHint')).toContain('职位描述诊断');
  });

  it('uses 板块 for custom sections everywhere, including the fine-tune module list', () => {
    const zhFlat = flatten(zh);
    expect(zhFlat.get('fineTune.dialog.modules.customSections')).toBe('自定义板块');
    expect(zhFlat.get('builder.customSections.dialogTitle')).toContain('板块');
  });
});

describe('English reference baseline', () => {
  it('keeps "job description" as the source-language canonical term', () => {
    const values = [...flatten(en).values()];
    expect(values.some((value) => value.includes('job description'))).toBe(true);
  });
});
