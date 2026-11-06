'use client';

import {
  useCallback,
  useRef,
  useState,
  type ComponentPropsWithoutRef,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from 'react';

const MIN_PCT = 20;
const MAX_PCT = 80;
const KEYBOARD_STEP_PCT = 2;
const DIVIDER_WIDTH = '10px';

export interface UseSplitPanesResult {
  leftPct: number;
  setLeftPct: (pct: number) => void;
  leftHidden: boolean;
  rightHidden: boolean;
  toggleLeft: () => void;
  toggleRight: () => void;
  /** Restore the initial ratio and show both panes. */
  reset: () => void;
  isDragging: boolean;
  containerRef: RefObject<HTMLDivElement | null>;
  dividerProps: ComponentPropsWithoutRef<'div'>;
  gridTemplateColumns: string;
}

const clampPct = (value: number) => Math.min(MAX_PCT, Math.max(MIN_PCT, value));

/**
 * Draggable two-pane split for a CSS-grid container laid out as
 * `left pane | divider | right pane`. The divider uses pointer capture;
 * arrow keys move it 2%; either pane collapses to 0 width while the other
 * takes the full row (the last visible pane cannot be hidden).
 */
export function useSplitPanes(initialPct = 45): UseSplitPanesResult {
  const [leftPct, setLeftPctState] = useState(initialPct);
  const [leftHidden, setLeftHidden] = useState(false);
  const [rightHidden, setRightHidden] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const draggingRef = useRef(false);

  const setLeftPct = useCallback((pct: number) => {
    setLeftPctState(clampPct(pct));
  }, []);

  const toggleLeft = useCallback(() => {
    // Keep at least one pane visible.
    setLeftHidden((hidden) => (hidden ? false : !rightHidden ? true : hidden));
  }, [rightHidden]);

  const toggleRight = useCallback(() => {
    setRightHidden((hidden) => (hidden ? false : !leftHidden ? true : hidden));
  }, [leftHidden]);

  const reset = useCallback(() => {
    setLeftPctState(initialPct);
    setLeftHidden(false);
    setRightHidden(false);
  }, [initialPct]);

  const updateFromClientX = useCallback((clientX: number) => {
    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    if (rect.width <= 0) return;
    setLeftPctState(clampPct(((clientX - rect.left) / rect.width) * 100));
  }, []);

  const handlePointerDown = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    draggingRef.current = true;
    setIsDragging(true);
    event.currentTarget.setPointerCapture(event.pointerId);
  }, []);

  const handlePointerMove = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (!draggingRef.current) return;
      updateFromClientX(event.clientX);
    },
    [updateFromClientX]
  );

  const endDrag = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current) return;
    draggingRef.current = false;
    setIsDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }, []);

  const handleKeyDown = useCallback((event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      setLeftPctState((pct) => clampPct(pct - KEYBOARD_STEP_PCT));
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      setLeftPctState((pct) => clampPct(pct + KEYBOARD_STEP_PCT));
    }
  }, []);

  const gridTemplateColumns = leftHidden
    ? `0px 0px minmax(0,1fr)`
    : rightHidden
      ? `minmax(0,1fr) 0px 0px`
      : `minmax(0,${leftPct}fr) ${DIVIDER_WIDTH} minmax(0,${100 - leftPct}fr)`;

  return {
    leftPct,
    setLeftPct,
    leftHidden,
    rightHidden,
    toggleLeft,
    toggleRight,
    reset,
    isDragging,
    containerRef,
    gridTemplateColumns,
    dividerProps: {
      role: 'separator',
      'aria-orientation': 'vertical',
      'aria-valuenow': Math.round(leftPct),
      'aria-valuemin': MIN_PCT,
      'aria-valuemax': MAX_PCT,
      tabIndex: 0,
      onPointerDown: handlePointerDown,
      onPointerMove: handlePointerMove,
      onPointerUp: endDrag,
      onPointerCancel: endDrag,
      onKeyDown: handleKeyDown,
    },
  };
}
