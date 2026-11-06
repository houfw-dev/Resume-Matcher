'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchResume, retryProcessing } from '@/lib/api/resume';
import { hasMeaningfulResumeContent } from '@/lib/utils/resume-content';

export type ResumeProcessingStatus = 'processing' | 'ready' | 'failed';

type ResumeData = Awaited<ReturnType<typeof fetchResume>>;

const MAX_POLL_ATTEMPTS = 12;

/**
 * Observe the server-side parse pipeline for one freshly uploaded resume.
 *
 * Mirrors the dashboard's master-resume watcher: the first check fires
 * immediately, background checks use a bounded exponential backoff
 * (3s·2^n, capped at 30s, at most 12 attempts), a hidden tab resumes the
 * poll when it becomes visible, and a legacy `ready` row without
 * user-visible content is surfaced as `failed`.
 *
 * `readyGeneration` increments on every transition INTO a usable `ready`
 * state (again after a retry), so consumers auto-run follow-up work once
 * per completed parse.
 */
export function useResumeProcessing(resumeId: string | null) {
  const [status, setStatus] = useState<ResumeProcessingStatus>('processing');
  const [resume, setResume] = useState<ResumeData | null>(null);
  const [readyGeneration, setReadyGeneration] = useState(0);
  const [attemptsExhausted, setAttemptsExhausted] = useState(false);

  const runRef = useRef(0);
  const attemptsRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const inFlightRef = useRef(false);
  const statusRef = useRef<ResumeProcessingStatus>('processing');

  const setStatusTracked = useCallback((next: ResumeProcessingStatus) => {
    statusRef.current = next;
    setStatus(next);
  }, []);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const observe = useCallback(
    async (id: string, run: number) => {
      const alive = () => runRef.current === run;
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      let data: ResumeData;
      try {
        data = await fetchResume(id);
      } catch (err) {
        console.error('Failed to check resume processing status:', err);
        inFlightRef.current = false;
        if (alive()) setStatusTracked('failed');
        return;
      }
      if (!alive()) {
        inFlightRef.current = false;
        return;
      }
      inFlightRef.current = false;
      const savedStatus = data.raw_resume?.processing_status || 'pending';
      setResume(data);

      if (savedStatus === 'ready' && hasMeaningfulResumeContent(data.processed_resume)) {
        setStatusTracked('ready');
        setReadyGeneration((gen) => gen + 1);
        return;
      }
      if (savedStatus === 'failed' || savedStatus === 'ready') {
        // ready without meaningful content counts as failed (legacy `{}`).
        setStatusTracked('failed');
        return;
      }

      // pending / processing: keep observing with bounded backoff.
      if (attemptsRef.current >= MAX_POLL_ATTEMPTS) {
        setAttemptsExhausted(true);
        setStatusTracked('failed');
        return;
      }
      const delay = Math.min(30_000, 3_000 * 2 ** attemptsRef.current);
      clearTimer();
      timerRef.current = window.setTimeout(function tickWhileVisible() {
        // Hidden tabs do not burn attempts; short-rearm until visible again.
        if (document.hidden) {
          timerRef.current = window.setTimeout(tickWhileVisible, 3_000);
          return;
        }
        attemptsRef.current += 1;
        void observe(id, run);
      }, delay);
    },
    [clearTimer, setStatusTracked]
  );

  // (Re)start the observation whenever the watched resume changes.
  useEffect(() => {
    if (!resumeId) return;
    const run = ++runRef.current;
    attemptsRef.current = 0;
    inFlightRef.current = false;
    setAttemptsExhausted(false);
    setResume(null);
    setStatusTracked('processing');
    void observe(resumeId, run);
    return () => {
      runRef.current += 1;
      clearTimer();
    };
  }, [resumeId, observe, clearTimer, setStatusTracked]);

  // Resume polling immediately when the tab becomes visible again.
  useEffect(() => {
    if (!resumeId) return;
    const handleVisible = () => {
      if (document.visibilityState !== 'visible') return;
      if (statusRef.current !== 'processing' || inFlightRef.current) return;
      clearTimer();
      void observe(resumeId, runRef.current);
    };
    document.addEventListener('visibilitychange', handleVisible);
    return () => document.removeEventListener('visibilitychange', handleVisible);
  }, [resumeId, observe, clearTimer]);

  const retry = useCallback(async () => {
    if (!resumeId) return;
    const run = ++runRef.current;
    clearTimer();
    attemptsRef.current = 0;
    inFlightRef.current = false;
    setAttemptsExhausted(false);
    setStatusTracked('processing');
    try {
      await retryProcessing(resumeId);
    } catch (err) {
      console.error('Retry processing failed:', err);
      if (runRef.current === run) setStatusTracked('failed');
      throw err;
    }
    if (runRef.current !== run) return;
    await observe(resumeId, run);
  }, [resumeId, clearTimer, observe, setStatusTracked]);

  return { status, resume, readyGeneration, attemptsExhausted, retry };
}
