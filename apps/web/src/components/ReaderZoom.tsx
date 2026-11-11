import { useCallback, useEffect, useRef, useState } from 'react';

export type ReaderZoomMode = 'vertical' | 'horizontal';

interface ReaderZoomOptions {
  mode: ReaderZoomMode;
  /** Смена главы/режима сбрасывает масштаб. */
  resetKey: string;
  /** Появление корневого элемента (глава догрузилась) перевешивает слушатели. */
  rootKey?: string;
  /** Вызывается при двойном касании — страница отменяет отложенный одиночный тап. */
  onDoubleTap?: () => void;
  onGestureStart?: () => void;
}

interface ZoomState {
  scale: number;
  tx: number;
  ty: number;
}

type Gesture =
  | {
      type: 'pinch';
      el: HTMLElement;
      startDist: number;
      startScale: number;
      baseLeft: number;
      baseTop: number;
      anchorX: number;
      anchorY: number;
    }
  | {
      type: 'pan';
      el: HTMLElement;
      startX: number;
      startY: number;
      startTx: number;
      startTy: number;
    };

interface TapCandidate {
  x: number;
  y: number;
  time: number;
  surface: HTMLElement;
  moved: boolean;
}

const MIN_SCALE = 1;
const MAX_SCALE = 4;
const DOUBLE_TAP_SCALE = 2.5;
const DOUBLE_TAP_DELAY = 320;
const TAP_SLOP = 14;
const PAN_START_SLOP = 4;
const CLICK_SUPPRESS_MS = 480;
const PAN_MARGIN = 24;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function distance(a: Touch, b: Touch): number {
  return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
}

function midpoint(a: Touch, b: Touch): { x: number; y: number } {
  return { x: (a.clientX + b.clientX) / 2, y: (a.clientY + b.clientY) / 2 };
}

function applyTransform(el: HTMLElement, state: ZoomState) {
  if (state.scale <= MIN_SCALE + 0.001) {
    el.style.transform = '';
    el.classList.remove('is-zoomed');
    return;
  }
  el.style.transformOrigin = '0 0';
  el.style.transform = `translate3d(${state.tx}px, ${state.ty}px, 0) scale(${state.scale})`;
  el.classList.add('is-zoomed');
}

function clampZoom(el: HTMLElement, state: ZoomState): ZoomState {
  if (state.scale <= MIN_SCALE + 0.001) return { scale: 1, tx: 0, ty: 0 };
  const width = el.offsetWidth;
  const height = el.offsetHeight;
  if (width <= 0 || height <= 0) return state;
  const maxTx = PAN_MARGIN;
  const minTx = width - width * state.scale - PAN_MARGIN;
  const maxTy = PAN_MARGIN;
  const minTy = height - height * state.scale - PAN_MARGIN;
  return {
    scale: state.scale,
    tx: clamp(state.tx, Math.min(minTx, maxTx), Math.max(minTx, maxTx)),
    ty: clamp(state.ty, Math.min(minTy, maxTy), Math.max(minTy, maxTy)),
  };
}

/**
 * Пинч-зум и двойной тап для страниц читалки. Работает только на устройствах
 * с touch-вводом: на десктопе слушатели не вешаются, поведение не меняется.
 */
export function useReaderZoom({ mode, resetKey, rootKey, onDoubleTap, onGestureStart }: ReaderZoomOptions) {
  const rootRef = useRef<HTMLElement | null>(null);
  const [scale, setScale] = useState(1);
  const [isZoomed, setIsZoomed] = useState(false);
  const [touchCapable] = useState(
    () => typeof window !== 'undefined' && (navigator.maxTouchPoints > 0 || 'ontouchstart' in window),
  );

  const stateRef = useRef<ZoomState>({ scale: 1, tx: 0, ty: 0 });
  const zoomedRef = useRef(false);
  const surfaceRef = useRef<HTMLElement | null>(null);
  const lastTapRef = useRef<{ time: number; x: number; y: number; surface: HTMLElement } | null>(null);
  const suppressClickUntilRef = useRef(0);
  const callbacksRef = useRef({ onDoubleTap, onGestureStart });

  useEffect(() => {
    callbacksRef.current = { onDoubleTap, onGestureStart };
  }, [onDoubleTap, onGestureStart]);

  const publish = useCallback(() => {
    const nextScale = stateRef.current.scale;
    setScale(nextScale);
    setIsZoomed(nextScale > MIN_SCALE + 0.001);
    zoomedRef.current = nextScale > MIN_SCALE + 0.001;
  }, []);

  const reset = useCallback(() => {
    const surface = surfaceRef.current;
    if (surface) {
      applyTransform(surface, { scale: 1, tx: 0, ty: 0 });
    }
    surfaceRef.current = null;
    stateRef.current = { scale: 1, tx: 0, ty: 0 };
    lastTapRef.current = null;
    suppressClickUntilRef.current = 0;
    publish();
  }, [publish]);

  useEffect(() => {
    reset();
  }, [reset, resetKey, mode]);

  useEffect(() => {
    const root = rootRef.current;
    if (!touchCapable || !root) return;

    let gesture: Gesture | null = null;
    let gestureMoved = false;
    let tap: TapCandidate | null = null;
    let multiTouch = false;

    const surfaceFor = (target: EventTarget | null): HTMLElement | null => {
      if (!(target instanceof Element)) return null;
      const selector = mode === 'horizontal' ? '.reader-paged__image' : '.reader-page__frame';
      const surface = target.closest(selector);
      return surface instanceof HTMLElement ? surface : null;
    };

    const ensureSurface = (el: HTMLElement) => {
      if (surfaceRef.current && surfaceRef.current !== el) {
        applyTransform(surfaceRef.current, { scale: 1, tx: 0, ty: 0 });
        stateRef.current = { scale: 1, tx: 0, ty: 0 };
      }
      surfaceRef.current = el;
      el.style.transformOrigin = '0 0';
    };

    const beginPinch = (touches: TouchList) => {
      const el =
        surfaceFor(touches[0].target) ??
        surfaceFor(touches[1]?.target ?? null) ??
        surfaceRef.current;
      if (!el) return;
      ensureSurface(el);
      const rect = el.getBoundingClientRect();
      const current = stateRef.current;
      const point = midpoint(touches[0], touches[1]);
      gesture = {
        type: 'pinch',
        el,
        startDist: Math.max(1, distance(touches[0], touches[1])),
        startScale: current.scale,
        baseLeft: rect.left - current.tx,
        baseTop: rect.top - current.ty,
        anchorX: (point.x - rect.left) / current.scale,
        anchorY: (point.y - rect.top) / current.scale,
      };
      multiTouch = true;
      tap = null;
      callbacksRef.current.onGestureStart?.();
    };

    const onTouchStart = (event: TouchEvent) => {
      if (event.touches.length >= 2) {
        beginPinch(event.touches);
        gestureMoved = true;
        if (event.cancelable) event.preventDefault();
        return;
      }
      if (event.touches.length !== 1 || multiTouch) return;

      const touch = event.touches[0];
      const el = surfaceRef.current;
      const zoomed = stateRef.current.scale > MIN_SCALE + 0.001;
      const tapSurface = surfaceFor(touch.target);
      gestureMoved = false;
      // Двойной тап имеет смысл только по самой странице, не по промежуткам.
      tap = tapSurface
        ? {
            x: touch.clientX,
            y: touch.clientY,
            time: Date.now(),
            surface: tapSurface,
            moved: false,
          }
        : null;

      if (el && zoomed && el.contains(touch.target as Node)) {
        gesture = {
          type: 'pan',
          el,
          startX: touch.clientX,
          startY: touch.clientY,
          startTx: stateRef.current.tx,
          startTy: stateRef.current.ty,
        };
        callbacksRef.current.onGestureStart?.();
      }
    };

    const onTouchMove = (event: TouchEvent) => {
      if (event.touches.length >= 2) {
        if (!gesture || gesture.type !== 'pinch') beginPinch(event.touches);
        if (!gesture || gesture.type !== 'pinch') return;
        const active = gesture;
        const nextScale = clamp(
          active.startScale * (distance(event.touches[0], event.touches[1]) / active.startDist),
          MIN_SCALE,
          MAX_SCALE,
        );
        const point = midpoint(event.touches[0], event.touches[1]);
        let next: ZoomState;
        if (nextScale <= MIN_SCALE + 0.01) {
          next = { scale: 1, tx: 0, ty: 0 };
        } else {
          next = clampZoom(active.el, {
            scale: nextScale,
            tx: point.x - active.baseLeft - active.anchorX * nextScale,
            ty: point.y - active.baseTop - active.anchorY * nextScale,
          });
        }
        stateRef.current = next;
        applyTransform(active.el, next);
        gestureMoved = true;
        if (event.cancelable) event.preventDefault();
        return;
      }

      if (gesture?.type === 'pan') {
        const touch = event.touches[0];
        if (!touch) return;
        const dx = touch.clientX - gesture.startX;
        const dy = touch.clientY - gesture.startY;
        if (Math.abs(dx) < PAN_START_SLOP && Math.abs(dy) < PAN_START_SLOP) return;
        gestureMoved = true;
        const next = clampZoom(gesture.el, {
          scale: stateRef.current.scale,
          tx: gesture.startTx + dx,
          ty: gesture.startTy + dy,
        });
        stateRef.current = next;
        applyTransform(gesture.el, next);
        if (event.cancelable) event.preventDefault();
        return;
      }

      if (tap) {
        const touch = event.touches[0];
        if (!touch) return;
        if (Math.hypot(touch.clientX - tap.x, touch.clientY - tap.y) > TAP_SLOP) {
          tap.moved = true;
        }
      }
    };

    const toggleAt = (el: HTMLElement, clientX: number, clientY: number) => {
      ensureSurface(el);
      const rect = el.getBoundingClientRect();
      const current = stateRef.current;
      if (current.scale > MIN_SCALE + 0.05) {
        stateRef.current = { scale: 1, tx: 0, ty: 0 };
      } else {
        const baseLeft = rect.left - current.tx;
        const baseTop = rect.top - current.ty;
        const anchorX = (clientX - rect.left) / current.scale;
        const anchorY = (clientY - rect.top) / current.scale;
        stateRef.current = clampZoom(el, {
          scale: DOUBLE_TAP_SCALE,
          tx: clientX - baseLeft - anchorX * DOUBLE_TAP_SCALE,
          ty: clientY - baseTop - anchorY * DOUBLE_TAP_SCALE,
        });
      }
      applyTransform(el, stateRef.current);
      publish();
    };

    const onTouchEnd = (event: TouchEvent) => {
      if (event.touches.length > 0) return;

      const wasMulti = multiTouch;
      const hadGesture = gesture !== null && (gesture.type === 'pinch' || gestureMoved);
      const candidate = tap;
      const doubleTapSurface = candidate?.surface ?? null;
      multiTouch = false;
      gesture = null;
      gestureMoved = false;
      tap = null;

      if (wasMulti || hadGesture) {
        suppressClickUntilRef.current = Date.now() + CLICK_SUPPRESS_MS;
        publish();
      }

      if (wasMulti || hadGesture || !candidate || candidate.moved) return;
      if (Date.now() - candidate.time > 500) return;

      const now = Date.now();
      const previous = lastTapRef.current;
      if (
        previous &&
        previous.surface === doubleTapSurface &&
        now - previous.time < DOUBLE_TAP_DELAY &&
        Math.hypot(candidate.x - previous.x, candidate.y - previous.y) < 32
      ) {
        lastTapRef.current = null;
        suppressClickUntilRef.current = now + CLICK_SUPPRESS_MS;
        toggleAt(candidate.surface, candidate.x, candidate.y);
        callbacksRef.current.onDoubleTap?.();
      } else {
        lastTapRef.current = {
          time: now,
          x: candidate.x,
          y: candidate.y,
          surface: candidate.surface,
        };
      }
    };

    root.addEventListener('touchstart', onTouchStart, { passive: false });
    root.addEventListener('touchmove', onTouchMove, { passive: false });
    root.addEventListener('touchend', onTouchEnd, { passive: true });
    root.addEventListener('touchcancel', onTouchEnd, { passive: true });

    return () => {
      root.removeEventListener('touchstart', onTouchStart);
      root.removeEventListener('touchmove', onTouchMove);
      root.removeEventListener('touchend', onTouchEnd);
      root.removeEventListener('touchcancel', onTouchEnd);
    };
  }, [mode, publish, reset, rootKey, touchCapable]);

  const shouldSuppressClick = useCallback(
    () => Date.now() < suppressClickUntilRef.current,
    [],
  );

  return {
    rootRef,
    enabled: touchCapable,
    scale,
    isZoomed,
    isZoomedRef: zoomedRef,
    shouldSuppressClick,
    reset,
  };
}
