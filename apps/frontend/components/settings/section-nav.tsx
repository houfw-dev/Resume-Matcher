'use client';

import { useEffect, useRef, useState } from 'react';
import { RetroTabs, type Tab } from '@/components/ui/retro-tabs';
import { useTranslations } from '@/lib/i18n';
import {
  SETTINGS_SECTIONS,
  buildSectionHash,
  isSettingsSectionId,
  parseSectionHash,
  pickActiveSection,
  sectionAnchorId,
  type SettingsSectionId,
} from '@/lib/utils/settings-sections';

/** Extra gap (px) between the sticky nav band and the highlighted section. */
const SCROLL_SPY_GAP = 8;

export function SettingsSectionNav() {
  const { t } = useTranslations();
  const navRef = useRef<HTMLDivElement>(null);
  const [activeSection, setActiveSection] = useState<SettingsSectionId>('status');

  // jsdom (and some older engines) have no scrollIntoView — optional chaining
  // keeps the click path alive wherever it is missing.
  const scrollToSection = (id: SettingsSectionId) => {
    document
      .getElementById(sectionAnchorId(id))
      ?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  };

  const handleTabChange = (tabId: string) => {
    // Never trust tab ids from DOM events — re-validate against the whitelist.
    if (!isSettingsSectionId(tabId)) return;
    window.history.pushState(null, '', buildSectionHash(tabId));
    setActiveSection(tabId);
    scrollToSection(tabId);
  };

  // Deep link on first paint + back/forward navigation. pushState itself does
  // not fire popstate, so tab clicks drive state directly above.
  useEffect(() => {
    const applyHash = () => {
      const id = parseSectionHash(window.location.hash);
      if (id) {
        setActiveSection(id);
        scrollToSection(id);
      }
    };
    applyHash();
    window.addEventListener('popstate', applyHash);
    return () => window.removeEventListener('popstate', applyHash);
  }, []);

  // Scroll-spy. The page scrolls inside an overflow container, whose scroll
  // events do not bubble — a capture-phase listener on document catches them.
  useEffect(() => {
    const syncActive = () => {
      const bandBottom = navRef.current?.getBoundingClientRect().bottom ?? 0;
      const offset = bandBottom + SCROLL_SPY_GAP;
      const tops = SETTINGS_SECTIONS.flatMap(({ id }) => {
        const el = document.getElementById(sectionAnchorId(id));
        return el ? [{ id, top: el.getBoundingClientRect().top }] : [];
      });
      const next = pickActiveSection(tops, offset);
      if (next && isSettingsSectionId(next)) setActiveSection(next);
    };
    syncActive();
    document.addEventListener('scroll', syncActive, true);
    return () => document.removeEventListener('scroll', syncActive, true);
  }, []);

  const tabs: Tab[] = SETTINGS_SECTIONS.map(({ id, labelKey }) => ({
    id,
    label: t(labelKey),
  }));

  return (
    <nav
      aria-label={t('settings.nav.label')}
      ref={navRef}
      className="sticky top-0 z-10 border-b border-black bg-white px-4 py-2 md:px-8"
    >
      <RetroTabs tabs={tabs} activeTab={activeSection} onTabChange={handleTabChange} />
    </nav>
  );
}
