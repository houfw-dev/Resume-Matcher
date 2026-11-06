import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { SectionHeader } from '@/components/builder/section-header';
import type { SectionMeta } from '@/components/dashboard/resume-component';

vi.mock('@/lib/i18n', () => ({ useTranslations: () => ({ t: (k: string) => k }) }));

function meta(over: Partial<SectionMeta>): SectionMeta {
  return {
    id: 'custom_x',
    key: 'custom_x',
    displayName: '兴趣爱好',
    sectionType: 'text',
    isDefault: false,
    isVisible: true,
    order: 0,
    ...over,
  };
}

describe('SectionHeader', () => {
  it('locks default sections: lock affordance, no rename control, no reorder controls', () => {
    render(
      <SectionHeader
        section={meta({
          id: 'education',
          key: 'education',
          displayName: '教育背景',
          sectionType: 'itemList',
          isDefault: true,
        })}
        onDelete={vi.fn()}
        onToggleVisibility={vi.fn()}
        canDelete
      />
    );

    expect(screen.getByText('教育背景')).toBeInTheDocument();
    expect(
      screen.getByRole('img', { name: 'builder.sectionHeader.titleLocked' })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'builder.sectionHeader.renameSection' })
    ).toBeNull();
    // Section-level reorder was removed entirely.
    expect(screen.queryByRole('button', { name: /moveUp|moveDown/ })).toBeNull();
  });

  it('offers rename only for custom sections and trims the saved name', () => {
    const onRename = vi.fn();
    render(
      <SectionHeader
        section={meta({ displayName: '志愿者' })}
        onRename={onRename}
        validateName={() => null}
        onDelete={vi.fn()}
        onToggleVisibility={vi.fn()}
        canDelete
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'builder.sectionHeader.renameSection' }));
    const input = screen.getByDisplayValue('志愿者');
    fireEvent.change(input, { target: { value: '  志愿者经历  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'common.save' }));

    expect(onRename).toHaveBeenCalledWith('志愿者经历');
  });

  it('blocks saving an invalid rename and shows the mono error line', () => {
    const onRename = vi.fn();
    const validateName = (name: string): string | null =>
      name.trim() === '重复标题' ? 'builder.sectionHeader.duplicateNameError' : null;
    render(
      <SectionHeader
        section={meta({ displayName: '志愿者' })}
        onRename={onRename}
        validateName={validateName}
        onDelete={vi.fn()}
        onToggleVisibility={vi.fn()}
        canDelete
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'builder.sectionHeader.renameSection' }));
    fireEvent.change(screen.getByDisplayValue('志愿者'), { target: { value: '重复标题' } });

    const save = screen.getByRole('button', { name: 'common.save' });
    expect(save).toBeDisabled();
    const error = screen.getByText('builder.sectionHeader.duplicateNameError');
    expect(error).toHaveClass('font-mono', 'text-xs', 'text-destructive');

    fireEvent.keyDown(screen.getByDisplayValue('重复标题'), { key: 'Enter' });
    expect(onRename).not.toHaveBeenCalled();

    // Back to a valid name: save unblocks.
    fireEvent.change(screen.getByDisplayValue('重复标题'), { target: { value: '志愿者经历' } });
    fireEvent.click(save);
    expect(onRename).toHaveBeenCalledWith('志愿者经历');
  });

  it('refuses to save a whitespace-only name even without a validator error', () => {
    const onRename = vi.fn();
    render(
      <SectionHeader
        section={meta({ displayName: '志愿者' })}
        onRename={onRename}
        validateName={() => null}
        onDelete={vi.fn()}
        onToggleVisibility={vi.fn()}
        canDelete
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'builder.sectionHeader.renameSection' }));
    fireEvent.change(screen.getByDisplayValue('志愿者'), { target: { value: '   ' } });
    expect(screen.getByRole('button', { name: 'common.save' })).toBeDisabled();
  });

  it('wires visibility toggle with the correct aria label', () => {
    const onToggleVisibility = vi.fn();
    render(
      <SectionHeader
        section={meta({ displayName: '志愿者' })}
        onDelete={vi.fn()}
        onToggleVisibility={onToggleVisibility}
        canDelete
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'builder.sectionHeader.hideSection' }));
    expect(onToggleVisibility).toHaveBeenCalledTimes(1);
  });
});
