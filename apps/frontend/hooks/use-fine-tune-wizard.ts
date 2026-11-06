'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useOperationOwner } from './use-operation-owner';
import {
  confirmFineTune,
  previewFineTune,
  type FineTuneKind,
  type FineTuneMode,
  type FineTunePreviewResponse,
} from '@/lib/api/fine-tune';
import { buildScope, normalizeTargets } from '@/lib/utils/fine-tune-scope';

export type FineTuneWizardStep = 'idle' | 'selecting' | 'generating' | 'previewing';

interface UseFineTuneWizardProps {
  resumeId: string;
  outputLanguage?: string;
  /** Called after the fine-tune is persisted (overwrite reload or copy navigation). */
  onApplied?: (result: { mode: FineTuneMode; resumeId: string }) => void | Promise<void>;
  onError?: (error: string) => void;
}

interface UseFineTuneWizardReturn {
  step: FineTuneWizardStep;
  kind: FineTuneKind;
  targets: string[];
  instruction: string;
  preview: FineTunePreviewResponse | null;
  isGenerating: boolean;
  isConfirming: boolean;
  error: string | null;
  open: (presetTargets?: string[]) => void;
  close: () => void;
  setKind: (kind: FineTuneKind) => void;
  setTargets: (targets: string[]) => void;
  setInstruction: (instruction: string) => void;
  generate: () => Promise<void>;
  confirm: (mode: FineTuneMode, title?: string) => Promise<void>;
}

/**
 * State machine for the fine-tune flow:
 * selecting → generating → previewing → (overwrite | copy).
 */
export function useFineTuneWizard({
  resumeId,
  outputLanguage,
  onApplied,
  onError,
}: UseFineTuneWizardProps): UseFineTuneWizardReturn {
  const { begin, isCurrent, invalidate } = useOperationOwner(resumeId);
  const confirming = useRef(false);
  const [step, setStep] = useState<FineTuneWizardStep>('idle');
  const [kind, setKindState] = useState<FineTuneKind>('all');
  const [targets, setTargetsState] = useState<string[]>([]);
  const [instruction, setInstruction] = useState('');
  const [preview, setPreview] = useState<FineTunePreviewResponse | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = useCallback(() => {
    invalidate();
    confirming.current = false;
    setStep('idle');
    setKindState('all');
    setTargetsState([]);
    setInstruction('');
    setPreview(null);
    setError(null);
    setIsGenerating(false);
    setIsConfirming(false);
  }, [invalidate]);

  const open = useCallback(
    (presetTargets?: string[]) => {
      const preset = normalizeTargets(presetTargets ?? []);
      invalidate();
      confirming.current = false;
      setError(null);
      setPreview(null);
      setInstruction('');
      if (preset.length > 0) {
        setKindState('modules');
        setTargetsState(preset);
      } else {
        setKindState('all');
        setTargetsState([]);
      }
      setStep('selecting');
    },
    [invalidate]
  );

  const setKind = useCallback((next: FineTuneKind) => {
    setKindState(next);
    setError(null);
  }, []);

  const setTargets = useCallback((next: string[]) => {
    setTargetsState(normalizeTargets(next));
    setError(null);
  }, []);

  const generate = useCallback(async () => {
    const token = begin();
    if (token === null) return;
    if (kind === 'modules' && targets.length === 0) {
      setError('No module selected');
      return;
    }
    setIsGenerating(true);
    setStep('generating');
    setError(null);
    try {
      const response = await previewFineTune(resumeId, {
        scope: buildScope(kind, targets),
        instruction: instruction.trim() || undefined,
        output_language: outputLanguage,
      });
      if (!isCurrent(token)) return;
      setPreview(response);
      setStep('previewing');
    } catch (err) {
      if (!isCurrent(token)) return;
      const message = err instanceof Error ? err.message : 'Failed to generate preview';
      setError(message);
      setStep('selecting');
      onError?.(message);
    } finally {
      if (isCurrent(token)) setIsGenerating(false);
    }
  }, [resumeId, kind, targets, instruction, outputLanguage, begin, isCurrent, onError]);

  const confirm = useCallback(
    async (mode: FineTuneMode, title?: string) => {
      if (confirming.current || !preview) return;
      const token = begin();
      if (token === null) return;
      confirming.current = true;
      setIsConfirming(true);
      setError(null);
      try {
        const result = await confirmFineTune(resumeId, {
          preview_id: preview.preview_id,
          improved_data: preview.improved_data,
          mode,
          title: title?.trim() || null,
        });
        if (!isCurrent(token)) return;
        await onApplied?.({ mode: result.mode, resumeId: result.resume_id });
        if (!isCurrent(token)) return;
        close();
      } catch (err) {
        if (!isCurrent(token)) return;
        const message = err instanceof Error ? err.message : 'Failed to save fine-tuned resume';
        setError(message);
        onError?.(message);
      } finally {
        if (isCurrent(token)) {
          confirming.current = false;
          setIsConfirming(false);
        }
      }
    },
    [resumeId, preview, begin, isCurrent, onApplied, onError, close]
  );

  useEffect(() => {
    setStep('idle');
  }, [resumeId]);

  return {
    step,
    kind,
    targets,
    instruction,
    preview,
    isGenerating,
    isConfirming,
    error,
    open,
    close,
    setKind,
    setTargets,
    setInstruction,
    generate,
    confirm,
  };
}

export default useFineTuneWizard;
