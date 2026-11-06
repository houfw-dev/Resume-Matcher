// Deterministic canonical casing for technical English terms.
//
// KEEP IN SYNC with apps/backend/app/services/tech_terms.py (same table, same
// regex boundaries, same field coverage): one case-insensitive pass fixes
// casing only ("java" -> "Java", "SPRING BOOT" -> "Spring Boot",
// "mysql集群" -> "MySQL集群"). It never adds/removes/translates anything;
// OCR/typo spelling correction stays the LLM's job.
//
// Boundary semantics: `(?<![A-Za-z0-9]) … (?![A-Za-z0-9])` means adjacency to
// CJK, punctuation or whitespace matches ("Redis集群"), adjacency to another
// ASCII letter/digit does not ("Java" can't match inside "JavaScript",
// "Vue.js" can't match inside "Vue.jsx"), and longest terms win.
import type { ResumeData } from '@/components/dashboard/resume-component';

// Curated mainstream-stack table, canonical casing. Order is irrelevant —
// the alternation is rebuilt longest-first.
export const CANONICAL_TERMS = [
  // JVM ecosystem (longest compound names first)
  'Spring Cloud Alibaba',
  'Spring AI Alibaba',
  'Spring Framework',
  'Spring Boot',
  'Spring Cloud',
  'Spring MVC',
  'Spring AI',
  'MyBatis-Plus',
  'LangChain4j',
  'Elasticsearch',
  'Kubernetes',
  'JavaScript',
  'TypeScript',
  'Element UI',
  'PostgreSQL',
  'ActiveMQ',
  'RabbitMQ',
  'RocketMQ',
  'LangChain',
  'Next.js',
  'Node.js',
  'Nuxt.js',
  'Vue.js',
  'FastAPI',
  'Hibernate',
  'MongoDB',
  'MyBatis',
  'Tailwind CSS',
  'Sentinel',
  'SQL Server',
  'DevOps',
  'Docker',
  'Dubbo',
  'Flask',
  'GitLab',
  'Gradle',
  'GraalVM',
  'GraphQL',
  'Hadoop',
  'Nacos',
  'Nginx',
  'React',
  'Redis',
  'Seata',
  'Spock',
  'Kafka',
  'Linux',
  'Maven',
  'MySQL',
  'NumPy',
  'Pandas',
  'Pulsar',
  'Python',
  'Quartz',
  'Spring',
  'SVN',
  'Thymeleaf',
  'Tomcat',
  'Vert.x',
  'Webpack',
  'Golang',
  'JUnit',
  'Java',
  'JVM',
  'JDK',
  'JRE',
  'CSS',
  'Git',
  'HTML',
  'JSON',
  'K8s',
  'AWS',
  'gRPC',
  'CI/CD',
  'SQL',
  '.NET',
  'C++',
] as const;

const escapeRegExp = (value: string): string => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// Longest-first so compounds win over their prefixes.
const SORTED_TERMS = [...new Set(CANONICAL_TERMS)].sort((a, b) => b.length - a.length);
const TERM_RE = new RegExp(
  `(?<![A-Za-z0-9])(?:${SORTED_TERMS.map(escapeRegExp).join('|')})(?![A-Za-z0-9])`,
  'gi'
);
const CANONICAL_BY_LOWER = new Map<string, string>(
  SORTED_TERMS.map((term) => [term.toLowerCase(), term])
);

/** Replace every known term in one string with its canonical casing. */
export const canonicalizeTermsInText = (value: unknown): unknown => {
  if (typeof value !== 'string' || value.length === 0) {
    return value;
  }
  return value.replace(TERM_RE, (match) => {
    const canonical = CANONICAL_BY_LOWER.get(match.toLowerCase());
    return canonical ?? match;
  });
};

const canonicalizeRows = (rows: unknown): unknown => {
  if (!Array.isArray(rows)) {
    return rows;
  }
  return rows.map((row) => canonicalizeTermsInText(row));
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

/**
 * Apply canonical term casing to a resume's content fields. Pure: the input
 * object is never mutated. Skips years, personalInfo, sectionMeta and URLs.
 */
export const canonicalizeTechTerms = (resume: ResumeData): ResumeData => {
  const data = resume as unknown as Record<string, unknown>;
  const result: Record<string, unknown> = { ...data };

  result.summary = canonicalizeTermsInText(data.summary);

  if (Array.isArray(data.workExperience)) {
    result.workExperience = data.workExperience.filter(isRecord).map((rawEntry) => {
      const entry: Record<string, unknown> = { ...rawEntry };
      for (const field of ['title', 'department'] as const) {
        entry[field] = canonicalizeTermsInText(entry[field]);
      }
      entry.description = canonicalizeRows(entry.description);
      return entry;
    });
  }

  if (Array.isArray(data.personalProjects)) {
    result.personalProjects = data.personalProjects.filter(isRecord).map((rawEntry) => {
      const entry: Record<string, unknown> = { ...rawEntry };
      for (const field of ['name', 'role'] as const) {
        entry[field] = canonicalizeTermsInText(entry[field]);
      }
      entry.description = canonicalizeRows(entry.description);
      return entry;
    });
  }

  if (isRecord(data.additional)) {
    const additional: Record<string, unknown> = { ...data.additional };
    for (const field of [
      'technicalSkills',
      'languages',
      'certificationsTraining',
      'awards',
    ] as const) {
      additional[field] = canonicalizeRows(additional[field]);
    }
    result.additional = additional;
  }

  if (isRecord(data.customSections)) {
    const sections: Record<string, unknown> = {};
    for (const [key, rawSection] of Object.entries(data.customSections)) {
      if (!isRecord(rawSection)) {
        sections[key] = rawSection;
        continue;
      }
      if (rawSection.sectionType === 'itemList') {
        const items = Array.isArray(rawSection.items)
          ? rawSection.items.filter(isRecord).map((rawItem) => {
              const item: Record<string, unknown> = { ...rawItem };
              for (const field of ['title', 'subtitle'] as const) {
                item[field] = canonicalizeTermsInText(item[field]);
              }
              item.description = canonicalizeRows(item.description);
              return item;
            })
          : [];
        sections[key] = { ...rawSection, items };
      } else if (rawSection.sectionType === 'stringList') {
        sections[key] = {
          ...rawSection,
          strings: canonicalizeRows(rawSection.strings),
        };
      } else if (rawSection.sectionType === 'text' && typeof rawSection.text === 'string') {
        sections[key] = {
          ...rawSection,
          text: canonicalizeTermsInText(rawSection.text),
        };
      } else {
        sections[key] = rawSection;
      }
    }
    result.customSections = sections;
  }

  return result as unknown as ResumeData;
};
