import { describe, expect, it } from 'vitest';
import type { Experience } from '@/components/dashboard/resume-component';
import {
  looksLikeDepartmentLine,
  promoteWorkDepartment,
} from '@/components/resume/work-department';

describe('looksLikeDepartmentLine', () => {
  it.each([
    '全球资金部',
    '研发部',
    '云计算集成部',
    '支付事业部',
    '保险事业群',
    '平台研发中心',
    '基础架构组',
    'Payments Department',
    'Platform Team',
    'Core Division',
  ])('accepts org-unit line: %s', (line) => {
    expect(looksLikeDepartmentLine(line)).toBe(true);
  });

  it.each([
    '负责清结算系统的设计与研发工作',
    '对接外部合作部完成联调，推动项目上线。',
    '性能提升 2.5 倍',
    'JDK 1.8 升级',
    '',
    '部',
  ])('rejects non-org text: %s', (line) => {
    expect(looksLikeDepartmentLine(line)).toBe(false);
  });
});

describe('promoteWorkDepartment', () => {
  it('prefers the parsed department field and leaves descriptions untouched', () => {
    const exp: Experience = {
      id: 1,
      department: '人工填写部门',
      description: ['全球资金部'],
      descriptionStyles: ['plain'],
    };
    expect(promoteWorkDepartment(exp)).toEqual({
      department: '人工填写部门',
      description: ['全球资金部'],
      descriptionStyles: ['plain'],
    });
  });

  it('promotes a sole plain department line out of the description', () => {
    const exp: Experience = {
      id: 1,
      description: ['研发部'],
      descriptionStyles: ['plain'],
    };
    expect(promoteWorkDepartment(exp)).toEqual({
      department: '研发部',
      description: [],
      descriptionStyles: [],
    });
  });

  it('promotes only the first plain line and keeps the following bullets', () => {
    const exp: Experience = {
      id: 1,
      description: ['支付事业部', '负责清结算系统重构', '性能提升 2.5 倍'],
      descriptionStyles: ['plain', 'bullet', 'bullet'],
    };
    expect(promoteWorkDepartment(exp)).toEqual({
      department: '支付事业部',
      description: ['负责清结算系统重构', '性能提升 2.5 倍'],
      descriptionStyles: ['bullet', 'bullet'],
    });
  });

  it('does not promote a bullet-styled or sentence-like first row', () => {
    const bullet: Experience = {
      id: 1,
      description: ['研发部'],
      descriptionStyles: ['bullet'],
    };
    expect(promoteWorkDepartment(bullet).department).toBe('');
    expect(promoteWorkDepartment(bullet).description).toEqual(['研发部']);

    const sentence: Experience = {
      id: 2,
      description: ['负责核心系统的架构设计工作'],
      descriptionStyles: ['plain'],
    };
    expect(promoteWorkDepartment(sentence).department).toBe('');
    expect(promoteWorkDepartment(sentence).description).toEqual(['负责核心系统的架构设计工作']);
  });

  it('tolerates missing arrays without mutating', () => {
    expect(promoteWorkDepartment({ id: 1 })).toEqual({
      department: '',
      description: [],
      descriptionStyles: [],
    });
  });
});
