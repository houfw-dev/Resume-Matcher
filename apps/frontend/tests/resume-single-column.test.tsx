import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { ResumeSingleColumn } from '@/components/resume/resume-single-column';
import gridStyles from '@/components/resume/styles/swiss-single.module.css';
import type { ResumeData, SectionMeta } from '@/components/dashboard/resume-component';

vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (k: string) => k }) }));

const meta: SectionMeta[] = [
  {
    id: 'personalInfo',
    key: 'personalInfo',
    displayName: '基本信息',
    sectionType: 'personalInfo',
    isDefault: true,
    isVisible: true,
    order: 0,
  },
  {
    id: 'education',
    key: 'education',
    displayName: '教育背景',
    sectionType: 'itemList',
    isDefault: true,
    isVisible: true,
    order: 1,
  },
  {
    id: 'summary',
    key: 'summary',
    displayName: '个人优势',
    sectionType: 'text',
    isDefault: true,
    isVisible: true,
    order: 2,
  },
  {
    id: 'additional',
    key: 'additional',
    displayName: '专业技能',
    sectionType: 'stringList',
    isDefault: true,
    isVisible: true,
    order: 3,
  },
  {
    id: 'workExperience',
    key: 'workExperience',
    displayName: '工作经历',
    sectionType: 'itemList',
    isDefault: true,
    isVisible: true,
    order: 4,
  },
  {
    id: 'personalProjects',
    key: 'personalProjects',
    displayName: '项目经验',
    sectionType: 'itemList',
    isDefault: true,
    isVisible: true,
    order: 5,
  },
];

const data: ResumeData = {
  personalInfo: { name: '王浩', title: 'Java 开发工程师' },
  summary: '',
  education: [
    {
      id: 1,
      years: '2019.09 - 2021.06',
      institution: '哈尔滨师范大学',
      description: '计算机科学与技术',
      degree: '统招本科',
    },
  ],
  workExperience: [
    {
      id: 1,
      years: '2025.06 - 2025.09',
      company: '佰钧成科技有限公司',
      department: '',
      title: 'Java 开发工程师',
      description: [],
    },
  ],
  personalProjects: [],
  additional: { technicalSkills: ['Java 并发', 'Spring 框架', 'JVM 调优'] },
  sectionMeta: meta,
} as ResumeData;

describe('ResumeSingleColumn', () => {
  it('renders technical skills as an ordered numbered list', () => {
    const { container } = render(<ResumeSingleColumn data={data} />);
    const list = container.querySelector('ol');
    expect(list).not.toBeNull();
    const items = list!.querySelectorAll('li');
    expect(items.length).toBe(3);
    // Number and text are separated by a CSS gap, so no whitespace in textContent.
    expect(items[0].textContent).toMatch(/^1\./);
    expect(items[2].textContent).toMatch(/^3\./);
    expect(screen.getByText('Java 并发')).toBeInTheDocument();
    // The old comma-joined paragraph is gone.
    expect(screen.queryByText('Java 并发, Spring 框架')).toBeNull();
  });

  it('lays education out as four left-aligned columns: time | university | major | degree', () => {
    render(<ResumeSingleColumn data={data} />);

    const institution = screen.getByRole('heading', { level: 4, name: '哈尔滨师范大学' });
    const row = institution.parentElement!;
    expect(row).toHaveClass('text-left');

    const cells = Array.from(row.children);
    expect(cells).toHaveLength(4);
    expect(cells[0].textContent).toBe('2019.09~2021.06');
    expect(cells[1]).toBe(institution);
    expect(cells[1].textContent).toBe('哈尔滨师范大学');
    expect(cells[2].textContent).toBe('计算机科学与技术');
    expect(cells[3].textContent).toBe('统招本科');
    for (const cell of cells) {
      expect(cell).toHaveClass('text-left');
    }
  });

  it('lays work entries without a department out as three justified columns: time | company | role', () => {
    render(<ResumeSingleColumn data={data} />);

    const role = screen.getByRole('heading', { level: 4, name: 'Java 开发工程师' });
    const row = role.parentElement!;
    expect(row).toHaveClass('text-left');
    // 两端对齐： date flush left, role flush right via the entryRole cell.
    // Exact token comparison: under identity CSS modules "entryColumnsWork"
    // is a substring of "entryColumnsWorkThree".
    const classes = row.className.split(/\s+/);
    expect(classes).toContain(gridStyles.entryColumnsWorkThree);
    expect(classes).not.toContain(gridStyles.entryColumnsWork);

    const cells = Array.from(row.children);
    expect(cells).toHaveLength(3);
    expect(cells[0].textContent).toBe('2025.06~2025.09');
    expect(cells[1].textContent).toContain('佰钧成科技有限公司');
    expect(cells[2]).toBe(role);
    expect(cells[2].textContent).toBe('Java 开发工程师');
    expect(cells[2].className).toContain('entryRole');
    expect(cells[2].className).not.toContain('resume-item-title');
    for (const cell of cells.slice(0, 2)) {
      expect(cell).toHaveClass('text-left');
    }
  });

  it('lays work entries with a department out as four justified columns: time | company | department | role', () => {
    const withDepartment: ResumeData = {
      ...data,
      workExperience: [
        {
          id: 1,
          years: '2025.06 - 2025.09',
          company: '佰钧成科技有限公司',
          department: '研发部',
          title: 'Java 开发工程师',
          description: [],
        },
      ],
    };
    render(<ResumeSingleColumn data={withDepartment} />);

    const role = screen.getByRole('heading', { level: 4, name: 'Java 开发工程师' });
    const row = role.parentElement!;
    const classes = row.className.split(/\s+/);
    expect(classes).toContain(gridStyles.entryColumnsWork);
    expect(classes).not.toContain(gridStyles.entryColumnsWorkThree);

    const cells = Array.from(row.children);
    expect(cells).toHaveLength(4);
    expect(cells[0].textContent).toBe('2025.06~2025.09');
    expect(cells[1].textContent).toContain('佰钧成科技有限公司');
    expect(cells[2].textContent).toBe('研发部');
    expect(cells[3]).toBe(role);
  });

  it('lays every project entry out as four columns: name | time | scale | role', () => {
    const projectData: ResumeData = {
      ...(data as object),
      personalProjects: [
        {
          id: 1,
          name: '订单系统',
          years: '2024.03 - 2024.09',
          scale: '5 人团队',
          role: '后端负责人',
          description: ['负责交易链路'],
          descriptionStyles: ['bullet'],
        },
      ],
    } as ResumeData;

    render(<ResumeSingleColumn data={projectData} />);

    const name = screen.getByRole('heading', { level: 4, name: '订单系统' });
    // h4 → name cell → grid row.
    const row = name.parentElement!.parentElement!;
    expect(row).toHaveClass('text-left');

    const cells = Array.from(row.children);
    expect(cells).toHaveLength(4);
    expect(cells[0].textContent).toBe('订单系统');
    expect(cells[1].textContent).toBe('2024.03~2024.09');
    expect(cells[2].textContent).toBe('5 人团队');
    expect(cells[3].textContent).toBe('后端负责人');
    for (const cell of cells) {
      expect(cell).toHaveClass('text-left');
    }

    // The role moved INTO the header row — no standalone subtitle row remains.
    const item = row.parentElement!;
    expect(item.querySelectorAll('[data-sub-label], ol').length).toBeGreaterThan(0);
    expect(item.textContent).toContain('负责交易链路');
  });

  it('keeps project header columns aligned when scale/role are absent', () => {
    const projectData: ResumeData = {
      ...(data as object),
      personalProjects: [{ id: 1, name: '订单系统', years: '2024.03 - 2024.09' }],
    } as ResumeData;

    render(<ResumeSingleColumn data={projectData} />);

    const name = screen.getByRole('heading', { level: 4, name: '订单系统' });
    const cells = Array.from(name.parentElement!.parentElement!.children);
    expect(cells).toHaveLength(4);
    expect(cells[2].textContent).toBe('');
    expect(cells[3].textContent).toBe('');
  });

  it('uses a full-width name row when a project has no date/scale/role', () => {
    const projectData: ResumeData = {
      ...(data as object),
      personalProjects: [{ id: 1, name: 'Omada 内网穿透服务' }],
    } as ResumeData;

    const { container } = render(<ResumeSingleColumn data={projectData} />);

    const name = screen.getByRole('heading', { level: 4, name: 'Omada 内网穿透服务' });
    const row = name.parentElement!;
    // The name cell sits directly on a plain row (one child), not in the
    // four-column grid, so empty metadata tracks never squeeze the title.
    expect(row.children).toHaveLength(1);
    expect(container.textContent).toContain('Omada 内网穿透服务');
  });

  it('places department in its own column, keeps location with the company, and left-aligns bullets', () => {
    const rich: ResumeData = {
      ...(data as object),
      workExperience: [
        {
          id: 1,
          years: '2022.03 - Present',
          company: '示例科技',
          department: '平台研发部',
          title: '不加粗的岗位名',
          location: '深圳',
          description: ['负责交易链路重构', '系统吞吐提升 40%'],
          descriptionStyles: ['bullet', 'bullet'],
        },
      ],
    } as ResumeData;

    render(<ResumeSingleColumn data={rich} />);

    const role = screen.getByRole('heading', {
      level: 4,
      name: '不加粗的岗位名',
    });
    const row = role.parentElement!;
    const cells = Array.from(row.children);
    expect(cells).toHaveLength(4);
    expect(cells[0].textContent).toBe('2022.03~至今');
    // Location stays appended to the company cell; department gets its own.
    expect(cells[1].textContent).toBe('示例科技 · 深圳');
    expect(cells[2].textContent).toBe('平台研发部');
    expect(cells[3].textContent).toBe('不加粗的岗位名');
    expect(cells[3]).toBe(role);
    expect(role.className).toContain('entryRole');
    expect(role.className).not.toContain('resume-item-title');

    const bullets = screen
      .getAllByRole('listitem')
      .filter(
        (li) =>
          li.textContent?.includes('负责交易链路重构') ||
          li.textContent?.includes('系统吞吐提升 40%')
      );
    expect(bullets).toHaveLength(2);
    for (const rowItem of bullets) {
      expect(rowItem).toHaveClass('text-left');
    }
  });

  const zhLabels = {
    gender: '性别',
    age: '年龄',
    educationLevel: '学历',
    workYears: '工作年限',
    jobIntention: '求职意向',
    desiredCity: '意向城市',
    phone: '电话',
    email: '邮箱',
    foreignLanguage: '外语水平',
    website: '个人网站',
    linkedin: '领英',
    github: 'GitHub',
  };

  it('renders the basic-info facts as labeled, left-aligned cells in the Chinese-resume order', () => {
    const headerData: ResumeData = {
      ...(data as object),
      personalInfo: {
        name: '王浩',
        gender: '男',
        age: '28岁',
        educationLevel: '硕士',
        workYears: '5年',
        title: 'Java 开发工程师',
        location: '深圳',
        phone: '13800000000',
        email: 'wanghao@example.com',
        website: 'wanghao.dev',
        linkedin: 'in/wanghao',
        github: 'wanghao',
      },
      additional: {
        technicalSkills: ['Java 并发', 'Spring 框架', 'JVM 调优'],
        languages: ['英语 CET-6', '日语 N2'],
      },
    } as ResumeData;

    const { container } = render(
      <ResumeSingleColumn data={headerData} personalInfoLabels={zhLabels} />
    );

    const name = screen.getByRole('heading', { level: 1, name: '王浩' });
    // No subtitle heading: the job objective lives in a labeled cell.
    expect(screen.queryByRole('heading', { level: 2 })).toBeNull();
    const grid = name.parentElement!.querySelector(':scope > div')!;

    // Fixed three columns: nine facts fill three fully-justified rows.
    const rows = Array.from(grid.children);
    expect(rows).toHaveLength(3);
    expect(rows.map((row) => row.children.length)).toEqual([3, 3, 3]);
    const cells = rows.flatMap((row) => Array.from(row.children));
    expect(cells.map((cell) => cell.textContent)).toEqual([
      '性别男',
      '年龄28岁',
      '学历硕士',
      '工作年限5年',
      '求职意向Java 开发工程师',
      '意向城市深圳',
      '电话13800000000',
      '邮箱wanghao@example.com',
      '外语水平英语 CET-6、日语 N2',
    ]);
    for (const cell of cells) {
      expect(cell).toHaveClass('text-left');
      expect(cell).not.toHaveClass(gridStyles.infoCellSparse);
      expect(cell.querySelector(':scope > span:last-child')).toHaveClass('text-left');
    }

    // The phone is a plain fact: its digits must not be an underlined tel:
    // link like email/website anchors.
    const phoneCell = cells.find((cell) => cell.textContent === '电话13800000000')!;
    expect(phoneCell).toBeTruthy();
    expect(phoneCell.querySelector('a')).toBeNull();
    expect(container.querySelector('a[href^="tel:"]')).toBeNull();

    // Website/LinkedIn/GitHub each carry their localized label before the link.
    const headerText = name.parentElement!.textContent ?? '';
    expect(headerText).toContain('个人网站');
    expect(headerText).toContain('领英');
    expect(headerText).toContain('GitHub');
    expect(screen.getByRole('link', { name: 'wanghao.dev' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'in/wanghao' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'wanghao' })).toBeInTheDocument();

    // Each label sits directly before its anchor inside the same wrapper.
    const websiteLink = screen.getByRole('link', { name: 'wanghao.dev' });
    const websiteLabel = websiteLink.parentElement!.querySelector('span');
    expect(websiteLabel).toHaveTextContent('个人网站');
  });

  it('renders an absolute https website value as a labeled clickable anchor', () => {
    const absoluteUrlData: ResumeData = {
      ...(data as object),
      personalInfo: {
        name: '徐洪晨',
        website: 'https://fengba.blog.csdn.net/',
      },
    } as ResumeData;

    render(<ResumeSingleColumn data={absoluteUrlData} personalInfoLabels={zhLabels} />);

    const anchor = screen.getByRole('link', { name: 'fengba.blog.csdn.net/' });
    expect(anchor.getAttribute('href')).toBe('https://fengba.blog.csdn.net/');
    expect(anchor.parentElement!.querySelector('span')).toHaveTextContent('个人网站');
  });

  it('falls back to the education degree for 学历 when personalInfo omits it', () => {
    const fallbackData: ResumeData = {
      ...(data as object),
      personalInfo: { name: '王浩', title: 'Java 开发工程师' },
    } as ResumeData;

    render(<ResumeSingleColumn data={fallbackData} personalInfoLabels={zhLabels} />);

    const grid = screen
      .getByRole('heading', { level: 1, name: '王浩' })
      .parentElement!.querySelector(':scope > div')!;
    // A two-cell partial row keeps the column tracks and hugs both edges.
    expect(grid.children).toHaveLength(1);
    const row = grid.children[0];
    expect(row.children).toHaveLength(2);
    expect(Array.from(row.children).map((cell) => cell.textContent)).toEqual([
      '学历统招本科',
      '求职意向Java 开发工程师',
    ]);
    for (const cell of Array.from(row.children)) {
      expect(cell).toHaveClass(gridStyles.infoCellSparse);
    }
  });

  it('lays seven facts out as three columns with a one-cell final row that keeps its track', () => {
    const eightFacts: ResumeData = {
      ...(data as object),
      personalInfo: {
        name: '李勇',
        gender: '男',
        educationLevel: '统招本科（985&211)',
        workYears: '15年+（5年大型医院项目，3年电商）',
        title: 'CTO|CIO|架构师 | 技术经理',
        phone: '17888001016',
        email: '434659298@qq.com',
      },
      additional: { languages: ['英语四级'] },
    } as ResumeData;

    render(<ResumeSingleColumn data={eightFacts} personalInfoLabels={zhLabels} />);

    const grid = screen
      .getByRole('heading', { level: 1, name: '李勇' })
      .parentElement!.querySelector(':scope > div')!;
    const rows = Array.from(grid.children);
    expect(rows).toHaveLength(3);
    expect(rows.map((row) => row.children.length)).toEqual([3, 3, 1]);
    // Row order keeps the Chinese-resume fact sequence.
    expect(Array.from(rows[0].children).map((cell) => cell.textContent)).toEqual([
      '性别男',
      '学历统招本科（985&211)',
      '工作年限15年+（5年大型医院项目，3年电商）',
    ]);
    expect(rows[2].children[0]).toHaveTextContent('外语水平英语四级');
    // The lone last-row cell reserves one column track instead of
    // stretching across the full row; full-row cells stretch.
    expect(rows[0].children[0]).not.toHaveClass(gridStyles.infoCellSparse);
    expect(rows[2].children[0]).toHaveClass(gridStyles.infoCellSparse);
  });

  it('keeps language proficiency out of 专业技能: it appears only in the header 外语水平 cell', () => {
    const withLanguages: ResumeData = {
      ...(data as object),
      additional: {
        technicalSkills: ['Java 并发', 'Spring 框架'],
        languages: ['英语 CET-6', '日语 N2'],
      },
    } as ResumeData;

    render(<ResumeSingleColumn data={withLanguages} personalInfoLabels={zhLabels} />);

    // Languages surface in the header fact grid, joined with 、.
    const header = screen.getByRole('heading', { level: 1, name: '王浩' }).parentElement!;
    expect(header.textContent).toContain('外语水平英语 CET-6、日语 N2');

    // Nothing language-related leaks into the 专业技能 section.
    const skillsTitle = screen.getByRole('heading', { level: 3, name: '专业技能' });
    const skillsBlock = skillsTitle.parentElement!;
    expect(skillsBlock.textContent).not.toContain('英语');
    expect(skillsBlock.textContent).not.toContain('日语');
    expect(skillsBlock.textContent).not.toContain('Languages');
    // Skills themselves still render.
    expect(within(skillsBlock).getByText('Java 并发')).toBeInTheDocument();
  });

  it('renders 培训与证书 and 荣誉奖项 as independent titled modules, never inside the skills list', () => {
    const withCerts: ResumeData = {
      ...(data as object),
      additional: {
        technicalSkills: ['Java 并发', 'Spring 框架'],
        certificationsTraining: ['信息系统项目管理师（高项）证书'],
        awards: ['上海市优秀工程师（2022）'],
      },
    } as ResumeData;

    const { container } = render(
      <ResumeSingleColumn
        data={withCerts}
        sectionHeadings={{
          certifications: '培训与证书',
          awards: '荣誉奖项',
          skills: '专业技能',
        }}
      />
    );

    const titles = Array.from(container.querySelectorAll('h3')).map((el) => el.textContent);
    const iSkills = titles.indexOf('专业技能');
    const iWork = titles.indexOf('工作经历');
    const iCerts = titles.indexOf('培训与证书');
    const iAwards = titles.indexOf('荣誉奖项');
    expect(iSkills).toBeGreaterThanOrEqual(0);
    expect(iSkills).toBeLessThan(iWork);
    // The two independent modules are projected to the BACK of the resume,
    // after work experience (and the custom-section cluster).
    expect(iWork).toBeLessThan(iCerts);
    expect(iCerts).toBeLessThan(iAwards);

    // Each module is its own block; the cert text is not inside the skills block.
    const skillsBlock = screen.getByRole('heading', { level: 3, name: '专业技能' }).parentElement!;
    expect(skillsBlock.textContent).not.toContain('信息系统项目管理师');
    const certsBlock = screen.getByRole('heading', { level: 3, name: '培训与证书' }).parentElement!;
    expect(certsBlock.textContent).toContain('信息系统项目管理师（高项）证书');
    const awardsBlock = screen.getByRole('heading', { level: 3, name: '荣誉奖项' }).parentElement!;
    expect(awardsBlock.textContent).toContain('上海市优秀工程师（2022）');
    // A single entry renders as a plain paragraph, no ordered list numbering.
    expect(certsBlock.querySelector('ol')).toBeNull();
    expect(awardsBlock.querySelector('ol')).toBeNull();
  });

  it('strips leaked Markdown emphasis modifiers from every rendered field', async () => {
    // The display-side strip runs in the <Resume> wrapper, so every template
    // (screen + PDF print page) is covered from one place.
    const { default: Resume } = await import('@/components/dashboard/resume-component');
    const leaked: ResumeData = {
      ...(data as object),
      personalInfo: {
        name: '**李勇**',
        educationLevel: '统招本科（**985&211)',
        title: 'CTO',
      },
      additional: { technicalSkills: ['**Java**', 'Python'] },
    } as ResumeData;

    const { container } = render(<Resume resumeData={leaked} />);

    expect(container.textContent).not.toContain('**');
    expect(screen.getByRole('heading', { level: 1, name: '李勇' })).toBeInTheDocument();
    expect(container.textContent).toContain('统招本科（985&211)');
    expect(screen.getByText('Java')).toBeInTheDocument();
  });

  it('renders a collapsed duplicate language only once in the header fact grid', async () => {
    // Old stored rows repeat one fact with different Markdown formatting;
    // after the display strip the two collapse and must de-duplicate.
    const { default: Resume } = await import('@/components/dashboard/resume-component');
    const duplicated: ResumeData = {
      ...(data as object),
      additional: { languages: ['英语四级**', '英语四级', '日语N2'] },
    } as ResumeData;

    const { container } = render(<Resume resumeData={duplicated} />);

    const header = screen.getByRole('heading', { level: 1, name: '王浩' }).parentElement!;
    expect(header.textContent).toContain('Foreign Languages英语四级、日语N2');
    expect(header.textContent).not.toContain('英语四级、英语四级');
    expect(container.textContent).not.toContain('**');
  });

  it('hides the 专业技能 section when only languages are present (header still shows 外语水平)', () => {
    const onlyLanguages: ResumeData = {
      ...(data as object),
      additional: { languages: ['英语 CET-6'] },
    } as ResumeData;

    render(<ResumeSingleColumn data={onlyLanguages} personalInfoLabels={zhLabels} />);

    expect(screen.queryByRole('heading', { level: 3, name: '专业技能' })).toBeNull();
    expect(
      screen.getByRole('heading', { level: 1, name: '王浩' }).parentElement!.textContent
    ).toContain('外语水平英语 CET-6');
  });

  it('omits empty basic-info facts and renders no fact grid/links when nothing is present', () => {
    const empty: ResumeData = {
      ...(data as object),
      personalInfo: { name: '张三' },
      education: [],
      additional: { technicalSkills: ['Java 并发', 'Spring 框架', 'JVM 调优'] },
    } as ResumeData;

    render(<ResumeSingleColumn data={empty} personalInfoLabels={zhLabels} />);

    const name = screen.getByRole('heading', { level: 1, name: '张三' });
    // No fact grid and no links row beneath the name.
    expect(name.parentElement!.querySelector(':scope > div')).toBeNull();
    for (const label of [
      '性别',
      '年龄',
      '学历',
      '工作年限',
      '求职意向',
      '意向城市',
      '电话',
      '邮箱',
      '外语水平',
    ]) {
      expect(screen.queryByText(label)).toBeNull();
    }
  });

  it('renders 个人优势 points as an ordered, left-aligned list without double numbering', () => {
    const withSummary: ResumeData = {
      ...(data as object),
      summary: '1、大厂背景，熟悉高并发\n2、主导支付链路重构\n3、Java/Go 双技术栈',
    } as ResumeData;

    const { container } = render(<ResumeSingleColumn data={withSummary} />);

    const lists = Array.from(container.querySelectorAll('ol'));
    const advantageList = lists.find((list) => list.textContent?.includes('大厂背景'));
    expect(advantageList).toBeDefined();
    expect(advantageList).toHaveClass('text-left');
    const items = advantageList!.querySelectorAll('li');
    expect(items).toHaveLength(3);
    expect(items[0].textContent).toMatch(/^1\./);
    // The source "1、" marker must not be rendered twice.
    expect(items[0].textContent).not.toContain('1、');
    expect(items[2].textContent).toContain('Java/Go 双技术栈');
  });

  it('does not render the 个人优势 section while summary is empty', () => {
    render(<ResumeSingleColumn data={data} />);
    expect(screen.queryByText('个人优势')).toBeNull();
  });

  it('places education second for formal degrees (formal branch DOM order)', () => {
    const { container } = render(<ResumeSingleColumn data={data} />);
    const titles = Array.from(container.querySelectorAll('h3')).map((el) => el.textContent);
    expect(titles.indexOf('教育背景')).toBeGreaterThanOrEqual(0);
    expect(titles.indexOf('教育背景')).toBeLessThan(titles.indexOf('专业技能'));
    expect(titles.indexOf('教育背景')).toBeLessThan(titles.indexOf('工作经历'));
  });

  it('moves education before the end for non-formal degrees (other branch DOM order)', () => {
    const otherMeta: SectionMeta[] = [
      {
        id: 'personalInfo',
        key: 'personalInfo',
        displayName: '基础信息',
        sectionType: 'personalInfo',
        isDefault: true,
        isVisible: true,
        order: 0,
      },
      {
        id: 'summary',
        key: 'summary',
        displayName: '个人优势',
        sectionType: 'text',
        isDefault: true,
        isVisible: true,
        order: 1,
      },
      {
        id: 'additional',
        key: 'additional',
        displayName: '专业技能',
        sectionType: 'stringList',
        isDefault: true,
        isVisible: true,
        order: 2,
      },
      {
        id: 'workExperience',
        key: 'workExperience',
        displayName: '工作经历',
        sectionType: 'itemList',
        isDefault: true,
        isVisible: true,
        order: 3,
      },
      {
        id: 'personalProjects',
        key: 'personalProjects',
        displayName: '项目经验',
        sectionType: 'itemList',
        isDefault: true,
        isVisible: true,
        order: 4,
      },
      {
        id: 'education',
        key: 'education',
        displayName: '教育背景',
        sectionType: 'itemList',
        isDefault: true,
        isVisible: true,
        order: 5,
      },
      {
        id: 'custom_eval',
        key: 'custom_eval',
        displayName: '自我评价',
        sectionType: 'text',
        isDefault: false,
        isVisible: true,
        order: 6,
      },
    ];
    // Stored order is scrambled; the template must reorder by degree branch.
    const scrambled = [...otherMeta].reverse();
    const otherData: ResumeData = {
      ...(data as object),
      summary: '多年后端开发经验，熟悉分布式系统。',
      education: [
        {
          id: 1,
          years: '2013.09 - 2016.06',
          institution: '某职业技术学院',
          description: '软件技术',
          degree: '大专',
        },
      ],
      personalProjects: [
        { id: 1, name: '订单系统', role: '后端开发', description: ['负责交易链路'] },
      ],
      customSections: {
        custom_eval: { sectionType: 'text', text: '踏实稳重，持续学习。' },
      },
      sectionMeta: scrambled,
    } as ResumeData;

    const { container } = render(<ResumeSingleColumn data={otherData} />);
    const titles = Array.from(container.querySelectorAll('h3')).map((el) => el.textContent);
    expect(titles).toEqual([
      '个人优势',
      '专业技能',
      '工作经历',
      '项目经验',
      '教育背景',
      '自我评价',
    ]);
  });
});
