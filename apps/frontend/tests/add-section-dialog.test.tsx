import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { AddSectionButton, AddSectionDialog } from '@/components/builder/add-section-dialog';
import type { SectionMeta } from '@/components/dashboard/resume-component';

// t returns the key: the six reserved default titles therefore surface as
// their `resume.sections.*` keys, and error strings as their message keys.
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

const existing: SectionMeta[] = [
  meta({ id: 'custom_hobby', key: 'custom_hobby', displayName: '兴趣爱好', order: 0 }),
  meta({
    id: 'custom_hidden',
    key: 'custom_hidden',
    displayName: '隐藏区块',
    isVisible: false,
    order: 1,
  }),
];

function nameInput(): HTMLElement {
  return screen.getByPlaceholderText('builder.customSections.sectionNamePlaceholder');
}

function submitButton(): HTMLElement {
  return screen.getByRole('button', { name: 'builder.addSection' });
}

describe('AddSectionDialog', () => {
  it('disables submit for a blank name', () => {
    render(
      <AddSectionDialog open onOpenChange={vi.fn()} onAdd={vi.fn()} existingSections={existing} />
    );
    expect(submitButton()).toBeDisabled();

    fireEvent.change(nameInput(), { target: { value: '   ' } });
    expect(submitButton()).toBeDisabled();
    // No error paragraph for an empty field — just blocked, not "wrong".
    expect(screen.queryByText('builder.sectionHeader.duplicateNameError')).not.toBeInTheDocument();
  });

  it('blocks a name duplicated by a visible section and shows the duplicate error', () => {
    const onAdd = vi.fn();
    render(
      <AddSectionDialog open onOpenChange={vi.fn()} onAdd={onAdd} existingSections={existing} />
    );

    // Whitespace/case folding: padded + different case must still collide.
    fireEvent.change(nameInput(), { target: { value: ' 兴趣爱好 ' } });
    expect(submitButton()).toBeDisabled();
    expect(screen.getByText('builder.sectionHeader.duplicateNameError')).toBeInTheDocument();

    fireEvent.keyDown(nameInput(), { key: 'Enter' });
    fireEvent.click(submitButton());
    // onAdd must never fire while invalid.
    expect(onAdd).not.toHaveBeenCalled();
  });

  it('allows reusing the name of a hidden section', () => {
    const onAdd = vi.fn();
    render(
      <AddSectionDialog open onOpenChange={vi.fn()} onAdd={onAdd} existingSections={existing} />
    );

    fireEvent.change(nameInput(), { target: { value: '隐藏区块' } });
    expect(submitButton()).not.toBeDisabled();
    fireEvent.click(submitButton());
    expect(onAdd).toHaveBeenCalledWith('隐藏区块', 'text');
  });

  it('blocks reserved default titles in the active locale and canonical English', () => {
    render(
      <AddSectionDialog open onOpenChange={vi.fn()} onAdd={vi.fn()} existingSections={existing} />
    );

    // Active-locale title (t returns the message key).
    fireEvent.change(nameInput(), { target: { value: 'resume.sections.education' } });
    expect(submitButton()).toBeDisabled();
    expect(screen.getByText('builder.sectionHeader.reservedNameError')).toBeInTheDocument();

    // Canonical English names are reserved regardless of the locale list.
    fireEvent.change(nameInput(), { target: { value: 'Education' } });
    expect(submitButton()).toBeDisabled();
    expect(screen.getByText('builder.sectionHeader.reservedNameError')).toBeInTheDocument();
  });

  it('submits the trimmed name with the chosen section type, then closes', () => {
    const onAdd = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <AddSectionDialog
        open
        onOpenChange={onOpenChange}
        onAdd={onAdd}
        existingSections={existing}
      />
    );

    fireEvent.change(nameInput(), { target: { value: '  志愿者经历 ' } });
    fireEvent.click(
      screen.getByRole('button', { name: /builder.customSections.sectionTypes.itemListLabel/ })
    );
    fireEvent.keyDown(nameInput(), { key: 'Enter' });

    expect(onAdd).toHaveBeenCalledTimes(1);
    expect(onAdd).toHaveBeenCalledWith('志愿者经历', 'itemList');
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('resets its inputs after being closed and reopened', () => {
    const onAdd = vi.fn();
    const { rerender } = render(
      <AddSectionDialog open onOpenChange={vi.fn()} onAdd={onAdd} existingSections={existing} />
    );
    fireEvent.change(nameInput(), { target: { value: '出版物' } });
    fireEvent.click(
      screen.getByRole('button', { name: /builder.customSections.sectionTypes.stringListLabel/ })
    );

    // Controlled close + reopen (the parent owns `open`).
    rerender(
      <AddSectionDialog
        open={false}
        onOpenChange={vi.fn()}
        onAdd={onAdd}
        existingSections={existing}
      />
    );
    rerender(
      <AddSectionDialog open onOpenChange={vi.fn()} onAdd={onAdd} existingSections={existing} />
    );

    expect(nameInput()).toHaveValue('');
    expect(submitButton()).toBeDisabled();
    expect(onAdd).not.toHaveBeenCalled();
  });
});

describe('AddSectionButton', () => {
  it('opens the dialog on click and adds through it', () => {
    const onAdd = vi.fn();
    render(<AddSectionButton onAdd={onAdd} existingSections={existing} />);

    fireEvent.click(
      screen.getByRole('button', { name: 'builder.customSections.addCustomSectionButton' })
    );
    fireEvent.change(nameInput(), { target: { value: '资格证书' } });
    fireEvent.click(submitButton());

    expect(onAdd).toHaveBeenCalledWith('资格证书', 'text');
  });
});
