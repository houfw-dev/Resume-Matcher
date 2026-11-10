import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SettingsSectionNav } from '@/components/settings/section-nav';
import { SETTINGS_SECTION_IDS, sectionAnchorId } from '@/lib/utils/settings-sections';

vi.mock('@/lib/i18n', () => ({
  useTranslations: () => ({ t: (key: string) => key, locale: 'en' }),
}));

const SECTION_TOPS: Record<string, number> = {
  status: 120,
  llm: 420,
  content: 760,
  language: 1080,
  danger: 1400,
};

function rect(top: number, bottom = 0): DOMRect {
  return { top, bottom, left: 0, right: 0, width: 0, height: 0, x: 0, y: 0 } as DOMRect;
}

describe('SettingsSectionNav', () => {
  let sectionEls: Record<string, HTMLElement>;
  let pushStateSpy: ReturnType<typeof vi.spyOn>;
  let scrollSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    sectionEls = {} as Record<string, HTMLElement>;
    for (const id of SETTINGS_SECTION_IDS) {
      const el = document.createElement('div');
      el.id = sectionAnchorId(id);
      document.body.appendChild(el);
      sectionEls[id] = el;
    }

    pushStateSpy = vi.spyOn(window.history, 'pushState');

    scrollSpy = vi.fn();
    Element.prototype.scrollIntoView =
      scrollSpy as unknown as typeof Element.prototype.scrollIntoView;

    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (
      this: Element
    ) {
      // The sticky nav itself has no section id and sits at the top band.
      if (this.id && this.id.startsWith('settings-section-')) {
        const key = this.id.replace('settings-section-', '');
        return rect(SECTION_TOPS[key] ?? 0);
      }
      return rect(0, 50);
    });

    window.history.replaceState(null, '', '/');
  });

  afterEach(() => {
    cleanup();
    Object.values(sectionEls).forEach((el) => el.remove());
    vi.restoreAllMocks();
  });

  it('renders one tab per whitelisted section with status active by default', () => {
    render(<SettingsSectionNav />);
    for (const id of SETTINGS_SECTION_IDS) {
      const labelKey =
        id === 'language'
          ? 'settings.nav.language'
          : id === 'danger'
            ? 'settings.dangerZone'
            : id === 'llm'
              ? 'settings.llmConfigurationTitle'
              : id === 'content'
                ? 'settings.contentGeneration.title'
                : 'settings.systemStatus.title';
      expect(screen.getByRole('button', { name: labelKey })).toBeDefined();
    }
    const statusTab = screen.getByRole('button', { name: 'settings.systemStatus.title' });
    expect(statusTab.className).toContain('font-bold');
    expect(
      screen.getByRole('button', { name: 'settings.llmConfigurationTitle' }).className
    ).not.toContain('font-bold');
    expect(screen.getByRole('navigation', { name: 'settings.nav.label' })).toBeDefined();
  });

  it('clicking a tab pushes the hash, scrolls the section and marks it active', () => {
    render(<SettingsSectionNav />);
    const llmTab = screen.getByRole('button', { name: 'settings.llmConfigurationTitle' });
    fireEvent.click(llmTab);

    expect(pushStateSpy).toHaveBeenCalledWith(null, '', '#llm');
    expect(
      scrollSpy.mock.instances.some((el) => (el as HTMLElement).id === sectionAnchorId('llm'))
    ).toBe(true);
    expect(llmTab.className).toContain('font-bold');
  });

  it('deep-links to the section named in the initial hash', () => {
    window.history.replaceState(null, '', '#content');
    render(<SettingsSectionNav />);

    const contentTab = screen.getByRole('button', { name: 'settings.contentGeneration.title' });
    expect(contentTab.className).toContain('font-bold');
    expect(
      scrollSpy.mock.instances.some((el) => (el as HTMLElement).id === sectionAnchorId('content'))
    ).toBe(true);
  });

  it('ignores an unknown initial hash and keeps the default tab', () => {
    window.history.replaceState(null, '', '#billing');
    render(<SettingsSectionNav />);

    expect(scrollSpy).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'settings.systemStatus.title' }).className).toContain(
      'font-bold'
    );
  });

  it('reacts to browser back/forward via popstate', () => {
    render(<SettingsSectionNav />);
    window.history.pushState(null, '', '#danger');
    fireEvent.popState(window);

    expect(screen.getByRole('button', { name: 'settings.dangerZone' }).className).toContain(
      'font-bold'
    );
    expect(
      scrollSpy.mock.instances.some((el) => (el as HTMLElement).id === sectionAnchorId('danger'))
    ).toBe(true);
  });

  it('updates the active tab from the scroll-spy on capture-phase scroll events', () => {
    render(<SettingsSectionNav />);
    // User scrolled: status/llm passed under the 58px nav band, content not yet.
    SECTION_TOPS.status = -300;
    SECTION_TOPS.llm = -40;
    SECTION_TOPS.content = 320;
    fireEvent.scroll(sectionEls.content);

    expect(
      screen.getByRole('button', { name: 'settings.llmConfigurationTitle' }).className
    ).toContain('font-bold');
    expect(
      screen.getByRole('button', { name: 'settings.systemStatus.title' }).className
    ).not.toContain('font-bold');
  });

  it('does not throw when scrollIntoView is unavailable (jsdom-style environment)', () => {
    // Simulate an engine without Element.scrollIntoView.
    Object.defineProperty(sectionEls.language, 'scrollIntoView', {
      value: undefined,
      configurable: true,
    });
    render(<SettingsSectionNav />);
    expect(() =>
      fireEvent.click(screen.getByRole('button', { name: 'settings.nav.language' }))
    ).not.toThrow();
    expect(pushStateSpy).toHaveBeenCalledWith(null, '', '#language');
  });
});
