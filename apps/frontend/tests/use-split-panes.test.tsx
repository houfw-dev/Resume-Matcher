import React from 'react';
import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useSplitPanes } from '@/hooks/use-split-panes';

const fireKey = (
  dividerProps: React.ComponentPropsWithoutRef<'div'>,
  key: 'ArrowLeft' | 'ArrowRight'
) => {
  const preventDefault = vi.fn();
  act(() => {
    dividerProps.onKeyDown?.({
      key,
      preventDefault,
    } as unknown as React.KeyboardEvent<HTMLDivElement>);
  });
  expect(preventDefault).toHaveBeenCalledTimes(1);
};

/** Minimal pointer target with the Element pointer-capture surface the hook uses. */
function pointerTarget() {
  return {
    setPointerCapture: vi.fn(),
    releasePointerCapture: vi.fn(),
    hasPointerCapture: vi.fn(() => true),
  };
}

describe('useSplitPanes keyboard ratio', () => {
  it('moves the divider 2% per arrow press and exposes ARIA range state', () => {
    const { result } = renderHook(() => useSplitPanes(45));
    expect(result.current.leftPct).toBe(45);
    expect(result.current.dividerProps).toMatchObject({
      role: 'separator',
      'aria-orientation': 'vertical',
      'aria-valuenow': 45,
      'aria-valuemin': 20,
      'aria-valuemax': 80,
      tabIndex: 0,
    });

    fireKey(result.current.dividerProps, 'ArrowRight');
    fireKey(result.current.dividerProps, 'ArrowRight');
    fireKey(result.current.dividerProps, 'ArrowRight');
    expect(result.current.leftPct).toBe(51);
    expect(result.current.dividerProps['aria-valuenow']).toBe(51);

    fireKey(result.current.dividerProps, 'ArrowLeft');
    fireKey(result.current.dividerProps, 'ArrowLeft');
    fireKey(result.current.dividerProps, 'ArrowLeft');
    expect(result.current.leftPct).toBe(45);
  });

  it('clamps setLeftPct and keyboard steps to the 20–80% range', () => {
    const { result } = renderHook(() => useSplitPanes(45));
    act(() => result.current.setLeftPct(5));
    expect(result.current.leftPct).toBe(20);
    act(() => result.current.setLeftPct(95));
    expect(result.current.leftPct).toBe(80);

    act(() => result.current.setLeftPct(45));
    for (let i = 0; i < 30; i += 1) fireKey(result.current.dividerProps, 'ArrowRight');
    expect(result.current.leftPct).toBe(80);
    for (let i = 0; i < 30; i += 1) fireKey(result.current.dividerProps, 'ArrowLeft');
    expect(result.current.leftPct).toBe(20);
  });
});

describe('useSplitPanes collapse toggles', () => {
  it('hides the left pane full-width right, and restores the previous ratio', () => {
    const { result } = renderHook(() => useSplitPanes(45));
    expect(result.current.gridTemplateColumns).toBe('minmax(0,45fr) 10px minmax(0,55fr)');

    act(() => result.current.toggleLeft());
    expect(result.current.leftHidden).toBe(true);
    expect(result.current.rightHidden).toBe(false);
    expect(result.current.gridTemplateColumns).toBe('0px 0px minmax(0,1fr)');

    act(() => result.current.toggleLeft());
    expect(result.current.leftHidden).toBe(false);
    expect(result.current.leftPct).toBe(45);
    expect(result.current.gridTemplateColumns).toBe('minmax(0,45fr) 10px minmax(0,55fr)');
  });

  it('hides the right pane full-width left and restores the previous ratio', () => {
    const { result } = renderHook(() => useSplitPanes(60));
    act(() => result.current.toggleRight());
    expect(result.current.rightHidden).toBe(true);
    expect(result.current.gridTemplateColumns).toBe('minmax(0,1fr) 0px 0px');

    act(() => result.current.toggleRight());
    expect(result.current.rightHidden).toBe(false);
    expect(result.current.leftPct).toBe(60);
  });

  it('never hides the last visible pane', () => {
    const { result } = renderHook(() => useSplitPanes(45));
    act(() => result.current.toggleRight());
    expect(result.current.rightHidden).toBe(true);
    act(() => result.current.toggleLeft());
    expect(result.current.leftHidden).toBe(false);

    act(() => result.current.toggleRight());
    act(() => result.current.toggleLeft());
    expect(result.current.leftHidden).toBe(true);
    act(() => result.current.toggleRight());
    expect(result.current.rightHidden).toBe(false);
  });

  it('reset restores the initial ratio and both panes', () => {
    const { result } = renderHook(() => useSplitPanes(45));
    act(() => result.current.setLeftPct(72));
    act(() => result.current.toggleLeft());
    act(() => result.current.reset());
    expect(result.current.leftPct).toBe(45);
    expect(result.current.leftHidden).toBe(false);
    expect(result.current.rightHidden).toBe(false);
  });
});

describe('useSplitPanes pointer drag', () => {
  const mountWithContainer = (width: number) => {
    const hook = renderHook(() => useSplitPanes(45));
    const container = document.createElement('div');
    container.getBoundingClientRect = vi.fn(
      () =>
        ({
          left: 0,
          top: 0,
          right: width,
          bottom: 0,
          width,
          height: 600,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        }) as DOMRect
    );
    act(() => {
      hook.result.current.containerRef.current = container;
    });
    return { ...hook, container };
  };

  const pointerEvent = (target: ReturnType<typeof pointerTarget>, clientX: number, pointerId = 1) =>
    ({
      clientX,
      pointerId,
      preventDefault: vi.fn(),
      currentTarget: target,
    }) as unknown as React.PointerEvent<HTMLDivElement>;

  it('updates the ratio from the container width and releases capture on pointer up', () => {
    const { result } = mountWithContainer(1000);
    const target = pointerTarget();

    act(() => {
      result.current.dividerProps.onPointerDown?.(pointerEvent(target, 450));
    });
    expect(target.setPointerCapture).toHaveBeenCalledWith(1);
    expect(result.current.isDragging).toBe(true);

    act(() => {
      result.current.dividerProps.onPointerMove?.(pointerEvent(target, 600));
    });
    expect(result.current.leftPct).toBe(60);

    act(() => {
      result.current.dividerProps.onPointerMove?.(pointerEvent(target, -200));
    });
    expect(result.current.leftPct).toBe(20);
    act(() => {
      result.current.dividerProps.onPointerMove?.(pointerEvent(target, 2000));
    });
    expect(result.current.leftPct).toBe(80);

    act(() => {
      result.current.dividerProps.onPointerUp?.(pointerEvent(target, 600));
    });
    expect(target.releasePointerCapture).toHaveBeenCalledWith(1);
    expect(result.current.isDragging).toBe(false);

    // Moves after release are ignored.
    act(() => {
      result.current.dividerProps.onPointerMove?.(pointerEvent(target, 500));
    });
    expect(result.current.leftPct).toBe(80);
  });

  it('ignores pointer moves that were never started', () => {
    const { result } = mountWithContainer(1000);
    const target = pointerTarget();
    act(() => {
      result.current.dividerProps.onPointerMove?.(pointerEvent(target, 300));
    });
    expect(result.current.leftPct).toBe(45);
    expect(target.releasePointerCapture).not.toHaveBeenCalled();
  });
});
