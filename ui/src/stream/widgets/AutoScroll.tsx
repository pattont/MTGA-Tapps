import { useEffect, useRef, type ReactNode } from 'react';
import { startScroll, stepScroll, type ScrollState } from '../autoScroll';

/**
 * A list that fits the space its widget leaves it and, when its rows don't
 * fit, scrolls itself (see autoScroll.ts). The frame keeps any fixed
 * background (the overlay's odds band); the inner element scrolls. The
 * animation runs only while the rows overflow.
 */
export function AutoScroll({
  frameClassName,
  className,
  label,
  as: Inner = 'div',
  children,
}: {
  frameClassName: string;
  className: string;
  label?: string;
  as?: 'div' | 'ul';
  children: ReactNode;
}) {
  const frame = useRef<HTMLDivElement>(null);
  const inner = useRef<HTMLElement>(null);

  useEffect(() => {
    const box = frame.current;
    const list = inner.current;
    if (!box || !list) return undefined;
    let raf = 0;
    let state: ScrollState = startScroll(performance.now());
    let last = performance.now();

    const overflow = () => list.scrollHeight - list.clientHeight;
    const mark = (scrolling: boolean, atTop: boolean, atBottom: boolean) => {
      box.classList.toggle('sk-scrolling', scrolling);
      box.classList.toggle('sk-at-top', atTop);
      box.classList.toggle('sk-at-bottom', atBottom);
    };
    const frameStep = (now: number) => {
      const max = overflow();
      state = stepScroll(state, now, now - last, max);
      last = now;
      list.scrollTop = state.position;
      if (max <= 1) {
        mark(false, true, true);
        raf = 0;
        return;
      }
      mark(true, state.position <= 0.5, state.position >= max - 0.5);
      raf = requestAnimationFrame(frameStep);
    };
    // Start the loop when the rows outgrow the frame; it stops itself once they fit.
    const check = () => {
      if (raf === 0 && overflow() > 1) {
        state = startScroll(performance.now());
        last = performance.now();
        raf = requestAnimationFrame(frameStep);
      } else if (overflow() <= 1) {
        list.scrollTop = 0;
        mark(false, true, true);
      }
    };
    check();
    const resize = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(check);
    resize?.observe(list);
    const mutations = new MutationObserver(check);
    mutations.observe(list, { childList: true, subtree: true, characterData: true });
    window.addEventListener('resize', check);
    return () => {
      cancelAnimationFrame(raf);
      resize?.disconnect();
      mutations.disconnect();
      window.removeEventListener('resize', check);
    };
  }, []);

  return (
    <div ref={frame} className={`${frameClassName} sk-at-top sk-at-bottom`}>
      <Inner ref={inner as never} className={`${className} sk-scroller`} aria-label={label}>
        {children}
      </Inner>
    </div>
  );
}
