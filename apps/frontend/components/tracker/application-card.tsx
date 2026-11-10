'use client';

import React from 'react';
import { useRouter } from 'next/navigation';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import GripVertical from 'lucide-react/dist/esm/icons/grip-vertical';
import Layers from 'lucide-react/dist/esm/icons/layers';
import FileText from 'lucide-react/dist/esm/icons/file-text';
import { Card } from '@/components/ui/card';
import { useTranslations } from '@/lib/i18n';
import { formatLocaleDate } from '@/lib/utils/format-date';
import type { Application } from '@/lib/api/tracker';

interface ApplicationCardProps {
  application: Application;
  selected: boolean;
  sharedResume: boolean;
  onToggleSelect: (id: string) => void;
  onOpen: (id: string) => void;
  /** Filtered/focused board views hide drag affordances — position math only
   *  holds for the unfiltered column, so reordering is disabled there. */
  dragDisabled?: boolean;
}

export function ApplicationCard({
  application,
  selected,
  sharedResume,
  onToggleSelect,
  onOpen,
  dragDisabled = false,
}: ApplicationCardProps) {
  const { t, locale } = useTranslations();
  const router = useRouter();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: application.application_id,
    disabled: dragDisabled,
  });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  const company = application.company?.trim();
  const role = application.role?.trim();

  const handleViewResume = (event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    router.push(`/resumes/${encodeURIComponent(application.resume_id)}`);
  };

  return (
    <div ref={setNodeRef} style={style}>
      <Card
        variant="interactive"
        noPadding
        className={`p-3 ${selected ? 'ring-2 ring-primary' : ''}`}
      >
        <div className="flex items-start gap-2">
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggleSelect(application.application_id)}
            onClick={(e) => e.stopPropagation()}
            aria-label={t('tracker.card.selectAria')}
            className="mt-1 h-4 w-4 shrink-0 rounded-none border-black accent-primary"
          />

          <button
            type="button"
            onClick={() => onOpen(application.application_id)}
            className="min-w-0 flex-1 text-left"
          >
            <p className="truncate text-sm font-semibold text-ink">
              {company || t('tracker.card.companyUnknown')}
            </p>
            <p className="truncate font-mono text-xs text-ink-soft">
              {role || t('tracker.card.roleUnknown')}
            </p>
            {application.applied_at && (
              <p className="mt-1 font-mono text-[10px] uppercase tracking-wide text-steel-grey">
                {formatLocaleDate(application.applied_at, locale)}
              </p>
            )}
            {sharedResume && (
              <span className="mt-1 inline-flex items-center gap-1 border border-black bg-paper-tint px-1 font-mono text-[10px] uppercase text-ink-soft">
                <Layers className="h-3 w-3" />
                {t('tracker.card.sharedResume')}
              </span>
            )}
          </button>

          <button
            type="button"
            className="mt-0.5 shrink-0 cursor-grab text-steel-grey hover:text-ink active:cursor-grabbing disabled:cursor-not-allowed disabled:opacity-30"
            aria-label={t('tracker.card.dragAria')}
            disabled={dragDisabled}
            {...(dragDisabled ? {} : attributes)}
            {...(dragDisabled ? {} : listeners)}
          >
            <GripVertical className="h-4 w-4" />
          </button>
        </div>

        {/* Reverse link to the applied resume. The detail modal owns the
            /builder edit path; this is the read-only viewer entry. */}
        <button
          type="button"
          onClick={handleViewResume}
          className="mt-2 inline-flex items-center gap-1 self-start border border-black bg-background px-2 py-1 font-mono text-[10px] uppercase tracking-wide text-ink-soft shadow-sw-xs transition-all hover:translate-x-[1px] hover:translate-y-[1px] hover:text-primary hover:shadow-none"
        >
          <FileText className="h-3 w-3" />
          {t('tracker.card.viewResume')}
        </button>
      </Card>
    </div>
  );
}
